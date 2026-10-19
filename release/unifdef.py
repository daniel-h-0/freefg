# SPDX-License-Identifier: MIT
"""Resolve the preprocessor conditionals of a C source on a fixed set of macros, as unifdef does (a small subset of it).

release/export_tree.py --public uses it to publish the C sources in the one configuration the public tree builds. A
conditional whose condition the given macros decide is replaced by the branch it selects, and its directives are
removed; a conditional they do not decide is kept as it is, and its branches are processed in turn. Every other line
is kept byte for byte, comments and line breaks included, so in the configuration the macros describe the compiler
reads the same tokens as from the original file.

  defined     {name: value} of the macros the build defines
  undefined   names the build never defines (#if NAME is then 0, as in C)
  protected   strings that must survive: a conditional is kept whole when removing one of its branches would remove one

Conditions may use defined(NAME), defined NAME, NAME, integer literals, the unary operators ! ~ - +, the binary
arithmetic, shift, comparison, bitwise and logical operators, and parentheses. A condition that mentions a given macro
but that the given macros do not decide is refused (a partial simplification would be needed), and so is an #elif chain
that mentions one. A directive line that opens a comment it does not close is refused when it would be removed.
"""
import re


class UnifdefError(Exception):
    """The source cannot be resolved safely; the message names the line."""


DIRECTIVE = re.compile(r'^[ \t]*#[ \t]*([A-Za-z_]+)\b(.*)$', re.S)
CONDITIONALS = ('if', 'ifdef', 'ifndef', 'elif', 'else', 'endif')
UNKNOWN = None


# ------------------------------------------------------------------------------------------------------------- scanning

def scan(line, in_comment):
    """(code of one physical line with comments and literals blanked, whether a block comment is open at its end)."""
    out, i, n = [], 0, len(line)
    while i < n:
        if in_comment:
            end = line.find('*/', i)
            if end < 0:
                return ''.join(out), True
            i, in_comment = end + 2, False
            out.append(' ')
        elif line.startswith('/*', i):
            in_comment, i = True, i + 2
        elif line.startswith('//', i):
            break
        elif line[i] in '"\'':
            quote, j = line[i], i + 1
            while j < n and line[j] != quote:
                j += 2 if line[j] == '\\' else 1
            out.append(quote * 2)
            i = j + 1
        else:
            out.append(line[i])
            i += 1
    return ''.join(out), in_comment


def has_code(text):
    """Whether text holds anything but comments and white space."""
    in_comment = False
    for line in text.splitlines():
        code, in_comment = scan(line, in_comment)
        if code.strip():
            return True
    return False


# ----------------------------------------------------------------------------------------------------------- parsing

class Group:
    """One #if…#endif: branches [(directive lines, kind, condition text, items)], each item a list of lines or a Group."""

    def __init__(self, lines, kind, condition, number):
        self.branches = [(lines, kind, condition, [])]
        self.endif = None
        self.number = number

    def raw(self):
        out = []
        for lines, _kind, _condition, items in self.branches:
            out += lines
            out += flatten(items)
        return out + (self.endif or [])


def flatten(items):
    out = []
    for item in items:
        out += item.raw() if isinstance(item, Group) else item
    return out


def parse(text, name='source'):
    """The items of a source: runs of lines (with their line ends) and Groups."""
    lines = text.splitlines(keepends=True)
    root, stack, i, in_comment = [], [], 0, False
    current = root
    while i < len(lines):
        number, start_comment = i + 1, in_comment
        physical = [lines[i]]
        code, in_comment = scan(lines[i], in_comment)
        match = None if start_comment else DIRECTIVE.match(code)
        if match:
            while physical[-1].rstrip('\r\n').endswith('\\') and i + 1 < len(lines):
                i += 1
                physical.append(lines[i])
                more, in_comment = scan(lines[i], in_comment)
                code = code.rstrip('\r\n')[:-1] + ' ' + more
            match = DIRECTIVE.match(code)
        i += 1
        word = match.group(1) if match else None
        if word not in CONDITIONALS:
            if current and not isinstance(current[-1], Group):
                current[-1] += physical
            else:
                current.append(list(physical))
            continue
        condition = match.group(2).strip()
        if in_comment:
            condition += ' /*'  # the directive opens a comment it does not close: never resolved (see resolve)
        if word in ('if', 'ifdef', 'ifndef'):
            group = Group(physical, word, condition, number)
            current.append(group)
            stack.append(group)
            current = group.branches[0][3]
        elif not stack:
            raise UnifdefError(f'{name}:{number}: #{word} without #if')
        elif word in ('elif', 'else'):
            group = stack[-1]
            if group.branches[-1][1] == 'else':
                raise UnifdefError(f'{name}:{number}: #{word} after #else')
            group.branches.append((physical, word, condition, []))
            current = group.branches[-1][3]
        else:
            stack.pop().endif = physical
            current = stack[-1].branches[-1][3] if stack else root
    if stack:
        raise UnifdefError(f'{name}:{stack[-1].number}: #if without #endif')
    return root


# ----------------------------------------------------------------------------------------------------------- conditions

TOKEN = re.compile(r'\s*(?:(0[xX][0-9a-fA-F]+|\d+)[uUlL]*|([A-Za-z_]\w*)|(&&|\|\||==|!=|<=|>=|<<|>>|[!~()+\-*/%<>&|^?:,]))')
BINARY = [('||',), ('&&',), ('|',), ('^',), ('&',), ('==', '!='), ('<', '>', '<=', '>='), ('<<', '>>'), ('+', '-'),
          ('*', '/', '%')]


def tokens(text):
    out, at = [], 0
    text = text.rstrip()
    while at < len(text):
        match = TOKEN.match(text, at)
        if not match:
            raise ValueError(f'cannot read {text[at:]!r}')
        number, name, operator = match.groups()
        out.append(('num', int(number, 0)) if number else ('name', name) if name else ('op', operator))
        at = match.end()
    return out


class Evaluator:
    """Three-valued evaluation of a condition: an int, or UNKNOWN when it depends on a macro that is not given."""

    def __init__(self, defined, undefined):
        self.defined, self.undefined = defined, undefined

    def evaluate(self, kind, condition):
        if kind in ('ifdef', 'ifndef'):
            name = condition.split()[0] if condition.split() else ''
            if not re.fullmatch(r'[A-Za-z_]\w*', name):
                raise ValueError(f'#{kind} needs a macro name')
            value = self.is_defined(name)
            return value if value is UNKNOWN or kind == 'ifdef' else int(not value)
        self.items, self.at = tokens(condition), 0
        value = self.binary(0)
        if self.at != len(self.items):
            raise ValueError('unexpected text after the condition')
        return value

    def mentions(self, kind, condition):
        names = {condition.split()[0]} if kind in ('ifdef', 'ifndef') and condition.split() else \
            set(re.findall(r'[A-Za-z_]\w*', condition))
        return names & (set(self.defined) | set(self.undefined))

    def is_defined(self, name):
        return 1 if name in self.defined else 0 if name in self.undefined else UNKNOWN

    def peek(self):
        return self.items[self.at] if self.at < len(self.items) else (None, None)

    def take(self, value=None):
        item = self.peek()
        if item[0] is None or (value is not None and item[1] != value):
            raise ValueError(f'expected {value or "a value"}')
        self.at += 1
        return item

    def binary(self, level):
        if level == len(BINARY):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == 'op' and self.peek()[1] in BINARY[level]:
            operator = self.take()[1]
            left = combine(operator, left, self.binary(level + 1))
        if level == 0 and self.peek() == ('op', '?'):
            self.take('?')
            yes = self.binary(0)
            self.take(':')
            no = self.binary(0)
            left = UNKNOWN if left is UNKNOWN else yes if left else no
        return left

    def unary(self):
        kind, value = self.take()
        if kind == 'num':
            return value
        if kind == 'name':
            if value == 'defined':
                parenthesised = self.peek() == ('op', '(')
                if parenthesised:
                    self.take('(')
                kind, name = self.take()
                if kind != 'name':
                    raise ValueError('defined needs a macro name')
                if parenthesised:
                    self.take(')')
                return self.is_defined(name)
            if self.peek() == ('op', '('):  # a function-like macro: depends on what defines it
                depth = 0
                while True:
                    item = self.take()
                    depth += item == ('op', '(')
                    depth -= item == ('op', ')')
                    if not depth:
                        return UNKNOWN
            return self.defined[value] if value in self.defined else 0 if value in self.undefined else UNKNOWN
        if value == '(':
            inner = self.binary(0)
            self.take(')')
            return inner
        operand = self.unary()
        if operand is UNKNOWN:
            return UNKNOWN
        return {'!': int(not operand), '~': ~operand, '-': -operand, '+': operand}[value]


def combine(operator, left, right):
    if operator == '&&':
        return 0 if left == 0 or right == 0 else UNKNOWN if UNKNOWN in (left, right) else 1
    if operator == '||':
        known_true = (left is not UNKNOWN and left != 0) or (right is not UNKNOWN and right != 0)
        return 1 if known_true else UNKNOWN if UNKNOWN in (left, right) else 0
    if UNKNOWN in (left, right):
        return UNKNOWN
    if operator in ('/', '%') and right == 0:
        raise ValueError('division by zero')
    return int({'|': left | right, '^': left ^ right, '&': left & right, '==': left == right, '!=': left != right,
                '<': left < right, '>': left > right, '<=': left <= right, '>=': left >= right, '<<': left << right,
                '>>': left >> right, '+': left + right, '-': left - right, '*': left * right,
                '/': int(left / right), '%': left - right * int(left / right)}[operator])


# ---------------------------------------------------------------------------------------------------------- resolution

class Result:
    def __init__(self, text):
        self.text = text
        self.resolved = 0   # conditionals removed
        self.kept = 0       # conditionals kept as they are (not decided by the given macros)
        self.protected = []  # line numbers of conditionals kept whole for a protected string


def unifdef(text, defined, undefined, protected=(), name='source'):
    """The source with every conditional the given macros decide resolved (see the module documentation)."""
    overlap = set(defined) & set(undefined)
    if overlap:
        raise UnifdefError(f'macros both defined and undefined: {sorted(overlap)}')
    evaluator = Evaluator(dict(defined), set(undefined))
    result = Result('')
    out = []

    def condition_of(group, index):
        lines, kind, condition, _items = group.branches[index]
        where = f'{name}:{group.number}'
        try:
            mentioned = evaluator.mentions(kind, condition)
            value = evaluator.evaluate(kind, condition.replace(' /*', '')) if mentioned else UNKNOWN
        except ValueError as error:
            if mentioned:
                raise UnifdefError(f'{where}: cannot evaluate #{kind} {condition}: {error}') from None
            value = UNKNOWN
        if mentioned and value is UNKNOWN:
            raise UnifdefError(f'{where}: #{kind} {condition} mentions {sorted(mentioned)} but the given macros do not '
                               'decide it (it would need a partial simplification)')
        if value is not UNKNOWN and condition.endswith(' /*'):
            raise UnifdefError(f'{where}: the directive to remove opens a comment that continues on the next line')
        return value

    def render(items):
        for item in items:
            if isinstance(item, Group):
                group(item)
            else:
                out.extend(item)

    def keep(item):
        result.kept += 1
        for lines, _kind, _condition, items in item.branches:
            out.extend(lines)
            render(items)
        out.extend(item.endif)

    def group(item):
        if len(item.branches) > 1 and item.branches[1][1] == 'elif' or \
                len(item.branches) > 2:
            values = [condition_of(item, i) for i, branch in enumerate(item.branches) if branch[1] != 'else']
            if any(v is not UNKNOWN for v in values):
                raise UnifdefError(f'{name}:{item.number}: an #elif chain that mentions a given macro is not supported')
            keep(item)
            return
        value = condition_of(item, 0)
        if value is UNKNOWN:
            keep(item)
            return
        taken = item.branches[0][3] if value else (item.branches[1][3] if len(item.branches) > 1 else [])
        dropped = item.branches[1][3] if value and len(item.branches) > 1 else [] if value else item.branches[0][3]
        dropped_text = ''.join(flatten(dropped))
        if any(s in dropped_text for s in protected):
            result.protected.append(item.number)
            keep(item)
            return
        result.resolved += 1
        render(taken)

    render(parse(text, name))
    result.text = ''.join(out)
    for string in protected:
        if text.count(string) != result.text.count(string):
            raise UnifdefError(f'{name}: protected text changed its count: {string[:60]!r}')
    return result


def remove_includes(text, headers):
    """text without its #include "<name>" lines (outside comments) for the given header names."""
    out, in_comment = [], False
    for line in text.splitlines(keepends=True):
        start = in_comment
        code, in_comment = scan(line, in_comment)
        match = None if start else re.match(r'^[ \t]*#[ \t]*include[ \t]*""', code)
        if match:
            target = re.match(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', line)
            if target and target.group(1).rsplit('/', 1)[-1] in headers:
                continue
        out.append(line)
    return ''.join(out)


def conditional_macros(text):
    """Names used in the conditions of a source's #if/#ifdef/#ifndef/#elif directives."""
    names = set()
    for item in walk(parse(text)):
        for _lines, kind, condition, _items in item.branches:
            if kind == 'ifdef' or kind == 'ifndef':
                names |= set(condition.split()[:1])
            elif kind in ('if', 'elif'):
                names |= set(re.findall(r'[A-Za-z_]\w*', condition.replace(' /*', ''))) - {'defined'}
    return names


def defined_macros(text):
    """Names a source #defines (outside comments)."""
    names, in_comment = set(), False
    for line in text.splitlines():
        start = in_comment
        code, in_comment = scan(line, in_comment)
        match = None if start else re.match(r'^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)', code)
        if match:
            names.add(match.group(1))
    return names


def walk(items):
    for item in items:
        if isinstance(item, Group):
            yield item
            for _lines, _kind, _condition, inner in item.branches:
                yield from walk(inner)


def mentions(text, names):
    """[(line number, name, in a comment)] of each occurrence of the names in text."""
    found, in_comment = [], False
    if not names:
        return found
    pattern = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, names))) + r')\b')
    for number, line in enumerate(text.splitlines(), 1):
        code, in_comment_next = scan(line, in_comment)
        for match in pattern.finditer(line):
            found.append((number, match.group(1), not pattern.search(code)))
        in_comment = in_comment_next
    return found
