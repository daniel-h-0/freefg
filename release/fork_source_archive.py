#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The OptiScaler fork's recursive source archive, <name>.tar.xz, for the fork's release beside the built
OptiScaler.dll (GPL-3.0 section 6: the Corresponding Source in the same place as the object code, without relying on
the submodules' third-party repositories staying online).

Under <name>/ (default name: OptiScaler-<tag>-source) the archive holds:

  the fork's tree at the locked build commit (inputs.lock.json optiscaler-fork source.commit, checked against
  source.tree; the group is under "work" until the fork's release is public, then under "fetch") plus the build route
    at the locked tag commit (source.build_route: FORK.md and tools/bc250-build.py; the tag commit may add or update only these
  files, and the checkout's tag source.tag must point at it), i.e. the tag's tree, read from the fork's git checkout
  (XEMFG_OPTISCALER_SOURCE or --optiscaler-source; nothing in it is written);
  every submodule the build commit pins (.gitmodules and the tree's links) at its pinned commit, fetched read-only from
  the repository .gitmodules names (git fetch --depth 1 <url> <commit> into one bare repository per URL under
  <cache>/optiscaler-fork-submodules/, then checked by commit id) and placed at its path. A submodule named with
  --pointer-only (default: external/xess, Intel's XeSS SDK: Intel's licence allows its redistribution in binary form
  only, and this project ships no Intel files) keeps an empty folder, like a submodule that is not checked out, and is
  recorded by repository, commit and tree (only its commit object is fetched: --filter=tree:0, which shows that the
  repository still has it without downloading its files);
  SOURCE-ARCHIVE.md (what is in the archive and how to build it), SOURCE-ARCHIVE.json (commits, trees, repositories,
  per part the file count, bytes and the sha256 of its file list, the files .gitattributes turns into CRLF on a
  checkout) and SOURCE-ARCHIVE.sha256 (every other file, for `sha256sum -c` in the extracted folder).

Files are stored as git stores them (no line-ending conversion, no export-subst or export-ignore), so the archive does
not depend on the git configuration of the machine that makes it; a git checkout on Linux differs only in the files
SOURCE-ARCHIVE.json lists under eol_crlf_on_checkout.

Deterministic: the root folder, then every folder and file sorted by path, then the three SOURCE-ARCHIVE files; every
mtime the build commit's committer time; uid and gid 0 with no user or group names; modes 0644/0755 (files by git's
executable bit, folders 0755); POSIX pax format; xz with CRC64 at preset 9 in one thread. Made again from the same
commits it has the same bytes. The sha256 of the uncompressed tar is recorded too: an xz library that compresses
differently cannot change it.

Written beside the archive: <name>.tar.xz.sha256 (sha256sum format) and <name>.json (sizes, both sha256, the parts,
and "lock": the object to put into inputs.lock.json work.optiscaler-fork source.archive, which names the archive in the
source companion). The archive is read back and checked before it replaces an earlier one.

  python3 release/fork_source_archive.py [--out DIR] [--name NAME] [--pointer-only PATH ... | --bundle-all]
                                         [--submodule-url PATH=URL ...] [--fetch-only] [--offline]
  python3 release/fork_source_archive.py --verify DIR/NAME.tar.xz     # check an archive against the .json beside it

The result lists under "warnings" the placeholders ([PRODUCT], [REPO-URL], ...) and draft markers still in the build
route files: an archive for the fork's release is made after FORK.md is filled in.

Moving the tag (a new commit on the fork's branch, such as the one that fills in FORK.md before publication):
  1. Commit only additions or updates to FORK.md and tools/bc250-build.py on the branch (the build commit's tree stays as it is, so the DLL does
     not change), as the fork's publishing identity (author and committer) under TZ=UTC, so that the dates read +0000,
     and move the annotated tag onto it the same way: TZ=UTC git tag -f -a <tag> <commit>. The build commit and the
     commits before it keep their dates: changing them changes the commit digits in the DLL's version string.
  2. In inputs.lock.json optiscaler-fork: set source.tag_commit and release_fetch.commit (the group's own "commit" once
     it is under "fetch") to that commit.
  3. Run this tool again (--out a new folder) and put its "lock" object into source.archive.
  4. Commit the lock, and assemble again: SOURCE.md and SOURCE.json then name the new archive and its sha256.
Until all of that is done, the source companion and this tool refuse (and so does the maintainers' publication tool):
they resolve the tag in the checkout and compare the lock's records (release/source_companion.py check_tag,
check_records).
"""
import argparse
import contextlib
import hashlib
import io
import json
import lzma
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ReleaseError, add_arguments, fork_source_record  # noqa: E402
import source_companion as fork  # noqa: E402

POINTER_ONLY = {
    'external/xess': 'Intel XeSS SDK: Intel\'s licence allows its redistribution in binary form only, and this '
                     'project ships no Intel files; fetch it from its repository at the commit named',
}
XZ = dict(format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=9)
RECORD_FILES = ('SOURCE-ARCHIVE.md', 'SOURCE-ARCHIVE.json', 'SOURCE-ARCHIVE.sha256')
# Placeholders and the draft marker that a published FORK.md must not carry any more: the placeholders of the public
# documents, which release/assemble.py --archive refuses in the build route (check_public_docs.py PLACEHOLDER), and
# [DRAFT] (unfilled_pattern()). A bracketed name of OptiScaler's own, such as the OptiScaler.ini section [BC250], is
# neither. In a tree without that check, every bracketed upper-case token counts.
UNFILLED = re.compile(r'\[[A-Z][A-Z0-9 -]*[A-Z0-9]\]')
DRAFT_MARKER = '[DRAFT]'
CACHE_FOLDER = 'optiscaler-fork-submodules'
GIT_ENV = dict(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')


def run_git(folder, *arguments, stdin=None):
    return subprocess.run(['git', '-C', str(folder), *arguments], input=stdin, capture_output=True,
                          env=dict(os.environ, **GIT_ENV))


def cache_repository(cache, url, commit_only=False):
    """The bare repository holding the fetched commits of url (one per URL, and one more for commit-only fetches;
    created when missing)."""
    slug = re.sub(r'[^A-Za-z0-9._-]+', '_', re.sub(r'^[A-Za-z+]+://', '', url).removesuffix('.git').strip('/'))
    folder = cache / CACHE_FOLDER / (slug + ('.commit-only' if commit_only else '') + '.git')
    if not folder.is_dir():
        folder.parent.mkdir(parents=True, exist_ok=True)
        out = subprocess.run(['git', 'init', '--quiet', '--bare', str(folder)], capture_output=True)
        if out.returncode:
            raise ReleaseError(f'git init failed: {out.stderr.decode(errors="replace")[-300:]}')
    return folder


def has_commit(folder, commit):
    out = run_git(folder, 'cat-file', '-t', commit)
    return out.returncode == 0 and out.stdout.strip() == b'commit'


def ensure_submodule(config, url, commit, commit_only=False):
    """(cache repository of url holding commit, whether it was fetched now): fetched once, read-only, depth 1, and
    kept by a ref so that git's housekeeping never drops it. commit_only fetches the commit object alone
    (--filter=tree:0), which proves that the repository has it and names its tree without downloading its files."""
    folder = cache_repository(config.cache, url, commit_only)
    fetched = False
    if not has_commit(folder, commit):
        if config.offline:
            raise ReleaseError(f'{url} {commit[:12]} is not in the cache ({folder}) and --offline forbids fetching')
        out = run_git(folder, 'fetch', '--quiet', '--depth=1', '--no-tags', *(['--filter=tree:0'] if commit_only else []),
                      url, commit)
        if out.returncode or not has_commit(folder, commit):
            raise ReleaseError(f'Could not fetch {commit} from {url}: {out.stderr.decode(errors="replace")[-400:]}')
        fetched = True
    if run_git(folder, 'update-ref', f'refs/pinned/{commit}', commit).returncode:
        raise ReleaseError(f'git update-ref failed in {folder}')
    return folder, fetched


def crlf_on_checkout(folder, commit, paths):
    """The paths that the .gitattributes of commit turn into CRLF on a checkout (eol=crlf on a text file)."""
    if not paths:
        return []
    out = run_git(folder, 'check-attr', '-z', '--stdin', f'--source={commit}', 'eol', 'text',
                  stdin='\0'.join(paths).encode() + b'\0')
    if out.returncode:
        raise ReleaseError(f'git check-attr failed in {folder}: {out.stderr.decode(errors="replace")[-300:]}')
    fields = out.stdout.decode().split('\0')
    values = {}
    for path, attribute, value in zip(fields[0::3], fields[1::3], fields[2::3]):
        values.setdefault(path, {})[attribute] = value
    return sorted(p for p, v in values.items() if v.get('eol') == 'crlf' and v.get('text') != 'unset')


class Sink:
    """File-like target of the tar stream: hashes the tar, compresses it with xz, writes and hashes the result."""

    def __init__(self, stream):
        self.stream = stream
        self.compressor = lzma.LZMACompressor(**XZ)
        self.tar, self.xz = hashlib.sha256(), hashlib.sha256()
        self.tar_bytes = self.xz_bytes = 0

    def _out(self, data):
        if data:
            self.stream.write(data)
            self.xz.update(data)
            self.xz_bytes += len(data)

    def write(self, data):
        self.tar.update(data)
        self.tar_bytes += len(data)
        self._out(self.compressor.compress(data))
        return len(data)

    def finish(self):
        self._out(self.compressor.flush())


def member(name, mtime, data=None, executable=False):
    """A tar header with nothing taken from the machine: fixed owner, time and modes."""
    info = tarfile.TarInfo(name)
    info.mtime = mtime
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    if data is None:
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
    else:
        info.size = len(data)
        info.mode = 0o755 if executable else 0o644
    return info


def list_digest(pairs):
    """sha256 of a sha256sum-style list of (path, digest)."""
    return hashlib.sha256(''.join(f'{digest}  {path}\n' for path, digest in pairs).encode()).hexdigest()


def parents(path):
    out = []
    parent = PurePosixPath(path).parent
    while parent.name:
        out.append(parent.as_posix())
        parent = parent.parent
    return out


def plan(config, folder, pointer_only, url_overrides):
    """[part]: the fork's tree (part 0) and each submodule, with the repository folder and entries to read."""
    section, group, source = fork_source_record(config.lock)
    # source.archive is what this tool makes: only the other records must agree with the tag already.
    fork.check_records(section, group, source, archive=False)
    commit = source['commit']
    tree_id = fork.check_commit(folder, commit, source['tree'])
    entries = fork.tree(folder, commit)
    route = fork.build_route(folder, source)
    links = fork.submodules(folder, commit, entries)
    pinned = {link['path'] for link in links}
    for label, names in (('--submodule-url', url_overrides), ('--pointer-only', pointer_only)):
        unknown = set(names) - pinned
        if unknown:
            raise ReleaseError(f'{label} names paths the fork does not pin: {sorted(unknown)}')
    parts = [dict(label='.', prefix='', folder=folder, commit=commit, tree=tree_id, attributes=source['tag_commit'],
                  entries=[e for e in entries if e[0] != fork.GITLINK and e[2] not in {r[2] for r in route}] + route,
                  extra=dict(tag=source['tag'], tag_commit=source['tag_commit'],
                             build_route=[path for _m, _o, path in route]))]
    for link in links:
        part = dict(label=link['path'], prefix=link['path'] + '/', url=link['url'], commit=link['commit'])
        url = url_overrides.get(link['path'], link['url'])
        if link['path'] in pointer_only:
            repository, fetched = ensure_submodule(config, url, link['commit'], commit_only=True)
            tree_id = run_git(repository, 'rev-parse', f'{link["commit"]}^{{tree}}').stdout.decode().strip()
            part.update(pointer_only=pointer_only[link['path']], fetched_from=url, fetched_now=fetched, tree=tree_id)
        else:
            repository, fetched = ensure_submodule(config, url, link['commit'])
            sub_entries = fork.tree(repository, link['commit'])
            if any(mode == fork.GITLINK for mode, _o, _p in sub_entries):
                raise ReleaseError(f'{link["path"]} has submodules of its own, which this archive does not carry')
            part.update(folder=repository, fetched_from=url, fetched_now=fetched, attributes=link['commit'],
                        tree=fork.check_commit(repository, link['commit']), entries=sub_entries)
        parts.append(part)
    return parts


def unfilled_pattern():
    """The placeholders of check_public_docs.py and the [DRAFT] marker, or UNFILLED without that check."""
    import assemble  # local import: assemble loads the public documents' check
    pattern = assemble.placeholder_pattern()
    return re.compile(re.escape(DRAFT_MARKER) + '|' + pattern.pattern) if pattern is not None else UNFILLED


def unfilled(folder, part):
    """Warnings for the build route files of the fork's part that still carry placeholders or draft markers."""
    route = set(part['extra']['build_route'])
    pattern = unfilled_pattern()
    out = []
    with fork.Blobs(folder) as blobs:
        for _mode, object_id, path in part['entries']:
            if path in route:
                text = blobs.read(object_id).decode('utf-8', errors='replace')
                found = sorted({match.group(0) for match in pattern.finditer(text)})
                if found:
                    out.append(f'{path} still carries {", ".join(found)}: fill it in, commit, move the tag and make '
                               'the archive again before the fork\'s release ("Moving the tag")')
    return out


def readme(name, parts):
    first = parts[0]
    lines = [
        f'# {name}', '',
        'The complete source of the BC-250 OptiScaler fork at tag `' + first['extra']['tag'] + '`, with its submodules. '
        '`FORK.md` describes the fork, the `OptiScaler.dll` built from it and how to build it.', '',
        '- The fork\'s files are the tree of commit `' + first['commit'] + '` (tree `' + first['tree'] + '`), the commit '
        'the DLL is built from, plus `' + '` and `'.join(first['extra']['build_route']) + '` from the tag\'s commit `'
        + first['extra']['tag_commit'] + '`.',
        '- Each submodule is the tree of the commit the fork pins, from the repository its `.gitmodules` names:']
    for part in parts[1:]:
        state = 'not included: ' + part['pointer_only'] if part.get('pointer_only') else 'included'
        lines.append(f'  - `{part["label"]}`: {part["url"]} at `{part["commit"]}` ({state})')
    lines += [
        '',
        'Files are stored as git stores them. `SOURCE-ARCHIVE.json` lists, under `eol_crlf_on_checkout`, any file that '
        'a git checkout on Linux would write with CRLF line endings instead, and gives the file count and SHA-256 of '
        'every part. `SOURCE-ARCHIVE.sha256` holds the SHA-256 of every file (run `sha256sum -c SOURCE-ARCHIVE.sha256` '
        'in this folder).', '',
        'To build, put each submodule that is not included into its folder at the commit above, then follow `FORK.md`, '
        '"Building". `tools/bc250-build.py` writes the git commit of the folder it builds into the DLL\'s version '
        'string, so it needs a git repository; the byte-identical `OptiScaler.dll` comes from the checkout that '
        '`FORK.md`, "Reproducing the shipped DLL", describes.', '']
    return '\n'.join(lines)


def build(config, pointer_only, url_overrides=None, out=None, name=None, fetch_only=False):
    """Fetch the submodules and (unless fetch_only) write the archive; returns the result record."""
    folder = config.fork_source()
    parts = plan(config, folder, pointer_only, url_overrides or {})
    fetched = [dict(path=p['label'], url=p['fetched_from'], commit=p['commit'], tree=p['tree'], fetched_now=p['fetched_now'],
                    objects='commit only' if p.get('pointer_only') else 'commit and tree')
               for p in parts[1:]]
    if fetch_only:
        return dict(fetched=fetched, pointer_only=[p['label'] for p in parts if p.get('pointer_only')])
    _section, _group, source = fork_source_record(config.lock)
    name = name or f'OptiScaler-{source["tag"]}-source'
    out = Path(out).resolve() if out else config.build / 'optiscaler-fork-source'
    out.mkdir(parents=True, exist_ok=True)
    target, partial = out / f'{name}.tar.xz', out / f'.{name}.tar.xz.partial'
    mtime = int(fork.git(folder, 'log', '-1', '--format=%ct', source['commit']).strip())

    files, folders = {}, set()
    for index, part in enumerate(parts):
        if part.get('pointer_only'):
            folders.add(part['label'])
        for mode, object_id, path in part.get('entries', ()):
            full = part['prefix'] + path
            if full in files:
                raise ReleaseError(f'{full} is in two parts of the archive')
            files[full] = (index, object_id, fork.FILE_MODES[mode])
    for path in list(files) + list(folders):
        folders.update(parents(path))
    clash = sorted((folders & set(files)) | (set(RECORD_FILES) & (set(files) | folders)))
    if clash:
        raise ReleaseError(f'Paths that cannot be both file and folder, or that clash with the record files: {clash[:5]}')

    warnings = unfilled(folder, parts[0])
    crlf = {index: crlf_on_checkout(part['folder'], part['attributes'], [p for _m, _o, p in part['entries']])
            for index, part in enumerate(parts) if part.get('entries')}
    lines = {index: [] for index in range(len(parts))}
    partial.unlink(missing_ok=True)
    with contextlib.ExitStack() as stack, open(partial, 'xb') as stream:
        readers = {index: stack.enter_context(fork.Blobs(part['folder'])) for index, part in enumerate(parts)
                   if part.get('entries')}
        sink = Sink(stream)
        with tarfile.open(fileobj=sink, mode='w|', format=tarfile.PAX_FORMAT) as tar:
            tar.addfile(member(name, mtime))
            for path in sorted(files.keys() | folders):
                if path in folders:
                    tar.addfile(member(f'{name}/{path}', mtime))
                    continue
                index, object_id, executable = files[path]
                data = readers[index].read(object_id)
                lines[index].append((path, hashlib.sha256(data).hexdigest(), len(data)))
                tar.addfile(member(f'{name}/{path}', mtime, data, executable), io.BytesIO(data))
            summary = []
            for index, part in enumerate(parts):
                entry = dict(path=part['label'], commit=part['commit'])
                if index:
                    entry['url'] = part['url']
                if part.get('pointer_only'):
                    entry.update(bundled=False, tree=part['tree'], reason=part['pointer_only'])
                else:
                    entry.update(bundled=True, tree=part['tree'], files=len(lines[index]),
                                 bytes=sum(n for _p, _d, n in lines[index]),
                                 files_sha256=list_digest([(p, d) for p, d, _n in lines[index]]),
                                 eol_crlf_on_checkout=[part['prefix'] + p for p in crlf.get(index, [])])
                entry.update(part.get('extra', {}))
                summary.append(entry)
            sums = sorted((p, d) for index in lines for p, d, _n in lines[index])
            record = dict(name=name, mtime=mtime, format='tar (POSIX pax): the root folder, folders and files sorted by '
                          'path, then the SOURCE-ARCHIVE files', files=len(sums), files_sha256=list_digest(sums),
                          parts=summary)
            texts = {'SOURCE-ARCHIVE.md': readme(name, parts).encode(),
                     'SOURCE-ARCHIVE.json': (json.dumps(record, indent=1) + '\n').encode(),
                     'SOURCE-ARCHIVE.sha256': ''.join(f'{d}  {p}\n' for p, d in sums).encode()}
            for path in RECORD_FILES:
                tar.addfile(member(f'{name}/{path}', mtime, texts[path]), io.BytesIO(texts[path]))
        sink.finish()
    members = 1 + len(files) + len(folders) + len(RECORD_FILES)
    try:
        verify_bytes(partial, sink.tar.hexdigest(), members)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    (out / f'{name}.tar.xz.sha256').write_text(f'{sink.xz.hexdigest()}  {target.name}\n')
    lock = dict(name=target.name, sha256=sink.xz.hexdigest(), bytes=sink.xz_bytes, tar_sha256=sink.tar.hexdigest(),
                tar_bytes=sink.tar_bytes, members=members, files=len(sums), files_sha256=record['files_sha256'],
                tag=source['tag'], tag_commit=source['tag_commit'], commit=source['commit'],
                bundled=[p['path'] for p in summary[1:] if p['bundled']],
                pointer_only=[p['path'] for p in summary[1:] if not p['bundled']],
                made_by='release/fork_source_archive.py')
    result = dict(archive=target.name, lock=lock, xz=dict(check='crc64', preset=XZ['preset'], threads=1),
                  python=sys.version.split()[0], parts=summary, fetched=fetched, warnings=warnings)
    (out / f'{name}.json').write_text(json.dumps(result, indent=1) + '\n')
    return result


def verify_bytes(path, tar_sha256, members=None):
    """Decompress the archive, compare the tar's sha256 (and member count), and check every file against the
    archive's own SOURCE-ARCHIVE.sha256."""
    digest = hashlib.sha256()
    with lzma.open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != tar_sha256:
        raise ReleaseError(f'{path.name}: the decompressed tar has sha256 {digest.hexdigest()}, expected {tar_sha256}')
    count, listed, actual = 0, None, {}
    with tarfile.open(path, 'r:xz') as tar:
        for info in tar:
            count += 1
            if not info.isfile():
                continue
            inner = info.name.split('/', 1)[1]
            data = tar.extractfile(info).read()
            if inner == 'SOURCE-ARCHIVE.sha256':
                listed = {line[66:]: line[:64] for line in data.decode().splitlines()}
            elif inner not in RECORD_FILES:
                actual[inner] = hashlib.sha256(data).hexdigest()
    if members is not None and count != members:
        raise ReleaseError(f'{path.name}: {count} members, expected {members}')
    if listed != actual:
        raise ReleaseError(f'{path.name}: the files differ from SOURCE-ARCHIVE.sha256')
    return dict(members=count, files=len(actual))


def verify(path):
    """Check a written archive against the <name>.json beside it."""
    path = Path(path).resolve()
    lock = json.loads(path.with_name(path.name.removesuffix('.tar.xz') + '.json').read_text())['lock']
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != lock['sha256']:
        raise ReleaseError(f'{path.name}: sha256 {digest.hexdigest()}, recorded {lock["sha256"]}')
    return dict(verify_bytes(path, lock['tar_sha256'], lock['members']), sha256=lock['sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', help='output directory (default: <build>/optiscaler-fork-source)')
    parser.add_argument('--name', help='archive name without .tar.xz (default: OptiScaler-<tag>-source)')
    parser.add_argument('--pointer-only', action='append', metavar='PATH',
                        help=f'submodule to record, not bundle (repeatable; default: {", ".join(POINTER_ONLY)})')
    parser.add_argument('--bundle-all', action='store_true', help='bundle every submodule, including the default '
                        'pointer-only ones')
    parser.add_argument('--submodule-url', action='append', default=[], metavar='PATH=URL',
                        help='fetch that submodule from URL (a mirror) instead of the .gitmodules URL; the archive still '
                             'names the .gitmodules URL')
    parser.add_argument('--fetch-only', action='store_true', help='fetch and check the submodule commits; write nothing')
    parser.add_argument('--verify', metavar='ARCHIVE', help='check an archive against the .json written beside it')
    add_arguments(parser)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify), indent=1))
        return
    if args.bundle_all and args.pointer_only:
        parser.error('--bundle-all and --pointer-only exclude each other')
    if args.bundle_all:
        pointer_only = {}
    elif args.pointer_only is not None:
        pointer_only = {p: POINTER_ONLY.get(p, 'not bundled (--pointer-only)') for p in args.pointer_only}
    else:
        pointer_only = dict(POINTER_ONLY)
    try:
        overrides = dict(item.split('=', 1) for item in args.submodule_url)
    except ValueError:
        parser.error('--submodule-url takes PATH=URL')
    config = Config.from_args(args)
    print(json.dumps(build(config, pointer_only, overrides, args.out, args.name, args.fetch_only), indent=1))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
