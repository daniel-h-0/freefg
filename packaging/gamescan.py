# SPDX-License-Identifier: MIT
"""Read-only game scanner: from a game's own files (and the launcher's records) decide the executable that renders,
64-bit or not, the graphics API(s) and the DirectX 12 switch, the engine, the upscaler and frame-generation inputs the
game ships, anti-cheat, files other tools added, and what GE-Proton's own per-game fix does to the game.

Nothing here executes anything, writes anything or uses the network: files are opened read-only (PE headers, import,
delay-import, export and version-resource tables and the certificate blob; a literal byte search over the chosen
executable and its engine DLLs; small text files such as Steam's app manifests, its binary appinfo.vdf launch entries,
Heroic's records, the game's own log in its Proton prefix and GE-Proton's protonfixes). compat.py turns a scan into a
verdict; install.py check prints it.

  scan_exe(exe, home)        the game that holds exe, analysed for exe (the one the user chose)
  scan_folder(game)          one game record (installed_games() or a bare folder), analysed for its best executable
  installed_games(home)      every installed Steam and Heroic game (Windows builds and native Linux builds)
"""
import hashlib, json, mmap, os, re, struct
from pathlib import Path

WALK_LIMIT = 250000
HERE = Path(__file__).resolve().parent

# ------------------------------------------------------------------------------------------------------------ PE files
MACHINES = {0x14c: 'x86', 0x8664: 'x64', 0xaa64: 'arm64', 0x1c4: 'arm'}
SIGNERS = [b'NVIDIA Corporation', b'Intel Corporation', b'Advanced Micro Devices', b'Microsoft Corporation',
           b'Epic Games', b'Unity Technologies', b'Valve', b'Easy Anti-Cheat', b'BattlEye']


class PEError(Exception):
    pass


def _cstr(data, off, limit=512):
    end = data.find(b'\0', off, off + limit)
    return data[off:end if end >= 0 else off + limit].decode('latin-1')


class _Image:
    def __init__(self, f, size):
        self.f, self.size = f, size
        head = self.read(0, 4096)
        if head[:2] != b'MZ' or len(head) < 64:
            raise PEError('no MZ header')
        pe = struct.unpack_from('<I', head, 60)[0]
        if pe + 24 > len(head):
            head = self.read(0, pe + 4096)
        if head[pe:pe + 4] != b'PE\0\0' or len(head) < pe + 26:
            raise PEError('no PE signature')
        self.machine, nsec, _, _, _, optsize, self.chars = struct.unpack_from('<HHIIIHH', head, pe + 4)
        opt = pe + 24
        self.magic = struct.unpack_from('<H', head, opt)[0] if len(head) >= opt + 2 else 0
        if self.magic == 0x20b:
            ndirs_off, dirs_off = opt + 108, opt + 112
        elif self.magic == 0x10b:
            ndirs_off, dirs_off = opt + 92, opt + 96
        else:
            raise PEError('unknown optional header')
        self.subsystem = struct.unpack_from('<H', head, opt + 68)[0] if len(head) >= opt + 70 else 0
        ndirs = min(struct.unpack_from('<I', head, ndirs_off)[0], 16) if len(head) >= ndirs_off + 4 else 0
        ndirs = ndirs if len(head) >= dirs_off + 8 * ndirs else 0
        self.dirs = [struct.unpack_from('<II', head, dirs_off + 8 * i) for i in range(ndirs)] + [(0, 0)] * (16 - ndirs)
        sec = opt + optsize
        need = sec + 40 * nsec
        if need > len(head):
            head = self.read(0, need)
        self.sections = []
        for i in range(nsec):
            if sec + 40 * (i + 1) > len(head):
                break
            name, vsize, va, rawsize, rawptr = struct.unpack_from('<8sIIII', head, sec + 40 * i)
            self.sections.append((name.rstrip(b'\0').decode('latin-1'), va, max(vsize, rawsize), rawptr, rawsize))

    def read(self, off, n):
        if off < 0 or off >= self.size:
            return b''
        self.f.seek(off)
        return self.f.read(min(n, self.size - off))

    def off(self, rva):
        for _, va, vsize, rawptr, rawsize in self.sections:
            if va <= rva < va + vsize:
                return None if rva - va >= rawsize else rawptr + rva - va
        return None

    def rva_read(self, rva, n):
        o = self.off(rva)
        return b'' if o is None else self.read(o, n)

    def rva_str(self, rva, limit=512):
        return _cstr(self.rva_read(rva, limit), 0, limit)


def _imports(img):
    rva, size = img.dirs[1]
    out = {}
    if not rva:
        return out
    data = img.rva_read(rva, max(size, 20 * 512))
    for i in range(0, len(data) - 19, 20):
        oft, _, _, name, ft = struct.unpack_from('<IIIII', data, i)
        if not name:
            break
        dll = img.rva_str(name).lower()
        funcs = []
        step, flag = (8, 1 << 63) if img.magic == 0x20b else (4, 1 << 31)
        raw = img.rva_read(oft or ft, step * 4096)
        for j in range(0, len(raw) - step + 1, step):
            v = int.from_bytes(raw[j:j + step], 'little')
            if not v:
                break
            if v & flag:
                funcs.append('#%d' % (v & 0xffff))
            elif v < 0x80000000:
                funcs.append(img.rva_str(v + 2, 128))
        out.setdefault(dll, []).extend(funcs)
    return out


def _delay_imports(img):
    rva, size = img.dirs[13]
    out = []
    if not rva:
        return out
    data = img.rva_read(rva, max(size, 32 * 256))
    for i in range(0, len(data) - 31, 32):
        _, name = struct.unpack_from('<II', data, i)
        if not name:
            break
        out.append(img.rva_str(name).lower())
    return out


def _exports(img, limit=4096):
    """(export directory name, [exported names]) or (None, [])."""
    rva, _ = img.dirs[0]
    if not rva:
        return None, []
    d = img.rva_read(rva, 40)
    if len(d) < 40:
        return None, []
    name = img.rva_str(struct.unpack_from('<I', d, 12)[0])
    nnames, names_rva = struct.unpack_from('<I', d, 24)[0], struct.unpack_from('<I', d, 32)[0]
    raw = img.rva_read(names_rva, 4 * min(nnames, limit))
    return name, [img.rva_str(struct.unpack_from('<I', raw, 4 * i)[0], 128) for i in range(len(raw) // 4)]


def _version_blob(img):
    rva, _ = img.dirs[2]
    if not rva:
        return None

    def entries(dir_rva):
        h = img.rva_read(dir_rva, 16)
        if len(h) < 16:
            return []
        named, ids = struct.unpack_from('<HH', h, 12)
        raw = img.rva_read(dir_rva + 16, 8 * min(named + ids, 256))
        return [struct.unpack_from('<II', raw, 8 * i) for i in range(len(raw) // 8)]

    def leaf(off):
        d = img.rva_read(rva + off, 16)
        if len(d) < 8:
            return None
        drva, dsize = struct.unpack_from('<II', d, 0)
        return img.rva_read(drva, min(dsize, 65536))

    for ident, off in entries(rva):
        if ident == 16 and off & 0x80000000:
            for _, off2 in entries(rva + (off & 0x7fffffff)):
                if off2 & 0x80000000:
                    for _, off3 in entries(rva + (off2 & 0x7fffffff)):
                        if not off3 & 0x80000000:
                            return leaf(off3)
                else:
                    return leaf(off2)
    return None


def _walk_utf16_key(blob, start):
    end = blob.find(b'\0\0', start)
    while end >= 0 and (end - start) % 2:
        end = blob.find(b'\0\0', end + 1)
    return end


def _parse_version(blob):
    out = {}
    if not blob:
        return out
    i = blob.find(struct.pack('<I', 0xFEEF04BD))
    if i >= 0 and i + 52 <= len(blob):
        fms, fls, pms, pls = struct.unpack_from('<IIII', blob, i + 8)
        out['file_version'] = '%d.%d.%d.%d' % (fms >> 16, fms & 0xffff, fls >> 16, fls & 0xffff)
        out['product_version'] = '%d.%d.%d.%d' % (pms >> 16, pms & 0xffff, pls >> 16, pls & 0xffff)
    try:
        length, vlen = struct.unpack_from('<HH', blob, 0)
        off = (((6 + 2 * (len('VS_VERSION_INFO') + 1) + 3) & ~3) + vlen + 3) & ~3
        while off + 6 <= min(length, len(blob)):
            clen = struct.unpack_from('<H', blob, off)[0]
            if not clen:
                break
            ckey_end = _walk_utf16_key(blob, off + 6)
            if ckey_end < 0:
                break
            if blob[off + 6:ckey_end].decode('utf-16-le', 'replace') == 'StringFileInfo':
                t = (ckey_end + 2 + 3) & ~3
                while t + 6 <= off + clen:
                    tlen = struct.unpack_from('<H', blob, t)[0]
                    tkey_end = _walk_utf16_key(blob, t + 6)
                    if not tlen or tkey_end < 0:
                        break
                    s = (tkey_end + 2 + 3) & ~3
                    while s + 6 <= t + tlen:
                        slen, svlen, _ = struct.unpack_from('<HHH', blob, s)
                        skey_end = _walk_utf16_key(blob, s + 6)
                        if not slen or skey_end < 0:
                            break
                        key = blob[s + 6:skey_end].decode('utf-16-le', 'replace')
                        v = (skey_end + 2 + 3) & ~3
                        value = blob[v:min(s + slen, v + 2 * svlen)].decode('utf-16-le', 'replace').split('\0')[0].strip()
                        if value:
                            out.setdefault('strings', {})[key] = value
                        s = (s + slen + 3) & ~3
                    t = (t + tlen + 3) & ~3
            off = (off + clen + 3) & ~3
    except (struct.error, ValueError):
        pass
    return out


def pe_parse(path):
    """dict(machine, bits, kind exe/dll, subsystem, dotnet, size, imports {dll: [names]}, delay_imports, export_name,
    exports, version {file_version, product_version, strings}, signed, signers). Raises PEError for a non-PE file."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        img = _Image(f, size)
        res = dict(machine=MACHINES.get(img.machine, hex(img.machine)), bits=64 if img.magic == 0x20b else 32,
                   kind='dll' if img.chars & 0x2000 else 'exe', subsystem={2: 'gui', 3: 'console'}.get(img.subsystem, img.subsystem),
                   dotnet=bool(img.dirs[14][0]), size=size)
        for key, reader, empty in (('imports', _imports, {}), ('delay_imports', _delay_imports, []), ('exports', lambda i: _exports(i), (None, [])),
                                   ('version', lambda i: _parse_version(_version_blob(i)), {})):
            try:
                res[key] = reader(img)
            except (struct.error, ValueError, IndexError):
                res[key] = empty
        res['export_name'], res['exports'] = res['exports']
        crva, csize = img.dirs[4]  # the security directory: a file offset, not an RVA
        res['signed'] = bool(crva and csize)
        blob = img.read(crva, min(csize, 262144)) if res['signed'] else b''
        res['signers'] = sorted(s.decode() for s in SIGNERS if s in blob)
        return res


def pe_strings(path, needles, limit=1 << 31):
    """{needle: True} for each needle found in the file as ASCII or UTF-16LE text (case-sensitive; read-only mmap)."""
    found = {}
    size = os.path.getsize(path)
    if not size:
        return found
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), min(size, limit), access=mmap.ACCESS_READ) as m:
        for n in needles:
            if m.find(n.encode('latin-1')) >= 0 or m.find(n.encode('utf-16-le')) >= 0:
                found[n] = True
    return found


def pe_context(path, needle, width=40):
    """The printable text that follows the first ASCII occurrence of needle, or None."""
    size = os.path.getsize(path)
    if not size:
        return None
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ) as m:
        i = m.find(needle.encode('latin-1'))
        return m[i:i + width].split(b'\0')[0].decode('latin-1', 'replace') if i >= 0 else None


# --------------------------------------------------------------------------------------------------- launcher records
_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def text_vdf(text):
    """Valve's text KeyValues (app manifests, config.vdf, localconfig.vdf) as nested dicts, keys in lower case."""
    root, key = {}, None
    stack = [root]
    for m in _TOK.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == '{':
            d = {}
            stack[-1][(key or '').lower()] = d
            stack.append(d)
            key = None
        elif brace == '}':
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s
        else:
            stack[-1][key.lower()] = s.replace('\\\\', '\\').replace('\\"', '"')
            key = None
    return root


def _read_vdf(path):
    try:
        return text_vdf(Path(path).read_text(errors='replace'))
    except OSError:
        return {}


def appinfo(path, want):
    """{appid: KeyValues} from Steam's binary appcache/appinfo.vdf (formats 28 and 29) for the apps in want."""
    data = Path(path).read_bytes()
    magic = struct.unpack_from('<I', data, 0)[0]
    if magic == 0x07564429:
        table = struct.unpack_from('<q', data, 8)[0]
        count = struct.unpack_from('<I', data, table)[0]
        strings, p = [], table + 4
        for _ in range(count):
            e = data.index(b'\0', p)
            strings.append(data[p:e].decode('utf-8', 'replace'))
            p = e + 1
        off, end = 16, table
    elif magic == 0x07564428:
        strings, off, end = None, 8, len(data)
    else:
        raise ValueError('unknown appinfo.vdf format %#x' % magic)

    def kv(p, depth=0):
        d = {}
        if depth > 32:
            raise ValueError('appinfo nesting')
        while True:
            t = data[p]
            p += 1
            if t == 8:
                return d, p
            if strings is not None:
                k = strings[struct.unpack_from('<I', data, p)[0]]
                p += 4
            else:
                e = data.index(b'\0', p)
                k = data[p:e].decode('utf-8', 'replace')
                p = e + 1
            if t == 0:
                v, p = kv(p, depth + 1)
            elif t == 1:
                e = data.index(b'\0', p)
                v = data[p:e].decode('utf-8', 'replace')
                p = e + 1
            elif t in (2, 3, 4, 6):
                v = struct.unpack_from('<f' if t == 3 else '<i', data, p)[0]
                p += 4
            elif t in (7, 10):
                v = struct.unpack_from('<Q' if t == 7 else '<q', data, p)[0]
                p += 8
            else:
                raise ValueError('appinfo value type %d' % t)
            d[k] = v

    out = {}
    while off + 8 <= end:
        appid, size = struct.unpack_from('<II', data, off)
        if appid == 0:
            break
        if appid in want:
            try:
                d, _ = kv(off + 8 + 4 + 4 + 8 + 20 + 4 + 20)
                out[appid] = d.get('appinfo', d)
            except (ValueError, IndexError, struct.error):
                pass
        off += 8 + size
    return out


def launch_entries(info):
    """Steam launch entries of an appinfo record: [dict(executable, arguments, type, description, oslist)]."""
    out = []
    items = (info.get('config', {}) or {}).get('launch') or {}
    for key, e in sorted(items.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        if isinstance(e, dict):
            cfg = e.get('config') or {}
            out.append(dict(executable=str(e.get('executable') or '').replace('\\', '/'), arguments=str(e.get('arguments') or ''),
                            type=str(e.get('type') or ''), description=str(e.get('description') or ''),
                            oslist=str(cfg.get('oslist') or '') if isinstance(cfg, dict) else ''))
    return out


def steam_roots(home):
    home = Path(home)
    return sorted({p.resolve() for p in (home/'.steam/steam', home/'.local/share/Steam',
                                         home/'.var/app/com.valvesoftware.Steam/.local/share/Steam') if p.is_dir()})


def steam_libraries(steam):
    libraries = {steam}
    folders = _read_vdf(steam/'steamapps/libraryfolders.vdf').get('libraryfolders', {})
    for entry in folders.values():
        if isinstance(entry, dict) and entry.get('path'):
            libraries.add(Path(entry['path']))
    return sorted(libraries)


def _steam_compat(steam):
    cfg = _read_vdf(steam/'config/config.vdf')
    try:
        return cfg['installconfigstore']['software']['valve']['steam'].get('compattoolmapping', {}) or {}
    except (KeyError, AttributeError, TypeError):
        return {}


def _steam_launch_options(steam):
    out = {}
    for lc in sorted((steam/'userdata').glob('*/config/localconfig.vdf')):
        try:
            apps = _read_vdf(lc)['userlocalconfigstore']['software']['valve']['steam'].get('apps', {})
        except (KeyError, AttributeError, TypeError):
            continue
        for appid, a in (apps or {}).items():
            if isinstance(a, dict) and a.get('launchoptions'):
                out.setdefault(str(appid), []).append(a['launchoptions'])
    return out


def _steam_game(steam, library, manifest, info, compat, options):
    st = _read_vdf(manifest).get('appstate', {})
    appid = str(st.get('appid', ''))
    common = (info.get(int(appid)) if appid.isdecimal() else None) or {}
    return dict(store='steam', id=appid, name=st.get('name', ''), path=str(library/'steamapps/common'/st.get('installdir', '')),
                library=str(library), steam_root=str(steam), type=str((common.get('common') or {}).get('type') or '').lower(),
                launch=launch_entries(common), stateflags=int(st.get('stateflags', 0) or 0),
                compat_tool=((compat.get(appid) or compat.get('0') or {}) if isinstance(compat, dict) else {}).get('name'),
                launch_options=options.get(appid, []))


def _heroic_roots(home):
    home = Path(home)
    return [p for p in (home/'.config/heroic', home/'.var/app/com.heroicgameslauncher.hgl/config/heroic') if p.is_dir()]


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def heroic_games(home):
    out = []
    for heroic in _heroic_roots(home):
        gog = _json(heroic/'gog_store/installed.json') or {}
        titles = {}
        for cache in ('store_cache/gog_library.json', 'store_cache/legendary_library.json'):
            lib = _json(heroic/cache) or {}
            for g in (lib.get('games') or lib.get('library') or []) if isinstance(lib, dict) else []:
                if isinstance(g, dict) and g.get('app_name'):
                    titles[str(g['app_name'])] = g.get('title')
        for x in gog.get('installed', []) if isinstance(gog, dict) else []:
            if not isinstance(x, dict) or x.get('is_dlc') or not x.get('install_path'):
                continue
            tasks = []
            for info in sorted(Path(x['install_path']).glob('goggame-*.info')):
                j = _json(info) or {}
                for t in j.get('playTasks', []) if isinstance(j, dict) else []:
                    if isinstance(t, dict) and t.get('type') == 'FileTask' and t.get('path'):
                        tasks.append(dict(executable=t['path'].replace('\\', '/'), arguments=str(t.get('arguments') or ''),
                                          description=str(t.get('name') or ''), oslist=''))
            out.append(dict(store='gog', id=str(x.get('appName')), name=titles.get(str(x.get('appName'))) or Path(x['install_path']).name,
                            path=x['install_path'], launch=tasks, platform=str(x.get('platform') or ''), heroic=str(heroic)))
        legendary = _json(heroic/'legendaryConfig/legendary/installed.json') or {}
        for key, x in legendary.items() if isinstance(legendary, dict) else []:
            if not isinstance(x, dict) or x.get('is_dlc') or not x.get('install_path'):
                continue
            out.append(dict(store='epic', id=str(key), name=x.get('title') or key, path=x['install_path'], platform=str(x.get('platform') or ''),
                            launch=[dict(executable=str(x.get('executable') or '').replace('\\', '/'), arguments=str(x.get('launch_parameters') or ''),
                                         description='Legendary executable', oslist='')], heroic=str(heroic)))
    for g in out:
        c = (_json(Path(g['heroic'])/'GamesConfig'/(g['id'] + '.json')) or {}).get(g['id'], {})
        c = c if isinstance(c, dict) else {}
        g['target_exe'] = c.get('targetExe') or None
        g['launch_options'] = [c['launcherArgs']] if c.get('launcherArgs') else []
        g['wine_prefix'] = c.get('winePrefix') or None
    return out


def installed_games(home=None):
    """Every installed Steam game (fully installed: StateFlags bit 4) and Heroic game, as game records for scan_folder."""
    home = Path(home or Path.home())
    games, seen = [], set()
    for steam in steam_roots(home):
        compat, options = _steam_compat(steam), _steam_launch_options(steam)
        manifests = [(library, m) for library in steam_libraries(steam) for m in sorted((library/'steamapps').glob('appmanifest_*.acf'))]
        ids = {int(m.name[12:-4]) for _, m in manifests if m.name[12:-4].isdecimal()}
        try:
            info = appinfo(steam/'appcache/appinfo.vdf', ids)
        except (OSError, ValueError, IndexError, struct.error):
            info = {}
        for library, m in manifests:
            g = _steam_game(steam, library, m, info, compat, options)
            if g['stateflags'] & 4 and g['type'] in ('game', 'demo', 'application', '') and (g['store'], g['id']) not in seen:
                seen.add((g['store'], g['id']))
                games.append(g)
    games += [g for g in heroic_games(home) if (g['store'], g['id']) not in seen]
    return games


def game_for_exe(exe, home=None):
    """The installed game record whose folder holds exe, else a bare folder record (no store)."""
    exe = Path(exe).resolve()
    home = Path(home or Path.home())
    for steam in steam_roots(home):
        for library in steam_libraries(steam):
            common = (library/'steamapps/common').resolve() if (library/'steamapps/common').is_dir() else None
            if not common or not exe.is_relative_to(common):
                continue
            folder = exe.relative_to(common).parts[0]
            for m in sorted((library/'steamapps').glob('appmanifest_*.acf')):
                st = _read_vdf(m).get('appstate', {})
                if str(st.get('installdir', '')).lower() == folder.lower():
                    appid = str(st.get('appid', ''))
                    try:
                        info = appinfo(steam/'appcache/appinfo.vdf', {int(appid)}) if appid.isdecimal() else {}
                    except (OSError, ValueError, IndexError, struct.error):
                        info = {}
                    g = _steam_game(steam, library, m, info, _steam_compat(steam), _steam_launch_options(steam))
                    g['path'] = str(common/folder)
                    return g
    for g in heroic_games(home):
        try:
            if exe.is_relative_to(Path(g['path']).resolve()):
                return g
        except OSError:
            continue
    return dict(store=None, id=None, name=None, path=str(game_root(exe)), launch=[], launch_options=[])


def game_root(exe):
    """A game's own folder above its executable when no launcher names it (install.py game_root)."""
    root = Path(exe).parent
    climbed = False
    while root.name.lower() in ('win64', 'x64', 'binaries', 'bin', 'bin64', 'x64_dx12', 'wingdk') and root.parent != root:
        climbed |= root.name.lower() == 'binaries'
        root = root.parent
    return root.parent if climbed and (root.parent/'Engine').is_dir() else root


# ------------------------------------------------------------------------------------------------- the game's files
# Folders other tools create beside a game's executable: their content is not the game's.
FOREIGN_DIRS = {'optiscaler', 'bc250-xefg', 'xessmfg', 'reshade-shaders', 'reshade-presets', 'renodx', 'luma',
                'd3d12_optiscaler', 'bc250-fsr4', 'specialk', 'lsfg', 'fsr4-optiscaler'}
FOREIGN_PREFIXES = ('.bc250-',)
STATE_PREFIX = '.bc250-xefg-experimental'
FOREIGN_FILES = {'optiscaler.ini', 'optiscaler.log', 'optiscaler.dll', 'optiscaler.asi', 'optipatcher.asi', 'reshade.ini',
                 'reshade.log', 'reshade64.dll', 'dxvk.conf', 'fakenvapi.ini', 'fakenvapi.log', 'dlssg_to_fsr3_amd_is_better.dll',
                 'dlssg_to_fsr3.log', 'xessmfg-ui-layout.ini', 'bc250_xefg_original.dll', 'specialk64.dll', 'specialk64.ini',
                 'nvngx.ini'} | {name.lower() for name in ('BC250-MFG.log', 'BC250-XeFG-fast.log')}  # the proxy's logs
MOD_PRODUCTS = [('optiscaler', 'OptiScaler'), ('xessmfg', 'XeSSMFG enabler'), ('reshade', 'ReShade'),
                ('ultimate asi loader', 'Ultimate ASI Loader'), ('special k', 'Special K'), ('dxvk', 'DXVK'),
                ('fakenvapi', 'fakenvapi'), ('dlssg-to-fsr3', 'dlssg-to-fsr3'), ('dlssg_to_fsr3', 'dlssg-to-fsr3'),
                ('luma', 'Luma'), ('bc250', 'BC250 add-on')]
PROXY_NAMES = {'dxgi.dll', 'd3d12.dll', 'd3d11.dll', 'winmm.dll', 'version.dll', 'wininet.dll', 'winhttp.dll', 'dinput8.dll',
               'dbghelp.dll', 'd3d9.dll', 'xinput1_3.dll', 'xinput1_4.dll'}


def known_hashes():
    """SHA-256 of the upstream files the installer places (the package's dependencies.json pins)."""
    data = _json(HERE/'dependencies.json') or {}
    return {v['sha256']: 'pinned ' + k for k, v in (data.get('inputs') or {}).items() if isinstance(v, dict) and v.get('sha256')}


def _sha256(path, limit=200 << 20):
    try:
        if os.path.getsize(path) > limit:
            return None
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class Tree:
    """The game's files (relative POSIX paths, sizes) without the folders other tools create, plus the installation
    records found there (state.json of this installer and its archived copies)."""

    def __init__(self, root, limit=WALK_LIMIT):
        self.root = Path(root)
        self.files, self.lower, self.by_name, self.dirs, self.symlinks = {}, {}, {}, set(), {}
        self.foreign_dirs, self.states, self.truncated = [], [], False
        rootreal = os.path.realpath(self.root)
        n = 0
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            reld = os.path.relpath(dirpath, self.root)
            reld = '' if reld == '.' else reld.replace(os.sep, '/')
            prefix = reld + '/' if reld else ''
            keep = []
            for d in sorted(dirnames):
                low, full = d.lower(), os.path.join(dirpath, d)
                if low.startswith(STATE_PREFIX):
                    state = _json(Path(full, 'state.json'))
                    if isinstance(state, dict):
                        self.states.append((prefix + d, state))
                if low in FOREIGN_DIRS or low.startswith(FOREIGN_PREFIXES):
                    self.foreign_dirs.append(prefix + d)
                    continue
                if os.path.islink(full) and not os.path.realpath(full).startswith(rootreal + os.sep):
                    self.symlinks[prefix + d] = os.path.realpath(full)
                    continue
                keep.append(d)
                self.dirs.add((prefix + d).lower())
            dirnames[:] = keep
            for fn in filenames:
                rel, full = prefix + fn, os.path.join(dirpath, fn)
                if os.path.islink(full) and not os.path.realpath(full).startswith(rootreal + os.sep):
                    self.symlinks[rel] = os.path.realpath(full)
                try:
                    self.files[rel] = os.lstat(full).st_size
                except OSError:
                    continue
                self.lower[rel.lower()] = rel
                self.by_name.setdefault(fn.lower(), []).append(rel)
                n += 1
            if n > limit:
                self.truncated = True
                break
        # Paths an installation created (before = null) or replaced, relative to the game root.
        self.created, self.replaced = {}, {}
        for sdir, st in self.states:
            base = sdir.rsplit('/', 1)[0] if '/' in sdir else ''
            for f in st.get('files') or []:
                p = ((base + '/') if base else '') + str(f.get('path', ''))
                if f.get('before') is None:
                    self.created[p.lower()] = st.get('package') or 'an earlier installation'
                else:
                    self.replaced.setdefault(p.lower(), sdir)

    def exists(self, rel):
        return rel.lower() in self.lower

    def find(self, name):
        return self.by_name.get(name.lower(), [])

    def full(self, rel):
        return self.root / rel


def _is_elf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except OSError:
        return False


def foreign(tree, rel, info=None):
    """Why rel is not the game's own file (another tool's, or this installer's), or None."""
    low = rel.lower()
    if low in tree.created:
        return 'created by ' + tree.created[low]
    if rel in tree.symlinks:
        return 'symlink out of the game folder'
    if low.rsplit('/', 1)[-1] in FOREIGN_FILES:
        return 'a mod\'s file name'
    if info:
        s = info.get('version', {}).get('strings', {})
        text = ' '.join(s.get(k, '') for k in ('ProductName', 'FileDescription', 'InternalName')).lower()
        for needle, label in MOD_PRODUCTS:
            if needle in text:
                return label
    return None


def _info(tree, rel, cache):
    if rel not in cache:
        try:
            cache[rel] = pe_parse(tree.full(rel))
        except (OSError, PEError, struct.error, ValueError, IndexError):
            cache[rel] = None
    return cache[rel]


# --------------------------------------------------------------------------------------------------------- executables
HELPER_EXE = re.compile(r'(crash|report|unitycrashhandler|bugsplat|sentry|redist|vc_?redist|dxsetup|directx|prereq|'
                        r'setup|install|unins|easyanticheat|start_protected_game|beservice|battleye|_be\.exe$|'
                        r'launcher|uplay|upc\.exe|epicwebhelper|cefsharp|subprocess|helper|quicksfv|7z|editor|'
                        r'uploader|modmanager|mod manager|aceed|leadpipe|server\.exe|dedicated|benchmark|'
                        r'workshop|config|settings|updater|patcher|notification|cohtml|renderdoc|sdk|tool|bssndrpt|'
                        r'prelauncher|playrdr|idtechlauncher)', re.I)
HELPER_PRODUCT = re.compile(r'(crash|bugsplat|report|setup|install|redistributable|launcher|anti-?cheat|updater|7-zip)', re.I)
HELPER_DIRS = re.compile(r'(^|/)(_commonredist|redist|redistributables|directx|vcredist|dotnet|prereqs?|installers?|'
                         r'__installer|support|easyanticheat|battleye|engine/extras|engine/binaries/thirdparty|tools|tools_[^/]*|'
                         r'artbook[^/]*|soundtrack[^/]*|legacy|developerbuild|development|profile)(/|$)', re.I)
GFX_DLLS = {'d3d12.dll': 'd3d12', 'dxgi.dll': 'dxgi', 'd3d11.dll': 'd3d11', 'vulkan-1.dll': 'vulkan', 'd3d9.dll': 'd3d9',
            'opengl32.dll': 'opengl', 'sl.interposer.dll': 'streamline', 'd3d10.dll': 'd3d10', 'd3d10_1.dll': 'd3d10',
            'd3d8.dll': 'd3d8', 'ddraw.dll': 'ddraw'}
ENGINE_DLLS = ('unityplayer.dll',)


def gfx_imports(info):
    """The graphics APIs a PE imports (d3d9 used only for D3DPERF_* PIX markers is not a renderer)."""
    imports = (info or {}).get('imports', {})
    names = set(imports) | set((info or {}).get('delay_imports', []))
    out = {GFX_DLLS[n] for n in names if n in GFX_DLLS}
    d9 = imports.get('d3d9.dll')
    if d9 is not None and 'd3d9.dll' not in (info or {}).get('delay_imports', []) and d9 and all(f.startswith('D3DPERF_') for f in d9):
        out.discard('d3d9')
    sl = imports.get('sl.interposer.dll', [])
    if any('D3D12' in f for f in sl):
        out.add('d3d12')
    if any('D3D11' in f for f in sl):
        out.add('d3d11')
    return out


def ue_stub_target(tree, rel):
    """For an Unreal bootstrap stub (<Root>/<Game>.exe), the <Project>/Binaries/Win64/*.exe it starts, or None."""
    folder = rel.rsplit('/', 1)[0] if '/' in rel else ''
    ships = [r for r in tree.files if r.lower().endswith('.exe') and re.search(r'/binaries/(win64|wingdk)/[^/]+$', r.lower())
             and not r.lower().startswith('engine/') and not HELPER_EXE.search(r.rsplit('/', 1)[-1])
             and (r.lower().startswith(folder.lower() + '/') if folder else True) and r != rel]
    if not ships:
        return None
    stem = rel.rsplit('/', 1)[-1][:-4].lower()
    ships.sort(key=lambda r: (0 if r.lower().endswith('-shipping.exe') else 1,
                              0 if r.rsplit('/', 1)[-1].lower().startswith(stem) else 1, r.count('/'), r))
    return ships[0]


def _store_exes(tree, game):
    out, notes = [], []
    for e in game.get('launch') or []:
        ex = (e.get('executable') or '').lstrip('/')
        oslist = e.get('oslist') or ''
        if ex and (not oslist or 'windows' in oslist) and ex.lower() in tree.lower:
            out.append(ex.lower())
    target = game.get('target_exe')
    if target:
        t = os.path.relpath(target, tree.root) if os.path.isabs(target) else target
        if t.lower() in tree.lower:
            out.insert(0, t.lower())
            notes.append('Heroic chooses ' + tree.lower[t.lower()])
    return list(dict.fromkeys(out)), notes


def score_exe(tree, rel, info, store_exes, cache):
    """(score, reasons, graphics APIs) of one candidate executable."""
    s, why = 0, []
    name = rel.rsplit('/', 1)[-1]
    g = set(gfx_imports(info))
    folder = rel.rsplit('/', 1)[0] + '/' if '/' in rel else ''
    for d in ENGINE_DLLS:
        if tree.exists(folder + d):
            g |= gfx_imports(_info(tree, tree.lower[(folder + d).lower()], cache))
            s += 30
            why.append('engine ' + d)
    if 'd3d12' in g:
        s += 40
    if g & {'dxgi', 'd3d11', 'vulkan', 'streamline'}:
        s += 25
    if g & {'d3d9', 'opengl'}:
        s += 5
    if g:
        why.append('graphics ' + ','.join(sorted(g)))
    s += 10 if info['bits'] == 64 else -30
    if info.get('dotnet'):
        s -= 5
    if name.lower().endswith('-shipping.exe'):
        s += 20
        why.append('Unreal shipping build')
    if rel.lower() in store_exes:
        s += 60
        why.append('the launcher starts it')
    if HELPER_EXE.search(name) or HELPER_PRODUCT.search(info.get('version', {}).get('strings', {}).get('ProductName', '') or ''):
        s -= 120
        why.append('helper or launcher name')
    if HELPER_DIRS.search(rel):
        s -= 60
        why.append('helper folder')
    s += min(20, info['size'] // (8 << 20))
    return s, why, sorted(g)


def rank_exes(tree, game, cache):
    """(ranked candidates [dict(rel, score, why, gfx, bits)], stub map {stub rel: target rel}, notes)."""
    store, notes = _store_exes(tree, game)
    stubs = {}
    for rel in [tree.lower[s] for s in store] + [r for r in tree.files if r.lower().endswith('.exe') and '/' not in r]:
        if not rel.lower().endswith('-shipping.exe') and tree.files.get(rel, 0) < 8 << 20:
            target = ue_stub_target(tree, rel)
            if target:
                stubs[rel] = target
    resolved = {t.lower() for s, t in stubs.items() if s.lower() in store}
    for s in [s for s in stubs if s.lower() in store]:
        notes.append('Unreal bootstrap ' + s + ' starts ' + stubs[s])
    ranked = []
    for rel, size in tree.files.items():
        if not rel.lower().endswith('.exe') or size < 4096 or foreign(tree, rel):
            continue
        info = _info(tree, rel, cache)
        if not info or info['kind'] != 'exe':
            continue
        sc, why, g = score_exe(tree, rel, info, set(store) | resolved, cache)
        if rel.lower() in resolved:
            sc += 30
        if store and rel.lower() == store[0]:
            sc += 10  # the launcher's default entry wins a tie (a demo shipped in a subfolder)
        ranked.append(dict(rel=rel, score=sc, why=why, gfx=g, bits=info['bits']))
    ranked.sort(key=lambda c: (-c['score'], c['rel'].count('/'), c['rel'].lower()))
    return ranked, stubs, notes


def exe_confidence(ranked):
    """high: the top candidate leads clearly; medium: it leads; low: nearly a tie or a poor top candidate."""
    if not ranked:
        return 'low'
    lead = ranked[0]['score'] - (ranked[1]['score'] if len(ranked) > 1 else -100)
    return 'high' if ranked[0]['score'] >= 60 and lead >= 40 else 'medium' if lead >= 15 and ranked[0]['score'] >= 30 else 'low'


# -------------------------------------------------------------------------------------------------------------- engine
def detect_engine(tree, exe_rel, exe_info, cache):
    names = tree.by_name
    low = set(tree.lower)
    exe_name = exe_rel.rsplit('/', 1)[-1].lower() if exe_rel else ''
    vs = (exe_info or {}).get('version', {})
    product = vs.get('strings', {}).get('ProductName', '')
    unreal_layout = any(d.endswith('/binaries/win64') or d == 'binaries/win64' for d in tree.dirs) and \
        any(d == 'engine' or d.startswith('engine/') for d in tree.dirs)
    if exe_name.endswith('-shipping.exe') or unreal_layout or product in ('UE4', 'UE5'):
        ver = None
        if product in ('UE4', 'UE5'):
            ver = product + ' ' + vs.get('file_version', '')
        if not ver and exe_rel:
            hit = pe_strings(tree.full(exe_rel), ['++UE5+Release-', '++UE4+Release-', 'r.Nanite.', 'r.Lumen.'])
            ver = 'UE5' if '++UE5+Release-' in hit or 'r.Nanite.' in hit or 'r.Lumen.' in hit else 'UE4' if '++UE4+Release-' in hit else None
        if ver or exe_name.endswith('-shipping.exe'):
            major = (ver or 'UE').split()[0]
            return dict(name='unreal', version=ver or 'unknown', major=major if major in ('UE4', 'UE5') else 'UE',
                        confidence='high' if ver else 'medium')
    folder = exe_rel.rsplit('/', 1)[0] + '/' if exe_rel and '/' in exe_rel else ''
    if (folder + 'unityplayer.dll').lower() in low or any(d.endswith('_data') and (d + '/globalgamemanagers') in low for d in tree.dirs):
        up = tree.lower.get((folder + 'unityplayer.dll').lower())
        ver = ((_info(tree, up, cache) or {}).get('version', {}) or {}).get('file_version') if up else None
        return dict(name='unity', version=ver or 'unknown', backend='il2cpp' if (folder + 'gameassembly.dll').lower() in low else 'mono',
                    confidence='high')
    if exe_rel and pe_strings(tree.full(exe_rel), ['Godot Engine']):
        return dict(name='godot', version=pe_context(tree.full(exe_rel), 'Godot Engine v') or 'unknown', confidence='medium')
    markers = [
        ('cryengine', lambda: 'crysystem.dll' in names or any(n.startswith('cryrender') for n in names)),
        ('redengine', lambda: any(r.startswith('archive/pc/content/') for r in low)),
        ('rage', lambda: any(r.endswith('.rpf') for r in low)),
        ('anvil', lambda: any(r.endswith('.forge') for r in low)),
        ('northlight', lambda: any(r.endswith(('.rmdp', '.rmdtoc', '.rmdblob')) for r in low)),
        ('blackspace', lambda: any(r.endswith(('.paz', '.pamt')) for r in low)),
        ('idtech', lambda: any(r.endswith('.resources') for r in low) and any(r.startswith('base/') for r in low)),
        ('re-engine', lambda: any(r.startswith('re_chunk_000') for r in low)),
        ('frostbite', lambda: any(r.endswith('.cas') for r in low) and any(r.endswith('.toc') for r in low)),
        ('source2', lambda: 'engine2.dll' in names),
        ('gamemaker', lambda: 'data.win' in names),
        ('fna/xna/monogame', lambda: bool({'fna.dll', 'monogame.framework.dll', 'microsoft.xna.framework.dll'} & set(names))),
        ('renpy', lambda: 'renpy' in tree.dirs),
        ('creation', lambda: any(r.endswith(('.ba2', '.bsa')) for r in low)),
        ('decima', lambda: any(d.startswith('localcachewingame') for d in tree.dirs)),
        ('snowdrop', lambda: any(r.endswith('.sdftoc') for r in low)),
        ('glacier', lambda: any(r.endswith('.rpkg') for r in low)),
    ]
    for name, test in markers:
        if test():
            return dict(name=name, version='unknown', confidence='medium')
    return dict(name='unknown', version='unknown', confidence='low')


# ------------------------------------------------------------------------------------------------ upscaler / FG inputs
INPUT_FILES = [  # (input, lower-case file name, meaning)
    ('dlss', 'nvngx_dlss.dll', 'DLSS Super Resolution'), ('dlssd', 'nvngx_dlssd.dll', 'DLSS Ray Reconstruction'),
    ('dlssg', 'nvngx_dlssg.dll', 'DLSS Frame Generation'), ('dlssg', 'sl.dlss_g.dll', 'DLSS Frame Generation (Streamline)'),
    ('dlss', 'sl.dlss.dll', 'DLSS (Streamline)'), ('streamline', 'sl.interposer.dll', 'Streamline'),
    ('reflex', 'sl.reflex.dll', 'Reflex (Streamline)'),
    ('fsr31', 'amd_fidelityfx_dx12.dll', 'FSR 3.1.0-3.1.3 (upscaler and frame generation in one DLL)'),
    ('fsr31', 'amd_fidelityfx_upscaler_dx12.dll', 'FSR 3.1.4+ upscaler'), ('fsr31', 'amd_fidelityfx_loader_dx12.dll', 'FidelityFX SDK 2 loader'),
    ('fsrfg', 'amd_fidelityfx_framegeneration_dx12.dll', 'FSR 3.1.4+ frame generation'), ('fsr31vk', 'amd_fidelityfx_vk.dll', 'FSR 3.1 Vulkan'),
    ('fsr3', 'ffx_fsr3_x64.dll', 'FSR 3.0'), ('fsr3', 'ffx_fsr3upscaler_x64.dll', 'FSR 3.0 upscaler'),
    ('fsrfg30', 'ffx_frameinterpolation_x64.dll', 'FSR 3.0 frame interpolation'), ('fsrfg30', 'ffx_opticalflow_x64.dll', 'FSR 3.0 optical flow'),
    ('fsr2', 'ffx_fsr2_api_x64.dll', 'FSR 2'), ('fsr2', 'ffx_fsr2_api_dx12_x64.dll', 'FSR 2 DX12 backend'),
    ('fsr2dx11', 'ffx_fsr2_api_dx11_x64.dll', 'FSR 2 DX11 backend'), ('fsr2vk', 'ffx_fsr2_api_vk_x64.dll', 'FSR 2 Vulkan backend'),
    ('xess', 'libxess.dll', 'XeSS Super Resolution'), ('xessdx11', 'libxess_dx11.dll', 'XeSS DX11'),
    ('xefg', 'libxess_fg.dll', 'XeSS Frame Generation'), ('xell', 'libxell.dll', 'XeLL'),
    ('agility', 'd3d12core.dll', 'D3D12 Agility SDK'),
]
INPUT_STRINGS = [  # (input, needle in the executable or an engine DLL, meaning)
    ('dlss', 'NVSDK_NGX_D3D12_Init', 'NGX D3D12'), ('dlss', 'r.NGX.DLSS.Enable', 'Unreal DLSS plugin'),
    ('dlssg', 'r.Streamline.DLSSG.Enable', 'Unreal Streamline DLSS-G'), ('dlssg', 'sl.dlss_g.dll', 'Streamline DLSS-G'),
    ('streamline', 'sl.interposer.dll', 'Streamline'), ('reflex', 'r.Streamline.Reflex', 'Unreal Reflex'),
    ('fsr31', 'amd_fidelityfx_dx12.dll', 'loads the FSR 3.1 DLL'), ('fsr31', 'amd_fidelityfx_upscaler_dx12.dll', 'loads the FSR upscaler DLL'),
    ('fsr31', 'ffxCreateContext', 'FidelityFX API'), ('fsrfg', 'r.FidelityFX.FI.Enabled', 'Unreal FSR 3 frame interpolation'),
    ('fsr3', 'r.FidelityFX.FSR3.Enabled', 'Unreal FSR 3 plugin'), ('fsr2', 'r.FidelityFX.FSR2.Enabled', 'Unreal FSR 2 plugin'),
    ('fsr2', 'ffxFsr2ContextCreate', 'FSR 2 API (static or DLL)'), ('fsr3', 'ffxFsr3UpscalerContextCreate', 'FSR 3.0 upscaler API'),
    ('xess', 'xessD3D12CreateContext', 'XeSS D3D12 API'), ('xess', 'r.XeSS.Enabled', 'Unreal XeSS plugin'),
    ('xefg', 'xefgSwapChainD3D12', 'XeSS FG API'), ('xefg', 'r.XeFG.Enabled', 'Unreal XeSS FG'),
    ('agility', 'D3D12SDKVersion', 'Agility SDK export'),
]
# Inputs OptiScaler hooks for OptiFG under DirectX 12 (static FSR 2/3 in Unreal executables through its pattern inputs).
HOOKABLE = ('dlss', 'fsr2', 'fsr3', 'fsr31', 'xess')


def detect_inputs(tree, exe_rel, cache, code_files, known=None):
    """{input: dict(files=[...], code=[...], foreign=[...], meaning)}: what the game ships (a file of its own, also one
    an installation replaced: the original was the game's) or calls (a code reference); copies other tools placed are
    listed under foreign and do not count."""
    known = known if known is not None else known_hashes()
    out = {}
    exe_dir = exe_rel.rsplit('/', 1)[0].lower() + '/' if exe_rel and '/' in exe_rel else ''
    for key, fname, meaning in INPUT_FILES:
        for rel in tree.find(fname):
            info = _info(tree, rel, cache)
            why = foreign(tree, rel, info)
            beside = rel.lower().startswith(exe_dir) and '/' not in rel.lower()[len(exe_dir):]
            if not why and beside and _sha256(tree.full(rel)) in known and (
                    any(tree.exists(exe_dir + n) for n in ('optiscaler.ini', 'optiscaler.log'))):
                why = 'a pinned upstream copy with OptiScaler beside it'
            slot = out.setdefault(key, dict(files=[], code=[], foreign=[], meaning=meaning))
            entry = dict(path=rel, version=((info or {}).get('version') or {}).get('file_version'), beside_exe=beside)
            if why and rel.lower() not in tree.replaced:
                slot['foreign'].append(dict(entry, reason=why))
            else:
                slot['files'].append(entry)
    needles = [n for _, n, _ in INPUT_STRINGS]
    for cf in code_files:
        try:
            hits = pe_strings(tree.full(cf), needles)
        except (OSError, ValueError):
            continue
        for key, needle, meaning in INPUT_STRINGS:
            if needle in hits:
                out.setdefault(key, dict(files=[], code=[], foreign=[], meaning=meaning))['code'].append(cf.rsplit('/', 1)[-1] + ': ' + meaning)
        info = _info(tree, cf, cache) or {}
        imports = set(info.get('imports', {})) | set(info.get('delay_imports', []))
        if 'D3D12SDKVersion' in (info.get('exports') or []):
            out.setdefault('agility', dict(files=[], code=[], foreign=[], meaning='D3D12 Agility SDK'))['code'].append(
                cf.rsplit('/', 1)[-1] + ' exports D3D12SDKVersion')
        for key, fname, meaning in INPUT_FILES:
            if fname in imports:
                out.setdefault(key, dict(files=[], code=[], foreign=[], meaning=meaning))['code'].append(cf.rsplit('/', 1)[-1] + ' imports ' + fname)
    return out


# Unity's NVIDIA module (com.unity.modules.nvidia) puts nvngx_dlss.dll and NVUnityPlugin.dll beside every player that
# includes it, whether or not the game ever turns DLSS on (games on URP or a renderer of their own, with no DLSS in
# the game's code). The game's code must name DLSS: HDRP's DLSS pass or a script that drives the module.
UNITY_DLSS_CODE = ('DLSSContext', 'DLSSPass', 'ActivateDLSS')
UNITY_ENGINE_ASSEMBLIES = ('unityengine.', 'system.', 'mscorlib', 'mono.', 'netstandard', 'microsoft.')


def unity_dlss_use(tree, inputs, engine):
    """For a Unity game whose only DLSS evidence is the copy Unity's NVIDIA module bundles: dict(used, where) after
    reading the game's own code (Managed/*.dll other than Unity's and .NET's own assemblies, or IL2CPP's
    global-metadata.dat), or None when the rule does not apply (another engine, DLSS named in code already, no
    NVUnityPlugin.dll, or no game code readable here: then the bundled DLL still counts)."""
    dlss = inputs.get('dlss') or {}
    if (engine or {}).get('name') != 'unity' or not dlss.get('files') or dlss.get('code') or not tree.find('nvunityplugin.dll'):
        return None
    code = []
    for rel in sorted(tree.files):
        low = rel.lower()
        name = low.rsplit('/', 1)[-1]
        if low.endswith('/il2cpp_data/metadata/global-metadata.dat') or (
                '_data/managed/' in low and name.endswith('.dll') and not name.startswith(UNITY_ENGINE_ASSEMBLIES)):
            code.append(rel)
    if not code:
        return None
    for rel in code:
        try:
            hits = pe_strings(tree.full(rel), UNITY_DLSS_CODE)
        except (OSError, ValueError):
            continue
        if hits:
            return dict(used=True, where=rel.rsplit('/', 1)[-1] + ': ' + ', '.join(sorted(hits)))
    return dict(used=False, where=f'{len(code)} code file{"s" if len(code) != 1 else ""} read')


def present(inputs, key):
    s = inputs.get(key)
    return bool(s and (s['files'] or s['code']))


def own_files(inputs, key, beside=None):
    return [f for f in (inputs.get(key) or {}).get('files', []) if beside is None or f['beside_exe'] == beside]


# ---------------------------------------------------------------------------------------------------------- anti-cheat
ANTICHEAT = [
    ('Easy Anti-Cheat', re.compile(r'(^|/)(easyanticheat[^/]*|start_protected_game\.exe|eac_launcher\.exe)$', re.I)),
    ('BattlEye', re.compile(r'(^|/)(battleye|beservice[^/]*|beclient[^/]*|[^/]*_be\.exe)$', re.I)),
    ('nProtect GameGuard', re.compile(r'(^|/)(gameguard[^/]*|npgg[^/]*)$', re.I)),
    ('XIGNCODE3', re.compile(r'(^|/)(xigncode[^/]*|x3\.xem)$', re.I)),
    ('EA Javelin', re.compile(r'(^|/)eaanticheat[^/]*$', re.I)),
    ('Anti-Cheat Expert (ACE)', re.compile(r'(^|/)(ace-[^/]*\.dll|anticheatexpert[^/]*)$', re.I)),
    ('mhyprot', re.compile(r'(^|/)mhyprot[^/]*$', re.I)),
    ('EQU8', re.compile(r'(^|/)equ8[^/]*$', re.I)),
    ('PunkBuster', re.compile(r'(^|/)(pbsvc[^/]*|pb/pbcl[^/]*)$', re.I)),
    ('Denuvo Anti-Cheat', re.compile(r'(^|/)denuvo[^/]*anti[^/]*$', re.I)),
    ('Vanguard', re.compile(r'(^|/)vgc[^/]*\.exe$', re.I)),
]


def detect_anticheat(tree):
    found = {}
    for rel in list(tree.files) + sorted(tree.dirs):
        for name, rx in ANTICHEAT:
            if rx.search(rel):
                found.setdefault(name, []).append(rel)
    return [dict(name=name, evidence=sorted(rels)[:4], proton_runtime=any(r.lower().endswith('.so') for r in rels))
            for name, rels in sorted(found.items())]


# ------------------------------------------------------------------------------------------- what the game ran last time
RHI = [('d3d12', re.compile(rb'LogD3D12RHI|D3D12RHI|Using Default RHI: D3D12|RHI D3D12|Direct3D 12', re.I)),
       ('d3d11', re.compile(rb'LogD3D11RHI|D3D11RHI|Using Default RHI: D3D11|Direct3D 11\.', re.I)),
       ('vulkan', re.compile(rb'LogVulkanRHI|Vulkan API version|Vulkan RHI|Vulkan 1\.\d', re.I))]


def prefix_user(game):
    """drive_c/users/steamuser of the game's Proton or Wine prefix, or None."""
    if game.get('store') == 'steam' and game.get('library') and game.get('id'):
        p = Path(game['library'])/'steamapps/compatdata'/str(game['id'])/'pfx/drive_c/users/steamuser'
        return p if p.is_dir() else None
    prefix = game.get('wine_prefix')
    if prefix:
        for p in (Path(prefix)/'drive_c/users/steamuser', Path(prefix)/'pfx/drive_c/users/steamuser'):
            if p.is_dir():
                return p
    return None


def runtime_log(game, tree, engine, exe_rel):
    """The graphics API the game used last time, from its own log or config in the prefix (Unreal Saved/Logs and
    GameUserSettings PreferredRHI, Unity Player.log): dict(api, source) or None. Evidence of what ran, not of what the
    files allow."""
    user = prefix_user(game)
    if not user:
        return None
    logs, configs = [], []
    if engine.get('name') == 'unreal' and exe_rel:
        names = [m.group(1) for m in [re.search(r'([^/]+)/binaries/(win64|wingdk)/', exe_rel, re.I)] if m]
        for base in (user/'AppData/Local', user/'Documents', user/'Documents/My Games'):
            for d in (sorted(base.iterdir()) if base.is_dir() else []):
                if (d/'Saved').is_dir() and (d.name.lower() in [n.lower() for n in names] or
                                             (game.get('name') and re.sub(r'\W', '', d.name.lower()) in re.sub(r'\W', '', game['name'].lower()))):
                    logs += sorted((d/'Saved/Logs').glob('*.log'), key=lambda p: -p.stat().st_mtime)[:1]
                    configs += sorted((d/'Saved').glob('Config/Windows*/GameUserSettings.ini'))
    if engine.get('name') == 'unity':
        for d in sorted(tree.dirs):
            app = tree.lower.get(d + '/app.info')
            if app:
                try:
                    company, product = tree.full(app).read_text(errors='replace').splitlines()[:2]
                except (OSError, ValueError):
                    continue
                p = user/'AppData/LocalLow'/company/product/'Player.log'
                if p.is_file():
                    logs.append(p)
    for cfg in configs:
        try:
            m = re.search(r'^\s*PreferredRHI\s*=\s*(\w+)', cfg.read_text(errors='replace'), re.M | re.I)
        except OSError:
            continue
        api = {'dx12': 'd3d12', 'dx11': 'd3d11', 'vulkan': 'vulkan'}.get(m.group(1).lower()) if m else None
        if api:
            return dict(api=api, source='the game\'s GameUserSettings.ini (PreferredRHI)')
    for log in logs:
        try:
            with open(log, 'rb') as f:
                data = f.read(4 << 20)
        except OSError:
            continue
        for api, rx in RHI:
            if rx.search(data):
                return dict(api=api, source='the game\'s own log')
    return None


# ------------------------------------------------------------------------------------------------------- graphics API
THIRD_PARTY = ('nvngx', 'sl.', 'amd_fidelityfx', 'libxess', 'libxell', 'igxess', 'ffx_', 'd3d12core', 'd3d12sdklayers',
               'dxcompiler', 'dxil', 'gfsdk', 'nvapi', 'physx', 'openimagedenoise', 'nri', 'nrd', 'eossdk', 'vcamp',
               'steam_api', 'discord', 'galaxy', 'bink', 'fmod', 'wwise', 'aksound', 'amd_ags', 'cohtml', 'coherent', 'renoir',
               'mediadecoders', 'embree', 'tbb', 'sentry', 'crashpad', 'd3dcompiler', 'glew', 'anselsdk', 'nvcloth',
               'pxfoundation', 'apex', 'bugsplat', 'xaudio', 'xinput', 'msvcp', 'vcruntime', 'ucrtbase', 'concrt', 'api-ms-',
               'libcurl', 'libssl', 'libcrypto', 'zlib', 'sdl2', 'sdl3', 'openal', 'oo2core', 'oo2net', 'granny', 'havok',
               'mono', 'dbghelp', 'nakama', 'epic', 'gameoverlay', 'reflex', 'nvlowlatency', 'streamline', 'dlss', 'xess',
               'fsr', 'ffx', 'amdxc', 'atiadl', 'atidxx', 'icu', 'cef', 'libcef', 'chrome', 'ffmpeg', 'avcodec', 'avformat',
               'avutil', 'swscale', 'swresample', 'opencv', 'onnx', 'directml', 'torch', 'vivox', 'eos', 'party', 'playfab',
               'easyanticheat', 'beclient')
API_SWITCH = re.compile(r'(?<![\w-])(-dx12|-d3d12|-force-d3d12|-dx11|-d3d11|-force-d3d11|-vulkan|-force-vulkan|'
                        r'--rendering-driver\s+\S+|-force-glcore|-opengl)(?![\w-])', re.I)
DX12_SWITCHES = ('-dx12', '-d3d12', '-force-d3d12')


def detect_api(tree, game, exe_rel, exe_info, engine, cache, log):
    """dict(apis, dx12, default, switch, switch_kind, confidence, evidence, current_switch, code_files): the APIs the
    executable and its engine DLLs can render with, the one the game starts with, and the launch switch that selects
    DirectX 12 when that is not the default."""
    ev, apis = [], set(gfx_imports(exe_info))
    if apis:
        ev.append('the executable imports ' + ', '.join(sorted(apis)))
    folder = exe_rel.rsplit('/', 1)[0] + '/' if '/' in exe_rel else ''
    code_files = [exe_rel]
    for rel in sorted(tree.files):
        low = rel.lower()
        if not low.startswith(folder.lower()) or '/' in low[len(folder):] or not low.endswith('.dll'):
            continue
        name = low[len(folder):]
        if name in PROXY_NAMES or name.startswith(THIRD_PARTY):
            continue
        info = _info(tree, rel, cache)
        if info and foreign(tree, rel, info) is None and gfx_imports(info):
            ev.append(name + ' imports ' + ', '.join(sorted(gfx_imports(info))))
            apis |= gfx_imports(info)
            code_files.append(rel)
    hits = {}
    for i, code in enumerate(code_files):
        try:
            hits.update(pe_strings(tree.full(code), ['d3d12.dll', 'D3D12CreateDevice', 'vulkan-1.dll', 'vkCreateInstance', 'D3D12SDKVersion']
                                   if i == 0 else ['d3d12.dll', 'D3D12CreateDevice', 'vulkan-1.dll', 'vkCreateInstance']))
        except (OSError, ValueError):
            pass
    if 'd3d12.dll' in hits or 'D3D12CreateDevice' in hits:
        apis.add('d3d12?')
        ev.append('its code names D3D12')
    if 'vulkan-1.dll' in hits or 'vkCreateInstance' in hits:
        apis.add('vulkan?')
        ev.append('its code names Vulkan')
    if 'D3D12SDKVersion' in hits or 'D3D12SDKVersion' in ((exe_info or {}).get('exports') or []) or tree.find('d3d12core.dll'):
        apis.add('d3d12')
        ev.append('D3D12 Agility SDK')
    eng = engine.get('name')
    dx12 = 'd3d12' in apis or ('d3d12?' in apis and eng in ('unreal', 'unity', 'godot'))
    store_args = []
    launch = game.get('launch') or []
    for e in launch:
        for m in API_SWITCH.finditer(e.get('arguments') or ''):
            store_args.append(dict(arg=m.group(1), default=e is launch[0], description=e.get('description', '')))
    if store_args:
        ev.append('launch entries: ' + '; '.join(s['arg'] + (' (default)' if s['default'] else '') for s in store_args))
    current = ' '.join(game.get('launch_options') or [])
    current_switch = [m.group(1) for m in API_SWITCH.finditer(current)]
    dx12_store = [s for s in store_args if s['arg'].lower() in DX12_SWITCHES]
    dx11_store = [s for s in store_args if s['arg'].lower() in ('-dx11', '-d3d11', '-force-d3d11')]
    vk_ambiguous = ('vulkan' in apis or 'vulkan?' in apis) and eng not in ('unreal', 'unity')
    default, switch, kind, conf = None, None, None, 'low'
    if log and log.get('api') and not current_switch:
        default, conf = log['api'], 'high'
        ev.append(log['source'] + ': the game started with ' + log['api'])
    if default is None and any(s['default'] for s in dx12_store):
        default, conf = 'd3d12', 'high'
        ev.append('the default launch entry passes ' + dx12_store[0]['arg'])
    if default is None and dx11_store and dx12 and not dx12_store:
        default, conf = 'd3d12', 'high'
        ev.append('the launcher offers DX11 as the alternative: DX12 is the default')
    if eng == 'unreal':
        if default is None:
            if not dx12:
                default, conf = 'd3d11', 'medium'
            elif engine.get('major') == 'UE5':
                default, conf = 'd3d12', 'medium'
            else:
                default, conf = 'd3d11', 'low'
                ev.append('Unreal 4: DX11 unless the project chose DX12 (not readable from the packaged config)')
        if dx12 and default != 'd3d12':
            switch, kind = '-dx12', 'needed' if conf != 'low' else 'likely needed'
        elif dx12 and conf != 'high':
            switch, kind = '-dx12', 'harmless (DX12 is probably the default already)'
    elif eng == 'unity':
        if default is None:
            default, conf = 'd3d11', 'medium'
        if dx12 and default != 'd3d12':
            switch, kind = '-force-d3d12', 'needed' if conf == 'high' else 'likely needed'
    elif eng == 'godot':
        if default is None:
            default, conf = ('vulkan' if 'vulkan' in apis or 'vulkan?' in apis else None), 'medium'
        if dx12 and default != 'd3d12':
            switch, kind = '--rendering-driver d3d12', 'needed (Godot 4.3 or newer)'
    elif default is None:
        if 'd3d12' in apis and not ({'d3d11', 'vulkan'} & apis) and not vk_ambiguous:
            default, conf = 'd3d12', 'high'
        elif 'streamline' in apis and 'd3d12' in apis and not vk_ambiguous:
            default, conf = 'd3d12', 'medium'
        elif dx12 and (vk_ambiguous or 'd3d11' in apis):
            ev.append('DX12 and ' + ('Vulkan' if vk_ambiguous else 'DX11') + ' paths: the game\'s own setting decides')
        elif dx12:
            default, conf = 'd3d12', 'medium'
        else:
            for api in ('vulkan', 'd3d11', 'd3d9', 'opengl'):
                if api in apis:
                    default, conf = api, 'medium'
                    break
            else:
                if 'vulkan?' in apis:
                    default, conf = 'vulkan', 'low'
    if dx12_store and not any(s['default'] for s in dx12_store) and default != 'd3d12':
        switch, kind = dx12_store[0]['arg'], 'the launcher\'s own DX12 entry'
    return dict(apis=sorted(apis), dx12=dx12, default=default, switch=switch, switch_kind=kind, confidence=conf, evidence=ev,
                current_switch=current_switch, code_files=code_files)


# ------------------------------------------------------------------------------------------------------- GE-Proton fixes
PROTONFIX_API = re.compile(r'''(append_argument|replace_command)\(([^)]*)\)''')
PROTONFIX_CALL = re.compile(r'''\butil\.(\w+)\(([^)]*)\)''')
OFF_DX12 = re.compile(r'(?<![\w-])(-vulkan|-force-vulkan|-dx11|-d3d11|-force-d3d11|/dx11|-dx9|-opengl|-force-glcore)(?![\w-])|vulkan', re.I)


def compat_tool_dirs(game, home):
    """Folders of the compatibility tool Steam maps the game to (or the default one)."""
    name = game.get('compat_tool')
    if not name:
        return []
    roots = [Path(game['steam_root'])/'compatibilitytools.d'] if game.get('steam_root') else []
    roots += [Path(home)/'.steam/root/compatibilitytools.d', Path('/usr/share/steam/compatibilitytools.d')]
    return [r/name for r in roots if (r/name).is_dir()]


def protonfix(game, home):
    """What the game's GE-Proton fix does to its graphics API: dict(tool, change) when the installed fix for this
    Steam AppID switches the game off DirectX 12 (an argument such as -vulkan or -dx11, or another executable), else
    None. Read as text; never imported or run."""
    if game.get('store') != 'steam' or not str(game.get('id') or '').isdecimal():
        return None
    for tool in compat_tool_dirs(game, home):
        fix = tool/'protonfixes/gamefixes-steam'/(str(game['id']) + '.py')
        try:
            text = fix.read_text(errors='replace')
        except OSError:
            continue
        for call, args in PROTONFIX_API.findall(text):
            m = OFF_DX12.search(args)
            if m:
                change = call + '(' + args.strip()[:80] + ')'
                # PROTONFIXES_DISABLE=1 turns off the whole fix, not only its API switch: name what else it does.
                others = [f'{name}({a.strip()[:40]})' for name, a in PROTONFIX_CALL.findall(text) if f'{name}({a.strip()[:80]})' != change]
                return dict(tool=tool.name, change=change, others=list(dict.fromkeys(others))[:6])
    return None


# -------------------------------------------------------------------------------------------------------------- scan
def scan_folder(game, selected=None, home=None):
    """Scan one game record (installed_games(), game_for_exe() or dict(path=...)) for the executable selected (a path
    relative to the game folder, or None for the best candidate). Returns a JSON-able dict that compat.decide reads."""
    home = Path(home or Path.home())
    root = Path(game['path'])
    res = dict(store=game.get('store'), id=game.get('id'), name=game.get('name'), root=str(root), complete=False)
    if not root.is_dir():
        res['error'] = 'the game folder is missing'
        return res
    tree, cache = Tree(root), {}
    res.update(files=len(tree.files), truncated=tree.truncated, installer_records=len(tree.states))
    elf = sorted(r for r, s in tree.files.items() if s > 4096 and (r.lower().endswith(('.x86_64', '.x86')) or
                 '.' not in r.rsplit('/', 1)[-1]) and _is_elf(tree.full(r)))[:3]
    ranked, stubs, notes = rank_exes(tree, game, cache)
    best = ranked[0]['rel'] if ranked else None
    exe = selected if selected is not None else best
    if exe is not None and exe not in tree.files:
        exe = tree.lower.get(exe.lower(), exe)
    info = _info(tree, exe, cache) if exe and exe in tree.files else None
    res['exe'] = dict(selected=exe, best=best, confidence=exe_confidence(ranked), candidates=ranked[:6], notes=notes,
                      bits=info['bits'] if info else None, parsed=bool(info), imports=bool(info and (info['imports'] or info['delay_imports'])),
                      stub=stubs.get(exe) if exe else None, native_linux=elf,
                      product=((info or {}).get('version') or {}).get('strings', {}).get('ProductName'))
    res['anticheat'] = detect_anticheat(tree)
    mods = [dict(path=d, what=d.rsplit('/', 1)[-1] + '/') for d in tree.foreign_dirs if not d.rsplit('/', 1)[-1].lower().startswith(STATE_PREFIX)]
    exe_dir = (exe.rsplit('/', 1)[0] + '/') if exe and '/' in exe else ''
    for rel in sorted(tree.files):
        low = rel.lower()
        name = low.rsplit('/', 1)[-1]
        beside = low.startswith(exe_dir.lower()) and '/' not in low[len(exe_dir):]
        if name in FOREIGN_FILES or (name in PROXY_NAMES and beside) or low in tree.created:
            why = foreign(tree, rel, _info(tree, rel, cache) if name.endswith(('.dll', '.asi')) else None)
            if not why and name in PROXY_NAMES:
                pi = _info(tree, rel, cache) or {}
                if 'Microsoft Corporation' not in pi.get('signers', []):
                    why = 'a proxy-named DLL beside the executable'
            if why:
                mods.append(dict(path=rel, what=why))
    res['mods'] = mods
    res['protonfix'] = protonfix(game, home)
    if not exe or exe not in tree.files:
        res['engine'] = dict(name='unity (Linux build)' if 'unityplayer.so' in tree.by_name else 'unknown', version='unknown', confidence='low')
        res['api'] = dict(apis=[], dx12=False, default=None, switch=None, confidence='low', evidence=[], current_switch=[])
        res['inputs'] = {}
        res['complete'] = not tree.truncated
        return res
    if info:
        engine = detect_engine(tree, exe, info, cache)
        log = runtime_log(game, tree, engine, exe)
        api = detect_api(tree, game, exe, info, engine, cache, log)
    else:  # an executable that is no readable PE: only the files beside it say anything
        engine, log = dict(name='unknown', version='unknown', confidence='low'), None
        api = dict(apis=[], dx12=False, default=None, switch=None, switch_kind=None, confidence='low', evidence=[], current_switch=[],
                   code_files=[])
    inputs = detect_inputs(tree, exe, cache, api.pop('code_files'))
    # DX12 confirmed only through the game's DX12 upscaler backends (RDR2: string references only in the executable).
    backends = [f['path'] for k in ('agility', 'fsr2', 'fsr31', 'xess', 'dlss') for f in (inputs.get(k) or {}).get('files', [])
                if f['path'].lower().endswith(('d3d12core.dll', 'ffx_fsr2_api_dx12_x64.dll', 'amd_fidelityfx_dx12.dll',
                                               'amd_fidelityfx_upscaler_dx12.dll', 'amd_fidelityfx_loader_dx12.dll'))]
    if not api['dx12'] and backends and 'd3d12?' in api['apis']:
        api['dx12'] = True
        api['evidence'].append('DX12 upscaler backends: ' + ', '.join(b.rsplit('/', 1)[-1] for b in backends[:3]))
        if not api['switch']:
            api['default'], api['confidence'] = None, 'low'
    res.update(engine=engine, api=api, runtime_log=log, inputs=inputs, complete=not tree.truncated)
    sdk2 = [f for f in own_files(inputs, 'fsrfg') if f['path'].lower().endswith('amd_fidelityfx_framegeneration_dx12.dll')]
    combined = [f for f in own_files(inputs, 'fsr31') if f['path'].lower().endswith('amd_fidelityfx_dx12.dll')]
    unity = unity_dlss_use(tree, inputs, engine)
    if unity and unity['used']:
        inputs['dlss']['code'].append(unity['where'] + ' (Unity\'s NVIDIA module)')
    res['dlss_unconfirmed'] = ('nvngx_dlss.dll and NVUnityPlugin.dll come with Unity\'s NVIDIA module, and the game\'s code '
                               f'never names DLSS ({unity["where"]})') if unity and not unity['used'] else None
    res['upscalers'] = [k for k in HOOKABLE if present(inputs, k) and not (k == 'dlss' and res['dlss_unconfirmed'])]
    res['game_fg'] = dict(fsrfg_sdk2=bool(sdk2), dlssg=present(inputs, 'dlssg'), fsrfg_combined=bool(combined) or present(inputs, 'fsrfg'),
                          fsrfg30=present(inputs, 'fsrfg30'))
    # The game's own libxess_fg.dll beside the executable (a verified native recipe needs only this, as 0.9.0 did); the
    # automatic native route also needs no XeSSMFG folder there (that enabler's OptiFG installs put Intel's DLL beside it).
    res['xefg_beside'] = bool(own_files(inputs, 'xefg', beside=True))
    res['native_xefg'] = res['xefg_beside'] and not (root/exe_dir/'XeSSMFG').exists()
    elsewhere = own_files(inputs, 'xefg', beside=False)
    res['native_xefg_elsewhere'] = elsewhere[0]['path'] if elsewhere else None
    res['dlss_copy'] = bool(own_files(inputs, 'dlss')) and any(f['path'].lower().endswith('nvngx_dlss.dll') for f in own_files(inputs, 'dlss'))
    res['fg_toggle_hints'] = sorted({c.split(': ', 1)[-1] for k in ('dlssg', 'fsrfg') for c in (inputs.get(k) or {}).get('code', []) if 'Unreal' in c})
    return res


def scan_exe(exe, home=None):
    """scan_folder for the game holding exe, analysed for exe."""
    exe = Path(exe).resolve()
    game = game_for_exe(exe, home)
    root = Path(game['path']).resolve()
    selected = exe.relative_to(root).as_posix() if exe.is_relative_to(root) else exe.name
    if not exe.is_relative_to(root):
        game = dict(game, path=str(exe.parent))
    return scan_folder(game, selected, home)
