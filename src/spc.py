'''
 *
 *      spc.py
 *      SpaceConfig reading and writing with type checking and escaping.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import os
import re

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}
_NULL = {"null", "none", "nil", "~"}

_ESCAPES = {'\\': '\\', '"': '"', "'": "'", 'n': '\n', 't': '\t', 'r': '\r'}
_ESCAPE_RE = re.compile(r'\\(.)', re.DOTALL)


# Expand backslash escapes inside a quoted value.
def _unescape(s: str) -> str:
    # Rewrite one escape match; an unknown escape is kept as written.
    def _rep(m):
        ch = m.group(1)
        return _ESCAPES.get(ch, '\\' + ch)
    return _ESCAPE_RE.sub(_rep, s)


# Escape backslash, quote, newline, tab and carriage return for writing a quoted value.
def _escape(s: str) -> str:
    return (s.replace('\\', '\\\\').replace('"', '\\"')
             .replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r'))


# Cut a trailing comment: quote aware, and '#' or ';' only start one outside quotes and after whitespace.
def _strip_inline_comment(line: str) -> str:
    quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch in ('#', ';') and (i == 0 or line[i - 1] in (' ', '\t')):
            return line[:i]
        i += 1
    return line


# Split on top-level commas, quote and bracket aware, with one level of nesting.
def _split_list(inner: str) -> List[str]:
    parts, cur, quote, depth = [], '', None, 0
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            cur += ch
            if ch == '\\' and i + 1 < len(inner):
                cur += inner[i + 1]
                i += 1
            elif ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            cur += ch
        elif ch == '[':
            depth += 1
            cur += ch
        elif ch == ']':
            depth -= 1
            cur += ch
        elif ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
        i += 1
    if cur.strip() or parts:
        parts.append(cur.strip())
    return [p for p in parts if p != '']


# Parse one value; the public entry point reused by spc_set and friends.
def parse_value(raw: str) -> Any:
    s = raw.strip()
    if s == '':
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return _unescape(s[1:-1])
    if s.startswith('[') and s.endswith(']'):
        return [parse_value(p) for p in _split_list(s[1:-1])]
    low = s.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    if low in _NULL:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# The old internal name is kept so existing imports still work
_parse_value = parse_value


# Report whether a string has to be written quoted to survive a round trip.
def _needs_quote(s: str) -> bool:
    if s == '':
        return True
    return any(c in s for c in ' #;="\'[]\n\t\r')


# Serialise one value; the public entry point.
def format_value(v: Any) -> str:
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(format_value(e) for e in v) + ']'
    s = str(v)
    if _needs_quote(s):
        return '"' + _escape(s) + '"'
    return s


_format_value = format_value


# Parse spc text; with_meta=True also returns meta[(section, key)] = line
# number, so schema errors can point at a line.
def loads(text: str, with_meta: bool = False):
    data: Dict[str, Dict[str, Any]] = {}
    meta: Dict[Tuple[str, str], int] = {}
    section = 'default'
    data[section] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        s = _strip_inline_comment(line).strip()
        if not s:
            continue
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].strip() or 'default'
            data.setdefault(section, {})
            continue
        if '=' not in s:
            raise SyntaxError(f"spc 第 {lineno} 行缺少 '=': {line!r}")
        k, v = s.split('=', 1)
        k = k.strip()
        data[section][k] = parse_value(v)
        meta[(section, k)] = lineno
    if with_meta:
        return data, meta
    return data


# Serialise a section dict back to spc text, behind a generated-by banner.
def dumps(data: Dict[str, Dict[str, Any]]) -> str:
    lines = ['# SpaceConfig generated by PySpOS spc.py']
    for section, kv in data.items():
        lines.append(f'[{section}]')
        for k, v in kv.items():
            lines.append(f'{k} = {format_value(v)}')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


# Read an spc file and parse it.
def load(path: str, with_meta: bool = False):
    with open(path, 'r', encoding='utf-8') as f:
        return loads(f.read(), with_meta=with_meta)


# Write a section dict to an spc file, creating the parent directory if needed.
def dump(data: Dict[str, Dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(dumps(data))


# Wrap a bootcfg dict as an spc 'boot' section, dropping the checksum.
def bootcfg_to_spc(bootcfg: dict) -> Dict[str, Dict[str, Any]]:
    return {'boot': {k: v for k, v in bootcfg.items() if k != 'checksum'}}


# Flatten the 'boot' and 'default' sections into a bootcfg dict; 'default' is applied last and wins.
def spc_to_bootcfg(data: Dict[str, Dict[str, Any]]) -> dict:
    merged: dict = {}
    for section in ('boot', 'default'):
        merged.update(data.get(section, {}))
    return merged


# --------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------

# One schema problem found in a parsed file: severity, location and a code.
@dataclass
class ValidationIssue:
    level: str      # 'error' | 'warning'
    section: str
    key: str
    lineno: int     # 0 means the line number is unknown
    message: str
    code: str       # MISSING_REQUIRED / TYPE_MISMATCH / NOT_IN_CHOICES /
                    # OUT_OF_RANGE / UNKNOWN_KEY / UNKNOWN_SECTION


# Raised by ensure_valid, carrying every error-level issue in .issues.
class SPCSchemaError(Exception):
# Build the message text from the error-level issues only.
    def __init__(self, issues: List[ValidationIssue]):
        self.issues = issues
        super().__init__('; '.join(
            f"[{i.section}.{i.key}@{i.lineno or '?'}] {i.message}"
            for i in issues if i.level == 'error'))


_TYPE_ALIASES = {
    'str': ('str',), 'string': ('str',),
    'int': ('int',), 'integer': ('int',),
    'float': ('float',), 'number': ('int', 'float'),
    'bool': ('bool',), 'boolean': ('bool',),
    'list': ('list',),
    'none': ('none',), 'null': ('none',),
    'any': ('any',),
}


# Report whether a value satisfies a schema type name, after alias expansion.
def _type_ok(v: Any, t: str) -> bool:
    t = _TYPE_ALIASES.get(str(t).lower(), ('any',))[0]
    if t == 'any':
        return True
    if t == 'bool':
        return type(v) is bool
    if t == 'int':
        return type(v) is int
    if t == 'float':
        return type(v) in (int, float) and type(v) is not bool
    if t == 'str':
        return isinstance(v, str)
    if t == 'list':
        return isinstance(v, (list, tuple))
    if t == 'none':
        return v is None
    return True


# Return the schema-facing name of a value's type, for error messages.
def _type_name(v: Any) -> str:
    if v is None:
        return 'null'
    if type(v) is bool:
        return 'bool'
    if type(v) is int:
        return 'int'
    if type(v) is float:
        return 'float'
    if isinstance(v, str):
        return 'str'
    if isinstance(v, (list, tuple)):
        return 'list'
    return type(v).__name__


# Check a rule's min and max, measuring strings and lists by length.
# Values that are neither numbers nor sized are accepted.
def _in_range(v: Any, rule: dict) -> bool:
    lo, hi = rule.get('min'), rule.get('max')
    if lo is None and hi is None:
        return True
    cmp_v = len(v) if isinstance(v, (str, list, tuple)) else v
    if not isinstance(cmp_v, (int, float)):
        return True
    if lo is not None and cmp_v < lo:
        return False
    if hi is not None and cmp_v > hi:
        return False
    return True


# Validate against a schema: missing, mistyped and out-of-range values are
# errors, while unknown keys and sections only warn so unknown data never
# breaks the chain. Rules take type, required, min, max, default, choices;
# __allow_unknown__ at top or per section gates the warnings.
def validate(data: Dict[str, Dict[str, Any]], schema: dict,
             meta: Optional[Dict[Tuple[str, str], int]] = None) -> List[ValidationIssue]:
    meta = meta or {}
    issues: List[ValidationIssue] = []
    sections = {k: v for k, v in schema.items() if not k.startswith('__')}
    top_allow_unknown = bool(schema.get('__allow_unknown__', False))

# Return the recorded line number for a key, or 0 when it is unknown.
    def _line(sec, key):
        return meta.get((sec, key), 0)

    for sec, kv in data.items():
        rules = sections.get(sec)
        if rules is None:
            # An empty section is usually a parser artefact, such as the ever-empty default, so stay quiet about it
            if kv:
                if not top_allow_unknown:
                    issues.append(ValidationIssue(
                        'warning', sec, '', 0,
                        f"未知分节 [{sec}]（schema 未声明，已忽略）", 'UNKNOWN_SECTION'))
            continue
        allow_unknown = bool(rules.get('__allow_unknown__', False))
        key_rules = {k: v for k, v in rules.items() if not k.startswith('__')}
        for key, rule in key_rules.items():
            if rule.get('required') and key not in kv:
                issues.append(ValidationIssue(
                    'error', sec, key, 0,
                    f"缺少必填项 '{key}'"
                    + (f"（{rule.get('description')}）" if rule.get('description') else ''),
                    'MISSING_REQUIRED'))
        for key, v in kv.items():
            rule = key_rules.get(key)
            if rule is None:
                if not allow_unknown:
                    issues.append(ValidationIssue(
                        'warning', sec, key, _line(sec, key),
                        f"未知配置项 '{key}'（schema 未声明，已忽略）", 'UNKNOWN_KEY'))
                continue
            types = rule.get('type', 'any')
            if isinstance(types, str):
                types = [types]
            if not any(_type_ok(v, t) for t in types):
                issues.append(ValidationIssue(
                    'error', sec, key, _line(sec, key),
                    f"'{key}' 类型应为 {'/'.join(types)}，实际为 {_type_name(v)}",
                    'TYPE_MISMATCH'))
                continue
            if 'choices' in rule and v not in rule['choices']:
                issues.append(ValidationIssue(
                    'error', sec, key, _line(sec, key),
                    f"'{key}' 取值 {v!r} 不在允许范围 {rule['choices']} 内",
                    'NOT_IN_CHOICES'))
            elif not _in_range(v, rule):
                issues.append(ValidationIssue(
                    'error', sec, key, _line(sec, key),
                    f"'{key}' 超出范围（min={rule.get('min')} max={rule.get('max')}）",
                    'OUT_OF_RANGE'))
    return issues


# Raise SPCSchemaError when validation produced any error-level issue.
def ensure_valid(data, schema, meta=None) -> None:
    errors = [i for i in validate(data, schema, meta) if i.level == 'error']
    if errors:
        raise SPCSchemaError(errors)


# Return a copy of data with every schema 'default' for an absent key filled in.
def apply_defaults(data: Dict[str, Dict[str, Any]], schema: dict) -> Dict[str, Dict[str, Any]]:
    out = {sec: dict(kv) for sec, kv in data.items()}
    for sec, rules in schema.items():
        if sec.startswith('__') or not isinstance(rules, dict):
            continue
        target = out.setdefault(sec, {})
        for key, rule in rules.items():
            if key.startswith('__') or not isinstance(rule, dict):
                continue
            if key not in target and 'default' in rule:
                target[key] = rule['default']
    return out


# Preset schema for the boot section, the default for spc_validate and the migration tools
BOOTCFG_SCHEMA = {
    'boot': {
        'locked': {'type': 'bool', 'required': True, 'description': 'Bootloader 上锁状态'},
        'rootstate': {'type': 'bool', 'required': True, 'description': 'ROOT 持久化状态'},
    }
}
