'''
 *
 *      check_tokens_contrast.py
 *      WCAG 2.2 AA contrast check for the docs design tokens, resolved once per theme.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import re
import sys

# ---------- colour helpers ----------

# One sRGB channel to linear light, as WCAG defines it.
def _srgb(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# Relative luminance of an RGB triple, using the WCAG 2.2 weights.
def lum(rgb):
    return sum(k * _srgb(v) for k, v in zip((0.2126, 0.7152, 0.0722), rgb))


# Return (r,g,b,a) for a #hex or an rgb()/rgba() value in comma or space syntax.
# A value that is not a colour at all returns None, so one malformed declaration
# is reported as unresolved instead of raising out of the whole check.
def parse_color(val):
    val = val.strip()
    m = re.fullmatch(r'#([0-9a-fA-F]{3,8})', val)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = ''.join(c * 2 for c in h)
        if len(h) == 6:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (1.0,)
        if len(h) == 8:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4, 6)) + (1.0,)
        # 5 and 7 digits are not a colour: reject them like any other bad value
        return None
    m = re.fullmatch(r'rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)'
                      r'(?:[,/\s]+([\d.%]+))?\s*\)', val)
    if m:
        try:
            r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        except ValueError:
            return None
        a = m.group(4)
        alpha = 1.0
        if a:
            try:
                alpha = float(a[:-1]) / 100 if a.endswith('%') else float(a)
            except ValueError:
                return None
        return (r, g, b, alpha)
    return None


# Flatten a translucent foreground onto its background.
def composite(fg, bg):
    r, g, b, a = fg
    br, bg_, bb, _ = bg
    return (r * a + br * (1 - a), g * a + bg_ * (1 - a), b * a + bb * (1 - a), 1.0)


# WCAG contrast ratio of two colours, ignoring their alpha.
def ratio(c1, c2):
    l1, l2 = lum(c1[:3]), lum(c2[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ---------- token parsing, split by theme ----------

PREFIX = r'--pg-[a-z0-9-]+'


# Cut out the primitive, light and dark token blocks; where a selector repeats, keep the one with the most tokens.
def split_blocks(css):

# Return the body of every block whose selector matches pat.
    def blocks(pat):
        # pat is the selector alone, without the braces
        return [m.group(1) for m in
                re.finditer(pat + r'\s*\{(.*?)\n\}', css, re.S)]

# Count the token declarations in one block body.
    def count(b):
        return len(re.findall(PREFIX + r'\s*:', b))

# Pick the block with the most token declarations, or an empty string if there is none.
    def biggest(bl):
        return max(bl, key=count, default='')

    # primitive layer: the :root block holding --pg-ref- (literal values, no var())
    roots = blocks(r':root')
    prim = max((b for b in roots if '--pg-ref-' in b), key=count, default='')
    # semantic layer: the default block is light, the override block is dark
    light = biggest(blocks(r':root,\s*\nbody:not\(\.theme-dark\)'))
    dark = biggest(blocks(r'body\.theme-dark'))
    return prim, dark, light


# Build a var()-chasing resolver over one theme's token table, returning it with the raw table.
def make_resolver(prim, dark, light, theme):
    table = {}
    for k, v in re.findall(r'(' + PREFIX + r')\s*:\s*([^;]+);', prim):
        table[k] = v.strip()
    src = dark if theme == 'dark' else light
    for k, v in re.findall(r'(' + PREFIX + r')\s*:\s*([^;]+);', src):
        table[k] = v.strip()

# Resolve one token to a colour by following var() links, giving up on cycles.
    def resolve(name, seen=()):
        if name in seen or len(seen) > 20:
            return None
        raw = table.get(name)
        if raw is None:
            return None
        c = parse_color(raw)
        if c:
            return c
        m = re.search(r'var\(\s*(' + PREFIX + r')', raw)
        if m:
            return resolve(m.group(1), seen + (name,))
        return None

    return resolve, table


# Measure every token pair that has a contrast floor and return 1 if any falls short.
def main():
    with open('docs/css/tokens.css', encoding='utf-8') as stream:
        css = stream.read()
    prim, dark, light = split_blocks(css)
    rd, td = make_resolver(prim, dark, light, 'dark')
    rl, tl = make_resolver(prim, dark, light, 'light')

    unres = sorted(set(td) - set(tl)) if set(td) != set(tl) else []
    if unres:
        print(f"提示：暗色块独有 token {unres}")

    base = {
        'page': {'dark': rd('--pg-bg-page'), 'light': rl('--pg-bg-page')},
        'raised': {'dark': rd('--pg-bg-raised'), 'light': rl('--pg-bg-raised')},
        'sunk': {'dark': rd('--pg-bg-sunken'), 'light': rl('--pg-bg-sunken')},
        'band': {'dark': rd('--pg-band-bg'), 'light': rl('--pg-band-bg')},
        'term': {'dark': rd('--pg-term-bg'), 'light': rl('--pg-term-bg')},
    }

    rows = [
        ('正文 fg-1 / 页面底', '--pg-fg-1', 'page', 4.5),
        ('次要 fg-2 / 页面底', '--pg-fg-2', 'page', 4.5),
        ('弱化 fg-3 / 页面底', '--pg-fg-3', 'page', 4.5),
        ('链接 accent / 页面底', '--pg-accent', 'page', 4.5),
        ('正文 / 凸起面', '--pg-fg-1', 'raised', 4.5),
        ('次要 / 凸起面', '--pg-fg-2', 'raised', 4.5),
        ('次要 / 下沉面', '--pg-fg-2', 'sunk', 4.5),
        # line-1/line-2 are purely decorative separators (WCAG 1.4.11 exempts decoration);
        # control borders use --pg-line-strong instead, which is what is measured here.
        ('控件边界 strong / 页面底', '--pg-line-strong', 'page', 3.0),
        ('反白带文字 / 带底', '--pg-band-fg', 'band', 4.5),
        ('反白带次要 / 带底', '--pg-band-mute', 'band', 4.5),
        ('终端正文 / 终端底', '--pg-term-fg', 'term', 4.5),
        ('终端弱化 / 终端底', '--pg-term-dim', 'term', 4.5),
        ('终端提示绿 / 终端底', '--pg-term-green', 'term', 3.0),
    ]
    print(f"{'检查项':28} {'暗色':>10} {'亮色':>10}  判定")
    print('-' * 70)
    bad = []
    for label, tok, surf, need in rows:
        vals = {}
        for th, res in (('dark', rd), ('light', rl)):
            fg = res(tok)
            bg = base[surf][th]
            vals[th] = ratio(fg, bg) if fg and bg else None
        ok = all(v is not None and v >= need for v in vals.values())
        cells = '  '.join(f'{vals[t]:6.2f}:1' if vals[t] else '     n/a' for t in ('dark', 'light'))
        print(f"{label:28} {cells}  {'OK' if ok else 'FAIL'}")
        if not ok:
            bad.append(label)

    print('\n状态色（前景叠在自己的底色上，再叠到凸起面）:')
    for name in ('ok', 'warn', 'bad', 'mute'):
        line = f'  {name:8}'
        okall = True
        for th, res in (('dark', rd), ('light', rl)):
            fg = res(f'--pg-{name}-fg')
            bg = res(f'--pg-{name}-bg')
            if not fg or not bg:
                line += f'  {th}:n/a'
                okall = False
                continue
            r = ratio(composite(fg, bg), composite(bg, base["raised"][th]))
            line += f'  {th} {r:5.2f}:1'
            if r < 4.5:
                okall = False
        print(line + ('  OK' if okall else '  FAIL'))
        if not okall:
            bad.append('status-' + name)

    print('\n结论:', '全部达标（WCAG AA）' if not bad else f'{len(bad)} 项不达标: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
