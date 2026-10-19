# SPDX-License-Identifier: MIT
"""Host-path detection shared by release/export_tree.py (review of exported files) and release/assemble.py (shipped and
emitted JSON): text that names a machine's user, its removable media or this host's administration repository.

A host path is:
  - a home directory, /home/<name> or /var/home/<name> (also inside a file:// URL);
  - a removable-media mount (the media folder under /run);
  - a named folder in a home directory written with a tilde, such as ~/<checkout> or the downloads folder (the hidden
    per-user folders every installation has, such as ~/.steam, ~/.config, ~/.local and ~/.cache, are not host paths);
  - Wine's view of a home directory: a drive letter, then home and a name (Z:\\home\\<name>, also with slashes or the
    doubled backslashes of JSON);
  - a Windows user profile folder, <drive>:\\Users\\<name> (Proton's fixed steamuser is not a host path);
  - this host's administration repository, as a path component, or with review=True also as a bare word (the recipes'
    provenance label still names it as a word, so shipped JSON is checked for the path component only).

Only text is scanned. A file with a NUL byte (DXIL, PE, ELF, archives) is binary, and its bytes can spell anything; a
file that starts with a UTF-16 byte-order mark is decoded first.

The patterns are written in pieces (and with one-character classes) so that this file does not match itself.
"""
import re

_SEP = r'(?:\\\\|\\|/)+'  # one or more path separators: /, \ or JSON's doubled backslash
_NAME = r'[A-Za-z0-9_.-]+'
_END = r'(?=/|\\|$|[\s"\'`,;:)\]}>])'  # a whole path component
_REPO = r'bc250' + r'[-]admin'

_RULES = [
    r'(?:/var)?/' + r'home/' + _NAME + _END,          # home directory (also in file:///…)
    r'/run' + r'/media/',                             # removable media
    r'(?<![\w.-])~/[A-Za-z0-9_]',                     # ~/<named folder>; ~/.<hidden> is fine
    r'\b[A-Za-z]:' + _SEP + r'home' + _SEP + _NAME,   # Wine: Z:\home\<name>
    r'\b[A-Za-z]:' + _SEP + r'Users' + _SEP + r'(?!steamuser\b)' + _NAME,
]
_REPO_COMPONENT = r'[/\\]' + _REPO + r'\b|' + _REPO + r'[/\\]'

SHIPPED = re.compile('|'.join(_RULES + [_REPO_COMPONENT]), re.M)
REVIEW = re.compile('|'.join(_RULES + [_REPO]), re.M)


def text_of(data):
    """The text of a file's bytes, or None when the file is binary (a NUL byte without a UTF-16 byte-order mark)."""
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return data.decode('utf-16', errors='replace')
    if b'\0' in data:
        return None
    return data.decode('utf-8', errors='replace')


def find(text, review=False):
    """The first host path in a string, as a match object, or None."""
    return (REVIEW if review else SHIPPED).search(text)


def in_file_bytes(data, review=True):
    """The first host path in a file's bytes (None for a binary file); review mode by default."""
    text = text_of(data)
    return None if text is None else find(text, review)
