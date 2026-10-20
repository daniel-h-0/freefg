#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The source companion of a package: <name>-source.zip, written beside the package directory.

The package bundles a build of an OptiScaler fork (GPL-3.0), so every archived package is offered with the matching
source. The companion holds, under <name>-source/source/:

  <every keep.txt file>          this project's code, installer, tests, documents and release tooling
  <package.json source_companion "files">
                                 further files of this tree, such as the research driver that built the fork
  OptiScaler/                    the fork's own tree at its locked build commit (inputs.lock.json optiscaler-fork
                                 source.commit, checked against source.tree; the group is under "work" until the fork's
                                 release is public, then under "fetch"), plus its build route at the locked tag commit
                                 (source.build_route: FORK.md, which documents the build, and tools/bc250-build.py, the
                                 script that ran it; the tag commit must add only these files to the build commit's
                                 tree, and the checkout's tag source.tag must point at it). Read from the fork's git
                                 checkout as git stores them (no line-ending conversion), so the bytes do not depend on
                                 the git configuration of the machine; nothing in the checkout is written. Submodules
                                 are not bundled here
  optiscaler-source-pins.json    build commit and tree, tag and tag commit, the build route files, branch, upstream base,
                                 the fork's own commits, each submodule's public repository and pinned commit, how the
                                 shipped DLL was built and, when the lock names it (source.archive), the fork's recursive
                                 source archive (release/fork_source_archive.py: the same source with the submodules)

and <name>-source/source-manifest.json with the sha256 of every file. The archive is deterministic (sorted entries,
fixed timestamps and permissions), so assembling the same inputs again gives the same bytes, and the package's
SOURCE.json and SOURCE.md (which name the archive and its sha256) stay covered by a qualification receipt. Neither
names a git commit of this repository: committing an unchanged tree does not change them.

The lock's records of the fork must agree with each other (check_records()): source.archive names the same tag, tag
commit and build commit as source, and the fork's release fetch group (release_fetch while the group is under "work",
the group itself once it is under "fetch") pins the tag commit. A moved tag therefore stops every reader until the lock
follows it (release/fork_source_archive.py, "Moving the tag").
"""
import hashlib
import json
import os
import subprocess
import zipfile

from config import FORK_GROUP, REPO, ReleaseError, fork_source_record, sha256

ZIP_TIME = (1980, 1, 1, 0, 0, 0)
INSTRUCTION = ('Offer this source archive in the same place as the package download, for as long as the package is '
               'offered. It is not needed to install or run anything.')
# git modes of the tree entries the fork readers accept: regular and executable files, submodule links.
FILE_MODES = {'100644': False, '100755': True}
GITLINK = '160000'
# What to do when the lock's fork records disagree with the checkout or with each other.
FOLLOW_UP = ('After a new fork commit and a moved tag: set source.tag_commit (and release_fetch.commit) to the tag\'s '
             'commit, rebuild the recursive source archive with release/fork_source_archive.py and put its "lock" object '
             'into source.archive (release/fork_source_archive.py, "Moving the tag")')


def git(folder, *arguments, binary=False):
    """Read-only git query of the fork checkout. GIT_OPTIONAL_LOCKS=0 keeps git from refreshing (writing) its index."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    out = subprocess.run(['git', '-C', str(folder), *arguments], capture_output=True, env=env)
    if out.returncode:
        raise ReleaseError(f'git {" ".join(arguments[:3])} failed in {folder}: {out.stderr.decode(errors="replace")[-500:]}')
    return out.stdout if binary else out.stdout.decode()


def tree(folder, commit):
    """[(mode, object id, path)] of every entry of commit's whole tree, in git's order. Refuses symbolic links and
    anything but files and submodule links, which the source archives do not carry."""
    entries = []
    for record in git(folder, 'ls-tree', '-r', '-z', '--full-tree', commit).split('\0'):
        if not record:
            continue
        info, _, path = record.partition('\t')
        mode, _kind, object_id = info.split()
        if mode not in FILE_MODES and mode != GITLINK:
            raise ReleaseError(f'{commit[:12]}:{path} has git mode {mode} (only files and submodules are carried)')
        entries.append((mode, object_id, path))
    return entries


class Blobs:
    """Reads blobs of a repository one at a time through one `git cat-file --batch` process (a context manager)."""

    def __init__(self, folder):
        self.process = subprocess.Popen(['git', '-C', str(folder), 'cat-file', '--batch'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))

    def read(self, object_id):
        self.process.stdin.write(object_id.encode() + b'\n')
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode().split()
        if len(header) != 3 or header[1] != 'blob':
            raise ReleaseError(f'Not a blob: {object_id} ({" ".join(header)})')
        data = self.process.stdout.read(int(header[2]))
        self.process.stdout.read(1)
        return data

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.wait()


def check_commit(folder, commit, tree_id=None):
    """The commit's tree id, after checking that the checkout has the commit (and, if given, that tree)."""
    if git(folder, 'rev-parse', '--verify', '--quiet', f'{commit}^{{commit}}').strip() != commit:
        raise ReleaseError(f'The checkout lacks commit {commit}: {folder}')
    actual = git(folder, 'rev-parse', f'{commit}^{{tree}}').strip()
    if tree_id and actual != tree_id:
        raise ReleaseError(f'Commit {commit} has tree {actual}, locked {tree_id}')
    return actual


def submodules(folder, commit, entries):
    """[{path, url, commit}] of the submodules commit pins: .gitmodules at commit against the tree's links."""
    names = {}
    if any(path == '.gitmodules' for _mode, _object, path in entries):
        for line in git(folder, 'config', '--blob', f'{commit}:.gitmodules', '--list').splitlines():
            key, _, value = line.partition('=')
            name, _, field = key.removeprefix('submodule.').rpartition('.')
            names.setdefault(name, {})[field] = value
    links = {path: object_id for mode, object_id, path in entries if mode == GITLINK}
    out = []
    for entry in sorted(names.values(), key=lambda e: e['path']):
        if entry['path'] not in links:
            raise ReleaseError(f'.gitmodules names {entry["path"]}, which the fork tree does not pin')
        out.append(dict(path=entry['path'], url=entry['url'], commit=links.pop(entry['path'])))
    if links:
        raise ReleaseError('Fork tree pins submodules .gitmodules does not name: ' + ', '.join(sorted(links)))
    return out


def check_tag(folder, source):
    """The tag source.tag of the fork checkout must point at source.tag_commit: the source offer names the tag, and a
    tag moved to another commit (a new FORK.md commit) would offer files the lock does not describe."""
    out = subprocess.run(['git', '-C', str(folder), 'rev-parse', '--verify', '--quiet',
                          f'refs/tags/{source["tag"]}^{{commit}}'], capture_output=True,
                         env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    resolved = out.stdout.decode().strip()
    if out.returncode or not resolved:
        raise ReleaseError(f'The fork checkout has no tag {source["tag"]} ({folder}): fetch it (git fetch <the fork\'s '
                           f'repository> tag {source["tag"]}); the source offer names that tag')
    if resolved != source['tag_commit']:
        raise ReleaseError(f'Tag {source["tag"]} points at {resolved[:12]} in the fork checkout, but inputs.lock.json '
                           f'names tag_commit {source["tag_commit"][:12]}. ' + FOLLOW_UP)
    return resolved


def record_problems(section, group, source, archive=True):
    """How the lock's records of the fork disagree: source.archive (with archive) against source, and the fork's
    release fetch group (release_fetch under "work", the group itself under "fetch") against source.tag_commit."""
    problems = []
    if archive and source.get('archive'):
        for key in ('tag', 'tag_commit', 'commit'):
            if source['archive'].get(key) != source.get(key):
                problems.append(f'source.archive.{key} is {source["archive"].get(key)}, source.{key} {source.get(key)}')
    fetch = group if section == 'fetch' else group.get('release_fetch')
    label = 'commit' if section == 'fetch' else 'release_fetch.commit'
    if fetch is not None and fetch.get('commit') != source.get('tag_commit'):
        problems.append(f'{label} is {fetch.get("commit")}, source.tag_commit {source.get("tag_commit")}')
    return problems


def check_records(section, group, source, archive=True):
    problems = record_problems(section, group, source, archive)
    if problems:
        raise ReleaseError(f'inputs.lock.json {section}.{FORK_GROUP}: its records of the fork disagree ('
                           + '; '.join(problems) + '). ' + FOLLOW_UP)


def build_route(folder, source):
    """[(mode, object id, path)] of the build route (source.build_route) at the tag commit (source.tag_commit), after
    checking that the checkout's tag source.tag points at the tag commit and that its tree is the build commit's tree
    plus exactly these files."""
    for key in ('tag', 'tag_commit', 'build_route'):
        if not source.get(key):
            raise ReleaseError(f'inputs.lock.json {FORK_GROUP}.source lacks "{key}": the source offer needs the '
                               'build route (FORK.md and the build script) at a locked commit')
    check_commit(folder, source['tag_commit'])
    check_tag(folder, source)
    ancestor = subprocess.run(['git', '-C', str(folder), 'merge-base', '--is-ancestor', source['commit'],
                               source['tag_commit']], capture_output=True, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    if ancestor.returncode:
        raise ReleaseError(f'Tag commit {source["tag_commit"][:12]} does not descend from build commit '
                           f'{source["commit"][:12]}')
    changes = git(folder, 'diff-tree', '-r', '-z', '--no-renames', '--name-status', source['commit'],
                  source['tag_commit']).split('\0')
    changed = dict(zip(changes[1::2], changes[0::2]))
    wanted = set(source['build_route'])
    if set(changed) != wanted or set(changed.values()) != {'A'}:
        raise ReleaseError(f'Tag commit {source["tag_commit"][:12]} must only add {sorted(wanted)} to build commit '
                           f'{source["commit"][:12]}; it changes {dict(sorted(changed.items()))}')
    entries = {path: (mode, object_id) for mode, object_id, path in tree(folder, source['tag_commit'])}
    out = []
    for path in source['build_route']:
        mode, object_id = entries[path]
        if mode not in FILE_MODES:
            raise ReleaseError(f'Build route entry {path} is not a file (git mode {mode})')
        out.append((mode, object_id, path))
    return out


def route_files(folder, source):
    """{path: bytes} of the build route at the tag commit (build_route(), so with its checks)."""
    with Blobs(folder) as blobs:
        return {path: blobs.read(object_id) for _mode, object_id, path in build_route(folder, source)}


def placeholder_problems(files, source, pattern, marker='[DRAFT]'):
    """[problem] for the build route files ({path: bytes}, route_files()) that still carry a placeholder of pattern
    (packaging/public/check_public_docs.py PLACEHOLDER) or the draft marker: the public archive's source companion and
    the fork's release offer these files as they are."""
    problems = []
    for path, data in sorted(files.items()):
        text = data.decode('utf-8', errors='replace')
        found = sorted({m.group(0) for m in pattern.finditer(text)}) + ([marker] if marker in text else [])
        if found:
            problems.append(f'the fork\'s {path} at tag {source["tag"]} ({source["tag_commit"][:12]}) still carries '
                            + ', '.join(found))
    return problems


def route_placeholders(config, pattern, marker='[DRAFT]'):
    """placeholder_problems() of the fork checkout's build route files at the locked tag commit."""
    _section, _group, source = fork_source_record(config.lock)
    return placeholder_problems(route_files(config.fork_source(), source), source, pattern, marker)


def fork_files(config):
    """{relative path: (bytes, executable)} of the fork's tree at the locked build commit plus its build route at the
    tag commit, and its pins record."""
    section, group, source = fork_source_record(config.lock)
    check_records(section, group, source)
    folder = config.fork_source()
    commit = source['commit']
    tree_id = check_commit(folder, commit, source['tree'])
    entries = tree(folder, commit)
    route = build_route(folder, source)
    files, route_record = {}, []
    with Blobs(folder) as blobs:
        for mode, object_id, path in entries:
            if mode != GITLINK:
                files[path] = (blobs.read(object_id), FILE_MODES[mode])
        for mode, object_id, path in route:
            if path in files:
                raise ReleaseError(f'Build route file {path} is already in the build commit\'s tree')
            data = blobs.read(object_id)
            files[path] = (data, FILE_MODES[mode])
            route_record.append(dict(path=path, git_blob=object_id, sha256=hashlib.sha256(data).hexdigest()))
    commits = [line.split(' ', 1) for line in git(folder, 'log', '--format=%H %s', f'{source["upstream_base"]}..{commit}')
               .splitlines()]
    pins = dict(
        commit=commit, tree=tree_id, tag=source['tag'], tag_commit=source['tag_commit'], build_route=route_record,
        branch=source['branch'], upstream=source['upstream'],
        upstream_base=source['upstream_base'],
        **{key: source[key] for key in ('reverted_upstream', 'fixed_upstream') if key in source},
        fork_commits=[dict(commit=c, subject=s) for c, s in commits],
        build=source['build'],
        submodules=submodules(folder, commit, entries),
        submodule_note='Submodule sources are not bundled in this archive: each is the public repository above at the '
                       'pinned commit; clone it at that commit into its path to build (FORK.md, "Building").'
                       + (' The fork\'s recursive source archive below holds them, apart from those it names under '
                          'pointer_only.' if source.get('archive') else ''),
        shipped=dict(file='opti/OptiScaler.dll', sha256=group['files']['OptiScaler.dll']['sha256']),
    )
    if source.get('archive'):
        pins['recursive_source_archive'] = source['archive']
    return files, pins


def project_files(names):
    out = {}
    for name in names:
        path = REPO / name
        out[name] = (path.read_bytes(), os.access(path, os.X_OK))
    return out


def write_zip(target, root, files):
    """A deterministic zip of {path: (bytes, executable)} under root/, plus root/source-manifest.json."""
    manifest = {name: hashlib.sha256(data).hexdigest() for name, (data, _executable) in sorted(files.items())}
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            data, executable = files[name]
            info = zipfile.ZipInfo(f'{root}/source/{name}', ZIP_TIME)
            info.create_system = 3
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)
        info = zipfile.ZipInfo(f'{root}/source-manifest.json', ZIP_TIME)
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, (json.dumps(manifest, indent=2) + '\n').encode(), compresslevel=9)
    with zipfile.ZipFile(target) as z:
        if z.testzip():
            raise ReleaseError('CRC failure in the source companion')
        for name, digest in manifest.items():
            if hashlib.sha256(z.read(f'{root}/source/{name}')).hexdigest() != digest:
                raise ReleaseError(f'Source companion verification failed: {name}')
    return len(manifest)


def archive_path(config, name, folder='package'):
    return config.build / folder / f'{name}-source.zip'


def build(config, spec, name, keep_names, target):
    """Write the companion of package <name> to target (assemble.py moves it to archive_path() once every check has
    passed); returns the SOURCE.json record."""
    declared = spec['source_companion']
    files = project_files(keep_names)
    for inside, source in declared.get('files', {}).items():
        if not source.startswith('repo:'):
            raise ReleaseError(f'source_companion files must be repo: sources: {source}')
        if inside in files:
            raise ReleaseError(f'{inside} is already in the companion (keep.txt)')
        path = REPO / source.removeprefix('repo:')
        if not path.is_file():
            raise ReleaseError(f'Missing source companion file {path.relative_to(REPO)} (an exported tree does not carry '
                               'it: use assemble.py --no-source-companion there)')
        files[inside] = (path.read_bytes(), os.access(path, os.X_OK))
    fork, pins = fork_files(config)
    prefix = declared['optiscaler_dir'].rstrip('/') + '/'
    for path, entry in fork.items():
        if prefix + path in files:
            raise ReleaseError(f'Fork file collides with a project file: {prefix + path}')
        files[prefix + path] = entry
    if declared['optiscaler_pins'] in files:
        raise ReleaseError(f'{declared["optiscaler_pins"]} collides with a project file')
    files[declared['optiscaler_pins']] = ((json.dumps(pins, indent=2) + '\n').encode(), False)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = write_zip(target, f'{name}-source', files)
    record = dict(archive=archive_path(config, name).name, sha256=sha256(target), bytes=target.stat().st_size,
                  files=count + 1, optiscaler_commit=pins['commit'], optiscaler_tag=pins['tag'],
                  optiscaler_tag_commit=pins['tag_commit'], instruction=INSTRUCTION)
    if pins.get('recursive_source_archive'):
        archive = pins['recursive_source_archive']
        links = {link['path']: link for link in pins['submodules']}
        record['optiscaler_recursive_source'] = dict(
            name=archive['name'], sha256=archive['sha256'],
            not_bundled=[dict(path=path, url=links[path]['url'], commit=links[path]['commit'])
                         for path in archive.get('pointer_only', []) if path in links])
    return record


def source_md(record):
    text = ('# Source\n\nThe matching source of this package is in **' + record['archive'] + '**, offered alongside this '
            'download. It is not needed to install or run anything.\n\n'
            'It holds this project\'s source and release tooling, and the complete corresponding source of the bundled '
            '`opti/OptiScaler.dll` (GNU GPL version 3): the OptiScaler fork\'s tree at commit `'
            + record['optiscaler_commit'] + '`, with the `FORK.md` and `tools/bc250-build.py` of tag `'
            + record['optiscaler_tag'] + '` that document and run its build (`source/OptiScaler/`). '
            '`source/optiscaler-source-pins.json` names the public repository and commit of each submodule.\n\n')
    recursive = record.get('optiscaler_recursive_source')
    if recursive:
        text += ('The fork\'s source together with its submodules is also available as one archive, **'
                 + recursive['name'] + '** (SHA256 `' + recursive['sha256'] + '`), with the release of the fork at tag `'
                 + record['optiscaler_tag'] + '`')
        missing = recursive.get('not_bundled') or []
        if missing:
            text += (', apart from ' + ', '.join(f'`{m["path"]}` ({m["url"]} at commit `{m["commit"]}`)' for m in missing)
                     + (', which comes' if len(missing) == 1 else ', which come') + ' from its own repository')
        text += '.\n\n'
    text += ('Whoever passes this package on should offer the matching source in the same place. Credits and licences '
             'are in this package (`licenses/` and its documents).\n\nSHA256: `' + record['sha256'] + '`\n')
    return text
