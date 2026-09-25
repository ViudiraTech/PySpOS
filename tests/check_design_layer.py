"""docs/ 设计层自检：token 契约 + 组件层纪律

三道检查，都是「机器能查就别靠眼睛」：

1. **对比度**（WCAG AA）：亮/暗两套语义 token 逐项实测，见
   check_tokens_contrast.py 的说明。
2. **组件层无硬编码**：style.css 里不允许出现裸 hex / rgb()；
   尺寸 >= 4px 必须走 --pg-space-*/--pg-radius-*/组件尺寸 token，
   1-3px 算 hairline（描边/偏移）予以放行。html 根字号是环境
   常量，不在 spacing 节奏里，特例放行并在此注明。
   设计 token 存在的意义就是让「改一处、全站变」成立。
3. **token 引用完整**：css 里每个 var(--pg-*) 都必须在 tokens.css 里有定义。
   拼错一个 token 名不会报错，只会静默失效——这条就是抓那个的。
"""
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
TOKENS = DOCS / "css" / "tokens.css"
COMPONENT = DOCS / "css" / "style.css"
PREFIX = r"--pg-[a-z0-9-]+"

# 确实需要 opacity 的选择器白名单。每条都要写明「为什么文字不受影响」。
# 往这里加之前先跑 check_tokens_contrast.py 确认变体后的对比度仍达标。
ALLOWED_FILTER_SELECTORS = {
    # 整站纸纹：纯装饰伪元素，只有噪点背景，不含任何文字，
    # 且 pointer-events: none，不参与交互。
    'body::after',
}


def read(p):
    return p.read_text(encoding="utf-8")


def strip_comments(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r'url\("data:[^"]+"\)', 'url(__DATA__)', css)
    return css


def defined_tokens(css):
    """tokens.css 里定义过的 token 名（不含引用）。"""
    return set(re.findall(r"(" + PREFIX + r")\s*:", css))


def check_component_hardcoding(css, name):
    """组件层不得有裸 hex / rgb() / >=4px 裸尺寸。"""
    bad = []
    body = strip_comments(css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
        raw_sel, decl = m.group(1).strip(), m.group(2)
        if not raw_sel or raw_sel.startswith('@'):
            continue
        # html 根字号是环境常量，不在 spacing 节奏里
        if raw_sel == 'html':
            continue
        for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl):
            bad.append(("hex", h, decl.strip()[:60]))
        for r in re.findall(r"rgba?\([^)]*\)", decl):
            # color-mix() 不是 rgb()，且只允许套 var()，不允许裸色值
            bad.append(("rgb", r, decl.strip()[:60]))
        for p in re.findall(r"(?<![\w-])(\d+(?:\.\d+)?)px", decl):
            if float(p) >= 4:
                bad.append(("px", p + "px", decl.strip()[:60]))
    # color-mix 里出现裸 hex/rgb 才是问题；套 var() 的挑出来免检
    bad = [b for b in bad if not (
        b[0] == "rgb" and "color-mix" in b[2] and not re.search(r"#[0-9a-fA-F]{3}", b[2]))]
    return bad


def check_token_refs(all_css, defined, label):
    missing = {}
    for p in all_css:
        body = strip_comments(read(p))
        for tok in set(re.findall(r"var\(\s*(" + PREFIX + r")", body)):
            if tok not in defined:
                missing.setdefault(tok, []).append(p.name)
    return missing


def check_no_opacity_on_content(css, name):
    """禁止在组件层对整块内容用 opacity / filter（白名单除外）。

    opacity 作用在容器上会连带把里面的文字一起冲淡。
    弱化状态请改用：中性强调色 + 徽标文字 + 只弱化非文字元素。
    """
    bad = []
    body = strip_comments(css)
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', body):
        raw_sel, decl = m.group(1).strip(), m.group(2)
        if not raw_sel or raw_sel.startswith('@'):
            continue
        selectors = [s.strip() for s in raw_sel.split(',') if s.strip()]
        for prop in ('opacity', 'filter', 'backdrop-filter'):
            for v in re.findall(rf'(?<![\w-]){prop}\s*:\s*([^;]+)', decl):
                if prop == 'backdrop-filter' or v.strip() == 'none':
                    continue
                for sel in selectors:
                    if sel in ALLOWED_FILTER_SELECTORS:
                        continue
                    bad.append((sel, prop, v.strip()))
    seen, uniq = set(), []
    for item in bad:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def check_root_tokens_frozen(css, name):
    """`:root` 相关块里不得用 var() 引用**会随主题变的** token。

    症状极难定位的 CSS 陷阱：自定义属性里的 var() 是在声明它的那个
    元素上完成替换的，替换后继承下去的是算好的字面值。如果在 :root 上
    写 `--x: var(--pg-fg-1)`，--pg-fg-1 在 :root 处解析成亮色值，
    --x 就永久等于亮色，body.theme-dark 再怎么覆盖 --pg-fg-1
    都影响不到它。

    唯一允许的引用是 --pg-ref-*（纯字面值，永不随主题变）。
    """
    bad = []
    body = strip_comments(css)
    for m in re.finditer(r':root[^{]*\{(.*?)\n\}', body, re.S):
        block = m.group(1)
        for name_, val in re.findall(r'(' + PREFIX + r')\s*:\s*([^;]+);', block):
            for ref in re.findall(r'var\(\s*(' + PREFIX + r')', val):
                if not ref.startswith('--pg-ref-'):
                    bad.append((name_, ref))
    return bad


def check_no_external_assets(css, name):
    """组件层不许引用外部图片（背景图不可控，压垮对比度）。
    data: 内联（纸纹噪点）允许。"""
    bad = re.findall(r'url\(\s*(?!__DATA__|"data:)([^)]+)\)', strip_comments(css))
    return [b.strip() for b in bad]


def main():
    errors = []

    # ---- 1. 组件层无硬编码 ----
    comp = read(COMPONENT)
    hard = check_component_hardcoding(comp, COMPONENT.name)
    if hard:
        print(f"[FAIL] {COMPONENT.name} 出现硬编码值 {len(hard)} 处：")
        for kind, val, ctx in hard[:12]:
            print(f"       {kind:4} {val:24} in  {ctx}")
        errors.append(f"{COMPONENT.name} 有 {len(hard)} 处硬编码")
    else:
        print(f"[ OK ] {COMPONENT.name} 无硬编码颜色/尺寸")

    # ---- 1b. 禁止对内容用 opacity/filter ----
    opac = check_no_opacity_on_content(comp, COMPONENT.name)
    if opac:
        print(f"[FAIL] {COMPONENT.name} 对内容施加了 opacity/filter {len(opac)} 处：")
        for sel, prop, val in opac:
            print(f"       {sel}  ->  {prop}: {val}")
        print("       弱化状态请用中性强调色 + 徽标文字，别用透明度。")
        errors.append(f"{COMPONENT.name} 有 {len(opac)} 处 opacity/filter 作用于内容")
    else:
        print(f"[ OK ] {COMPONENT.name} 未对内容施加 opacity/filter")

    # ---- 1c. 组件层不许外部图片 ----
    ext = check_no_external_assets(comp, COMPONENT.name)
    if ext:
        print(f"[FAIL] {COMPONENT.name} 引用了外部资源：{ext}")
        errors.append(f"{COMPONENT.name} 有外部资源引用")
    else:
        print(f"[ OK ] {COMPONENT.name} 无外部图片引用")

    # ---- 2. token 引用完整 ----
    tokens = read(TOKENS)
    defined = defined_tokens(tokens)
    css_files = sorted((DOCS / "css").glob("*.css"))
    missing = check_token_refs(css_files, defined, "css")
    if missing:
        print("[FAIL] 引用了未定义的 token：")
        for tok, files in missing.items():
            print(f"       {tok:34} <- {', '.join(files)}")
        errors.append(f"{len(missing)} 个 token 引用未定义")
    else:
        print(f"[ OK ] 所有 var(--pg-*) 引用都有定义（共 {len(defined)} 个 token）")

    # ---- 2b. :root 相关块不得冻结主题 token ----
    frozen = check_root_tokens_frozen(tokens, TOKENS.name)
    if frozen:
        print(f"[FAIL] {TOKENS.name} 有 {len(frozen)} 处 var() 引用会被冻结：")
        for tok, ref in frozen[:10]:
            print(f"       {tok:34} -> {ref}")
        errors.append(f"{len(frozen)} 个 token 会被冻结")
    else:
        print("[ OK ] :root 相关块没有会被 var() 冻结的主题 token")

    # ---- 3. token 是否定义了却没人用（提示，非错误）----
    all_refs = set()
    for p in css_files:
        all_refs |= set(re.findall(r"var\(\s*(" + PREFIX + r")", strip_comments(read(p))))
    unused = sorted(defined - all_refs)
    if unused:
        print(f"[INFO] 定义了但暂未引用：{len(unused)} 个")
        print(f"       {', '.join(unused[:10])}" + (" ..." if len(unused) > 10 else ""))

    print()
    if errors:
        print("结论:", "；".join(errors))
        return 1
    print("结论: 设计层自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
