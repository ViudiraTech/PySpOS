"""docs/ 设计层自检：token 契约 + 组件层纪律

三道检查，都是「机器能查就别靠眼睛」：

1. **对比度**（WCAG AA）：亮/暗两套语义 token 逐项实测，见
   check_tokens_contrast.py 的说明。
2. **组件层无硬编码**：cards.css 里不允许出现裸 hex / rgba / 裸 px。
   允许的只有 0、100%、fr、ch 等与主题无关的值。设计 token 存在的意义
   就是让「改一处、全站变」成立；组件里写死颜色等于把这个价值丢掉。
3. **token 引用完整**：css 里每个 var(--ps-*) 都必须在 tokens.css 里有定义。
   拼错一个 token 名不会报错，只会静默失效——这条就是抓那个的。
"""
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
TOKENS = DOCS / "css" / "tokens.css"
CARDS = DOCS / "css" / "cards.css"

# 与主题无关、允许出现的裸值
ALLOWED_BARE = {
    "0", "0%", "100%", "auto", "none", "inherit", "currentcolor",
    "transparent", "1", "1fr", "minmax", "var", "env",
}

# 确实需要 opacity/filter 的选择器白名单。每条都要写明「为什么文字不受影响」。
# 往这里加之前先跑 check_tokens_contrast.py 确认变体后的对比度仍达标。
ALLOWED_FILTER_SELECTORS = {
    # 纯装饰：顶部强调条，伪元素里只有背景色，没有任何文字
    '.ps-card::before',
    # WCAG 1.4.3 明确豁免「禁用控件」的前后景对比度要求。
    # 状态另有承载：aria-disabled + 文案「敬请期待」+ pointer-events: none。
    # 两条选择器共用一条声明，组合选择器会按逗号拆开逐个判定，所以都要列。
    '.ps-btn--disabled',
    '.ps-btn[disabled]',
}


def read(p):
    return p.read_text(encoding="utf-8")


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def defined_tokens(css):
    """tokens.css 里定义过的 token 名（不含引用）。"""
    return set(re.findall(r"(--ps-[a-z0-9-]+)\s*:", css))


def check_component_hardcoding(css, name):
    """组件层不得有裸 hex / rgba / 裸 px。"""
    bad = []
    body = strip_comments(css)
    # 只查声明块内部（{ ... }），粗略但足够
    for m in re.finditer(r"\{([^{}]*)\}", body):
        decl = m.group(1)
        # 裸 hex
        for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl):
            bad.append(("hex", h, decl.strip()[:60]))
        # rgb()/rgba()（tokens.css 允许，组件层不允许）
        for r in re.findall(r"rgba?\([^)]*\)", decl):
            bad.append(("rgb", r, decl.strip()[:60]))
        # 裸 px 尺寸（0 除外）
        for p in re.findall(r"(?<![\w-])(\d+(?:\.\d+)?)px", decl):
            if p != "0":
                bad.append(("px", p + "px", decl.strip()[:60]))
    return bad


def check_token_refs(all_css, defined, label):
    missing = {}
    for p in all_css:
        body = strip_comments(read(p))
        for tok in set(re.findall(r"var\(\s*(--ps-[a-z0-9-]+)", body)):
            if tok not in defined:
                missing.setdefault(tok, []).append(p.name)
    return missing


def check_no_opacity_on_content(css, name):
    """禁止在组件层对整块内容用 opacity / filter。

    为什么单独一条规则：opacity 作用在容器上会**连带把里面的文字一起冲淡**。
    2026-09-24 真踩过——为了表达「已停止维护」给 .ps-card--retired 加了
    opacity: 0.62，视觉上到位了，但正文对比度跌破 WCAG AA 下限，
    而只测 token 的对比度脚本完全看不出来（它只看 tokens.css，
    根本不知道 cards.css 里写了什么）。

    弱化状态请改用：中性强调色 + 徽标文字 + 只弱化非文字元素。
    确实需要时，加进 ALLOWED_FILTER_SELECTORS 并写明理由。
    """
    bad = []
    body = strip_comments(css)
    # 找出每个选择器块
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', body):
        raw_sel, decl = m.group(1).strip(), m.group(2)
        if not raw_sel or raw_sel.startswith('@'):
            continue
        # 组合选择器要拆开逐个判定：`.ps-btn[disabled], .ps-btn--disabled`
        # 是**两条**规则共用一个声明，只要有一条不在白名单就应被拦下。
        selectors = [s.strip() for s in raw_sel.split(',') if s.strip()]
        for prop in ('opacity', 'filter', 'backdrop-filter'):
            for v in re.findall(rf'(?<![\w-]){prop}\s*:\s*([^;]+)', decl):
                if prop == 'backdrop-filter' or v.strip() == 'none':
                    continue
                for sel in selectors:
                    if sel in ALLOWED_FILTER_SELECTORS:
                        continue
                    bad.append((sel, prop, v.strip()))
    # 去重但保持顺序
    seen, uniq = set(), []
    for item in bad:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def main():
    errors = []

    # ---- 1. 组件层无硬编码 ----
    cards = read(CARDS)
    hard = check_component_hardcoding(cards, CARDS.name)
    if hard:
        print(f"[FAIL] {CARDS.name} 出现硬编码值 {len(hard)} 处：")
        for kind, val, ctx in hard[:12]:
            print(f"       {kind:4} {val:24} in  {ctx}")
        errors.append(f"{CARDS.name} 有 {len(hard)} 处硬编码")
    else:
        print(f"[ OK ] {CARDS.name} 无硬编码颜色/尺寸")

    # ---- 1b. 禁止对内容用 opacity/filter ----
    opac = check_no_opacity_on_content(cards, CARDS.name)
    if opac:
        print(f"[FAIL] {CARDS.name} 对内容施加了 opacity/filter {len(opac)} 处：")
        for sel, prop, val in opac:
            print(f"       {sel}  ->  {prop}: {val}")
        print("       弱化状态请用中性强调色 + 徽标文字，别用透明度。")
        errors.append(f"{CARDS.name} 有 {len(opac)} 处 opacity/filter 作用于内容")
    else:
        print(f"[ OK ] {CARDS.name} 未对内容施加 opacity/filter")

    # ---- 2. token 引用完整 ----
    tokens = read(TOKENS)
    defined = defined_tokens(tokens)
    css_files = sorted((DOCS / "css").glob("*.css"))
    missing = check_token_refs(css_files, defined, "css")
    if missing:
        print(f"[FAIL] 引用了未定义的 token：")
        for tok, files in missing.items():
            print(f"       {tok:34} <- {', '.join(files)}")
        errors.append(f"{len(missing)} 个 token 引用未定义")
    else:
        print(f"[ OK ] 所有 var(--ps-*) 引用都有定义（共 {len(defined)} 个 token）")

    # ---- 3. token 是否定义了却没人用（提示，非错误）----
    all_refs = set()
    for p in css_files:
        all_refs |= set(re.findall(r"var\(\s*(--ps-[a-z0-9-]+)", strip_comments(read(p))))
    unused = sorted(defined - all_refs)
    if unused:
        print(f"[INFO] 定义了但暂未引用（可能是桥接层或预留）：{len(unused)} 个")
        print(f"       {', '.join(unused[:10])}" + (" ..." if len(unused) > 10 else ""))

    print()
    if errors:
        print("结论:", "；".join(errors))
        return 1
    print("结论: 设计层自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
