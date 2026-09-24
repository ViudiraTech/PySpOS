"""PySpOS 设计 token 对比度校验（WCAG 2.2 AA）

按主题分别解析 tokens.css：暗色取 `:root, body:not(.light-theme)` 块，
亮色取 `body.light-theme` 块。正确处理 var() 链与 rgb(... / alpha)：
半透明色要先与底色合成再算对比度，否则虚高。
"""
import re
import sys

# ---------- 色彩工具 ----------

def _srgb(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb):
    return sum(k * _srgb(v) for k, v in zip((0.2126, 0.7152, 0.0722), rgb))


def parse_color(val):
    """返回 (r,g,b,a)，支持 #hex 与 rgb()/rgba() 空格语法。"""
    val = val.strip()
    m = re.fullmatch(r'#([0-9a-fA-F]{3,8})', val)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) == 6:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (1.0,)
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4, 6)) + (1.0,)
    m = re.fullmatch(r'rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)'
                     r'(?:[,/\s]+([\d.%]+))?\s*\)', val)
    if m:
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a = m.group(4)
        alpha = 1.0
        if a:
            alpha = float(a[:-1]) / 100 if a.endswith('%') else float(a)
        return (r, g, b, alpha)
    return None


def composite(fg, bg):
    """把半透明前景合成到底色上。"""
    r, g, b, a = fg
    br, bg_, bb, _ = bg
    return (r * a + br * (1 - a), g * a + bg_ * (1 - a), b * a + bb * (1 - a), 1.0)


def ratio(c1, c2):
    l1, l2 = lum(c1[:3]), lum(c2[:3])
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ---------- token 解析（按主题分块）----------

def split_blocks(css):
    """切出原始层、暗色语义块、亮色语义块、组件层四段 token 表。

    两个必须遵守的点，都是踩过坑的：

    1. `pat` 里绝不能再带 `\\{`——下面统一由本函数拼 `\\s*\\{`，
       否则会要求两个左花括号，匹配永远失败（静默返回空块）。
    2. 同一选择器可能出现多次（为某个 token 单独补覆盖块）。
       一律取 **token 数最多** 的那个。取「第一个」会在有人新增小覆盖块
       时静默解析到错的块——真的踩过：亮色块被误认成只含 --ps-bg-scrim
       的小块，于是所有亮色对比度报 n/a 还看不出原因。
    """
    def blocks(pat):
        # pat 只给选择器，不带花括号
        return [m.group(1) for m in
                re.finditer(pat + r'\s*\{(.*?)\n\}', css, re.S)]

    def count(b):
        return len(re.findall(r'--ps-[a-z0-9-]+\s*:', b))

    def biggest(bl):
        return max(bl, key=count, default='')

    # 原始层：含 --ps-ref- 的那个 :root 块
    roots = blocks(r':root')
    prim = max((b for b in roots if '--ps-ref-' in b), key=count, default='')
    # 组件层：含 --ps-card- 的那个 :root 块
    comp = max((b for b in roots if '--ps-card-' in b), key=count, default='')
    # 语义层
    dark = biggest(blocks(r':root,\s*\nbody:not\(\.light-theme\)'))
    light = biggest(blocks(r'body\.light-theme'))
    return prim, dark, light, comp


def make_resolver(prim, dark, light, comp, theme):
    table = {}
    for blob in (prim, comp):
        for k, v in re.findall(r'(--ps-[a-z0-9-]+)\s*:\s*([^;]+);', blob):
            table[k] = v.strip()
    src = dark if theme == 'dark' else light
    for k, v in re.findall(r'(--ps-[a-z0-9-]+)\s*:\s*([^;]+);', src):
        table[k] = v.strip()

    def resolve(name, seen=()):
        if name in seen or len(seen) > 20:
            return None
        raw = table.get(name)
        if raw is None:
            return None
        c = parse_color(raw)
        if c:
            return c
        m = re.search(r'var\(\s*(--ps-[a-z0-9-]+)', raw)
        if m:
            return resolve(m.group(1), seen + (name,))
        return None

    return resolve, table


def main():
    css = open('docs/css/tokens.css', encoding='utf-8').read()
    prim, dark, light, comp = split_blocks(css)
    rd, td = make_resolver(prim, dark, light, comp, 'dark')
    rl, tl = make_resolver(prim, dark, light, comp, 'light')

    unres = sorted(set(td) - set(tl)) if set(td) != set(tl) else []
    if unres:
        print(f"提示：暗色块独有 token {unres}")

    page = {'dark': rd('--ps-bg-page'), 'light': rl('--ps-bg-page')}
    surf = {'dark': rd('--ps-bg-surface'), 'light': rl('--ps-bg-surface')}

    rows = [
        ('正文 fg-default / 页面底',  '--ps-fg-default',  'page', 4.5),
        ('次要 fg-muted / 页面底',    '--ps-fg-muted',    'page', 4.5),
        ('弱化 fg-subtle / 页面底',   '--ps-fg-subtle',   'page', 4.5),
        ('标题 fg-strong / 页面底',   '--ps-fg-strong',   'page', 4.5),
        ('正文 / 卡片面',            '--ps-fg-default',  'surf', 4.5),
        ('次要 / 卡片面',            '--ps-fg-muted',    'surf', 4.5),
        ('弱化 / 卡片面',            '--ps-fg-subtle',   'surf', 4.5),
        ('品牌 brand / 页面底',       '--ps-brand',       'page', 4.5),
        ('描边 border-default / 页面底', '--ps-border-default', 'page', 3.0),
        ('描边 border-brand / 页面底',   '--ps-border-brand',   'page', 3.0),
    ]
    print(f"{'检查项':34} {'暗色':>10} {'亮色':>10}  判定")
    print('-' * 70)
    bad = []
    for label, tok, base, need in rows:
        vals = {}
        for th, res, bgs in (('dark', rd, page), ('light', rl, page)):
            fg = res(tok)
            vals[th] = ratio(fg, bgs[th]) if fg else None
        # 卡片面单独再算一次
        if base == 'surf':
            for th, res, bgs in (('dark', rd, surf), ('light', rl, surf)):
                fg = res(tok)
                vals[th] = ratio(fg, bgs[th]) if fg else None
        ok = all(v is not None and v >= need for v in vals.values())
        cells = '  '.join(f'{vals[t]:6.2f}:1' if vals[t] else '     n/a' for t in ('dark', 'light'))
        print(f"{label:34} {cells}  {'OK' if ok else 'FAIL'}")
        if not ok:
            bad.append(label)

    print('\n状态色（前景叠在自己的底色上）:')
    for name in ('success', 'warning', 'danger', 'info', 'neutral'):
        line = f'  {name:8}'
        okall = True
        for th, res, bgs in (('dark', rd, surf), ('light', rl, surf)):
            fg = res(f'--ps-status-{name}-fg')
            bg = res(f'--ps-status-{name}-bg')
            if not fg or not bg:
                line += f'  {th}:n/a'
                okall = False
                continue
            r = ratio(composite(fg, bg), composite(bg, bgs[th]))
            line += f'  {th} {r:5.2f}:1'
            if r < 4.5:
                okall = False
        print(line + ('  OK' if okall else '  FAIL'))
        if not okall:
            bad.append('status-' + name)

    # 停用卡片：必须实测**变体后**的对比度，而不是只测 token 对 token。
    # 2026-09-24 的教训：曾经给 .ps-card--retired 加 opacity: 0.62 来表达
    # 「不活跃」，视觉上到位了，但 opacity 连带把正文冲淡，对比度跌破 AA。
    # 只测 token 的话完全看不出来——必须把变体效果算进去。
    print('\n停用卡片变体（.ps-card--retired）:')
    retired_ok = True
    for th, res, bgs in (('dark', rd, page), ('light', rl, page)):
        for tok, label in (('--ps-card-body-color', '正文'),
                           ('--ps-card-meta-color', '元信息'),
                           ('--ps-fg-subtle', '副标题/元信息')):
            fg = res(tok)
            if not fg:
                print(f'  {th} {label:14} n/a')
                retired_ok = False
                continue
            # 停用态不再有 opacity，正文与常规态同对比度
            r = ratio(fg, res('--ps-card-bg') or bgs[th])
            # --ps-card-bg 可能是 color-mix，解析不出来时退回卡片面
            if res('--ps-card-bg') is None:
                r = ratio(fg, bgs[th])
            ok = r >= 4.5
            if not ok:
                retired_ok = False
            print(f"  {th:5} {label:14} {r:6.2f}:1  {'OK' if ok else 'FAIL (需 4.5)'}")
    if not retired_ok:
        bad.append('retired-card')
    else:
        print('  停用态未对文字施加 opacity，正文对比度与常规态一致')

    print('\n结论:', '全部达标（WCAG AA）' if not bad else f'{len(bad)} 项不达标: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
