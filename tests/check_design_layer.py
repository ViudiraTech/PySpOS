'''
 *
 *      check_design_layer.py
 *      Docs design layer self-check: token contract, no hardcoded colour or spacing, no frozen theme token.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
TOKENS = DOCS / "css" / "tokens.css"
COMPONENT = DOCS / "css" / "style.css"
PREFIX = r"--pg-[a-z0-9-]+"

# Selectors allowed to use opacity. Each entry must say why the text is unaffected.
# Before adding an entry, run check_tokens_contrast.py to confirm the variant still meets contrast.
ALLOWED_FILTER_SELECTORS = {
    # Site-wide paper grain: a purely decorative pseudo-element carrying a noise background, no text in it,
    # and pointer-events: none, so it takes no part in interaction.
    'body::after',
}


# Read a CSS file as UTF-8 text.
def read(p):
    return p.read_text(encoding="utf-8")


# Drop /* */ comments and fold inline data: URLs to a placeholder, so neither can trip a pattern.
def strip_comments(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r'url\("data:[^"]+"\)', 'url(__DATA__)', css)
    return css


# Token names that tokens.css defines, references excluded.
def defined_tokens(css):
    return set(re.findall(r"(" + PREFIX + r")\s*:", css))


# Flag bare hex, rgb() and raw px >= 4 in the component layer.
def check_component_hardcoding(css, name):
    bad = []
    body = strip_comments(css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
        raw_sel, decl = m.group(1).strip(), m.group(2)
        if not raw_sel or raw_sel.startswith('@'):
            continue
        # The html root font size is an environment constant, outside the spacing rhythm
        if raw_sel == 'html':
            continue
        for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", decl):
            bad.append(("hex", h, decl.strip()[:60]))
        for r in re.findall(r"rgba?\([^)]*\)", decl):
            # color-mix() is not rgb(), and it only takes var(); bare colour values are not allowed
            bad.append(("rgb", r, decl.strip()[:60]))
        for p in re.findall(r"(?<![\w-])(\d+(?:\.\d+)?)px", decl):
            if float(p) >= 4:
                bad.append(("px", p + "px", decl.strip()[:60]))
    # Only a bare hex/rgb inside color-mix is a problem; the var()-wrapped ones are filtered out
    bad = [b for b in bad if not (
        b[0] == "rgb" and "color-mix" in b[2] and not re.search(r"#[0-9a-fA-F]{3}", b[2]))]
    return bad


# Map every var(--pg-*) reference that tokens.css never defines to the files using it.
def check_token_refs(all_css, defined, label):
    missing = {}
    for p in all_css:
        body = strip_comments(read(p))
        for tok in set(re.findall(r"var\(\s*(" + PREFIX + r")", body)):
            if tok not in defined:
                missing.setdefault(tok, []).append(p.name)
    return missing


# Flag opacity or filter applied to whole content blocks, whitelist aside.
def check_no_opacity_on_content(css, name):
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


# Flag :root declarations that alias a theme-varying token through var().
def check_root_tokens_frozen(css, name):
    bad = []
    body = strip_comments(css)
    for m in re.finditer(r':root[^{]*\{(.*?)\n\}', body, re.S):
        block = m.group(1)
        for name_, val in re.findall(r'(' + PREFIX + r')\s*:\s*([^;]+);', block):
            for ref in re.findall(r'var\(\s*(' + PREFIX + r')', val):
                if not ref.startswith('--pg-ref-'):
                    bad.append((name_, ref))
    return bad


# Flag url() references to anything but inline data: images.
def check_no_external_assets(css, name):
    bad = re.findall(r'url\(\s*(?!__DATA__|"data:)([^)]+)\)', strip_comments(css))
    return [b.strip() for b in bad]


# Run every check over docs/css, print the findings and return 1 if any failed.
def main():
    errors = []

    # ---- 1. no hardcoded values in the component layer ----
    comp = read(COMPONENT)
    hard = check_component_hardcoding(comp, COMPONENT.name)
    if hard:
        print(f"[FAIL] {COMPONENT.name} 出现硬编码值 {len(hard)} 处：")
        for kind, val, ctx in hard[:12]:
            print(f"       {kind:4} {val:24} in  {ctx}")
        errors.append(f"{COMPONENT.name} 有 {len(hard)} 处硬编码")
    else:
        print(f"[ OK ] {COMPONENT.name} 无硬编码颜色/尺寸")

    # ---- 1b. no opacity/filter on content ----
    opac = check_no_opacity_on_content(comp, COMPONENT.name)
    if opac:
        print(f"[FAIL] {COMPONENT.name} 对内容施加了 opacity/filter {len(opac)} 处：")
        for sel, prop, val in opac:
            print(f"       {sel}  ->  {prop}: {val}")
        print("       弱化状态请用中性强调色 + 徽标文字，别用透明度。")
        errors.append(f"{COMPONENT.name} 有 {len(opac)} 处 opacity/filter 作用于内容")
    else:
        print(f"[ OK ] {COMPONENT.name} 未对内容施加 opacity/filter")

    # ---- 1c. no external images in the component layer ----
    ext = check_no_external_assets(comp, COMPONENT.name)
    if ext:
        print(f"[FAIL] {COMPONENT.name} 引用了外部资源：{ext}")
        errors.append(f"{COMPONENT.name} 有外部资源引用")
    else:
        print(f"[ OK ] {COMPONENT.name} 无外部图片引用")

    # ---- 2. every token reference resolves ----
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

    # ---- 2b. :root blocks must not freeze themed tokens ----
    frozen = check_root_tokens_frozen(tokens, TOKENS.name)
    if frozen:
        print(f"[FAIL] {TOKENS.name} 有 {len(frozen)} 处 var() 引用会被冻结：")
        for tok, ref in frozen[:10]:
            print(f"       {tok:34} -> {ref}")
        errors.append(f"{len(frozen)} 个 token 会被冻结")
    else:
        print("[ OK ] :root 相关块没有会被 var() 冻结的主题 token")

    # ---- 3. tokens defined but never referenced (informational, not an error) ----
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
