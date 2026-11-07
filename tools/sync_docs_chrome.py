'''
 *
 *      sync_docs_chrome.py
 *      Single source for the docs site chrome: head assets, header menu and footer sitemap.
 *
 *      2026/11/7 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

# Every page in docs/ carries three marker pairs. This script rewrites what sits between them:
#   <!-- head:start -->   ...  <!-- head:end -->     stylesheet links and favicon
#   <!-- chrome:start --> ...  <!-- chrome:end -->   theme script, skip link, header and menu
#   <!-- foot:start -->   ...  <!-- foot:end -->     footer sitemap and the site script
# Page content stays hand-written. Adding a page means adding it to the lists below and running:
#   python tools/sync_docs_chrome.py            rewrite the pages
#   python tools/sync_docs_chrome.py --check    exit 1 if any page is out of date (CI uses this)

import hashlib
import re
import sys
from html import escape
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"

GITHUB = "https://github.com/ViudiraTech"
MAIL = "mailto:goutoustdio@outlook.com"

# Plain links in the header, in order. (text, page)
HEADER_LINKS = [
    ("PySpOS", "pyspos.html"),
    ("SpaceOS 9", "spaceos9.html"),
    ("SpaceOS 8", "spaceos8.html"),
    ("配置要求", "requirements.html"),
]

# Drop-down menus in the header, shown after the plain links. (label, [(text, page)])
HEADER_MENUS = [
    ("下载", [
        ("PySpOS 更新包", "ota/index.html"),
        ("PySpOS 版本历史", "ota/releases.html"),
        ("SpaceOS 9 镜像", "spaceos9-download.html"),
        ("SpaceOS 8 镜像", "spaceos8-download.html"),
    ]),
    ("存档", [
        ("SpaceOS 7", "spaceos7.html"),
        ("SpaceOS 6", "spaceos6.html"),
    ]),
]

# Footer sitemap columns. A target that starts with http or mailto is external, anything else is a page.
FOOTER = [
    ("项目", [
        ("PySpOS", "pyspos.html"),
        ("SpaceOS 9", "spaceos9.html"),
        ("SpaceOS 8", "spaceos8.html"),
    ]),
    ("下载", [
        ("PySpOS 更新包", "ota/index.html"),
        ("PySpOS 版本历史", "ota/releases.html"),
        ("SpaceOS 9 镜像", "spaceos9-download.html"),
        ("SpaceOS 8 镜像", "spaceos8-download.html"),
    ]),
    ("资料", [
        ("配置要求", "requirements.html"),
        ("GitHub", GITHUB),
        ("联系我们", "index.html#contact"),
    ]),
    ("存档", [
        ("SpaceOS 7", "spaceos7.html"),
        ("SpaceOS 6", "spaceos6.html"),
    ]),
]

FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' rx='12' fill='%23d97757'/%3E"
    "%3Ctext x='32' y='44' font-size='34' font-weight='700' text-anchor='middle' "
    "fill='%23faf9f5' font-family='Georgia,serif'%3EG%3C/text%3E%3C/svg%3E"
)

BLOCKS = ("head", "chrome", "foot")


# Every page in docs/ and docs/ota/, as paths relative to docs/ with forward slashes.
def page_paths():
    pages = sorted(DOCS.glob("*.html")) + sorted((DOCS / "ota").glob("*.html"))
    return [p.relative_to(DOCS).as_posix() for p in pages]


# Hash a static asset with line endings normalised, so the cache key is the same on every OS.
def asset_version(rel):
    data = (DOCS / rel).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(data).hexdigest()[:8]


# Path prefix that leads from a page back to docs/.
def root_prefix(page):
    return "../" * page.count("/")


# True for a target that leaves the site.
def is_external(target):
    return target.startswith(("http://", "https://", "mailto:"))


# Render one <a> for a header or footer target, marking it current when it is the page itself.
def render_link(page, text, target):
    if is_external(target):
        extra = ' rel="noopener" target="_blank"' if target.startswith("http") else ""
        return f'<a href="{escape(target)}"{extra}>{escape(text)}</a>'
    current = ' aria-current="page"' if target == page else ""
    return f'<a href="{root_prefix(page)}{target}"{current}>{escape(text)}</a>'


# Render the stylesheet links and favicon for one page.
def render_head(page):
    root = root_prefix(page)
    return "\n".join([
        f'  <link rel="stylesheet" href="{root}css/tokens.css?v={asset_version("css/tokens.css")}">',
        f'  <link rel="stylesheet" href="{root}css/style.css?v={asset_version("css/style.css")}">',
        f'  <link rel="icon" href="{FAVICON}">',
    ])


# Render the header menu items for one page.
def render_menu(page):
    out = []
    for text, target in HEADER_LINKS:
        out.append(f"          <li>{render_link(page, text, target)}</li>")
    for label, items in HEADER_MENUS:
        current = " is-current" if any(t == page for _x, t in items) else ""
        out.append(f'          <li><details class="menu{current}"><summary>{escape(label)}</summary>')
        out.append("            <ul>")
        for text, target in items:
            out.append(f"              <li>{render_link(page, text, target)}</li>")
        out.append("            </ul>")
        out.append("          </details></li>")
    out.append(f"          <li>{render_link(page, 'GitHub', GITHUB)}</li>")
    return "\n".join(out)


# Render the theme script, skip link and header for one page.
def render_chrome(page):
    root = root_prefix(page)
    version = asset_version("js/theme-init.js")
    return "\n".join([
        f'  <script src="{root}js/theme-init.js?v={version}"></script>',
        '  <a class="skip-link" href="#main">跳到正文</a>',
        '  <header class="site-header">',
        '    <div class="container header-inner">',
        f'      <a class="brand" href="{root}index.html">GoutouStdio</a>',
        '      <nav class="site-nav" id="site-nav" aria-label="主导航">',
        "        <ul>",
        render_menu(page),
        "        </ul>",
        "      </nav>",
        '      <div class="header-actions">',
        '        <button class="icon-btn" id="theme-toggle" type="button" aria-label="切换主题">主题</button>',
        '        <button class="icon-btn nav-toggle" id="nav-toggle" type="button" '
        'aria-controls="site-nav" aria-expanded="false">菜单</button>',
        "      </div>",
        "    </div>",
        "  </header>",
    ])


# Render the footer sitemap and the site script for one page.
def render_foot(page):
    root = root_prefix(page)
    out = [
        '  <footer class="site-footer">',
        '    <div class="container footer-grid">',
        '      <div class="footer-about">',
        f'        <a class="brand" href="{root}index.html">GoutouStdio</a>',
        "        <p>学生自发组织的开源小组，做操作系统相关的项目。</p>",
        "      </div>",
    ]
    for title, items in FOOTER:
        out.append("      <nav>")
        out.append(f'        <h2 class="footer-title">{escape(title)}</h2>')
        out.append("        <ul>")
        for text, target in items:
            out.append(f"          <li>{render_link(page, text, target)}</li>")
        out.append("        </ul>")
        out.append("      </nav>")
    out += [
        "    </div>",
        '    <div class="container">',
        '      <div class="footer-base">',
        "        <p>© 2022–2026 GoutouStdio。学生自发组织的项目，不涉及任何商业活动，GoutouStdio 不是真实的公司。</p>",
        f'        <p><a href="{MAIL}">goutoustdio@outlook.com</a></p>',
        "      </div>",
        "    </div>",
        "  </footer>",
        f'  <script src="{root}js/main.js?v={asset_version("js/main.js")}"></script>',
    ]
    return "\n".join(out)


RENDERERS = {"head": render_head, "chrome": render_chrome, "foot": render_foot}


# Return the page text with every marker pair rewritten, plus the names of pairs that are missing.
def apply_blocks(page, text):
    missing = []
    for name in BLOCKS:
        pattern = re.compile(
            r"[ \t]*<!-- %s:start -->.*?<!-- %s:end -->" % (name, name), re.S)
        if not pattern.search(text):
            missing.append(name)
            continue
        block = "  <!-- %s:start -->\n%s\n  <!-- %s:end -->" % (name, RENDERERS[name](page), name)
        text = pattern.sub(lambda _m: block, text, count=1)
    return text, missing


# Read a page, normalising line endings so the comparison is stable on every OS.
def read_page(page):
    return (DOCS / page).read_text(encoding="utf-8").replace("\r\n", "\n")


# Pages of the site that the header cannot reach, and menu targets that point at no page.
def nav_mismatch():
    linked = {"index.html"}
    for _text, target in HEADER_LINKS:
        linked.add(target)
    for _label, items in HEADER_MENUS:
        linked.update(target for _text, target in items)
    pages = set(page_paths())
    return sorted(pages - linked), sorted(linked - pages)


# List the problems found when comparing every page with what this script would write.
def check():
    problems = []
    unlisted, dangling = nav_mismatch()
    for page in unlisted:
        problems.append(f"{page}: 不在页眉菜单里，访客从导航找不到它")
    for page in dangling:
        problems.append(f"菜单指向不存在的页面: {page}")
    for page in page_paths():
        text = read_page(page)
        new, missing = apply_blocks(page, text)
        for name in missing:
            problems.append(f"{page}: 缺少 <!-- {name}:start --> / <!-- {name}:end --> 标记")
        if not missing and new != text:
            problems.append(f"{page}: 页眉/菜单/页脚与 tools/sync_docs_chrome.py 不一致，"
                            "请运行 python tools/sync_docs_chrome.py")
    return problems


# Rewrite every page whose chrome is out of date and return the pages that changed.
def sync():
    changed = []
    for page in page_paths():
        text = read_page(page)
        new, missing = apply_blocks(page, text)
        if missing:
            print(f"[WARN] {page}: 缺少标记 {', '.join(missing)}，已跳过")
            continue
        if new != text:
            (DOCS / page).write_text(new, encoding="utf-8", newline="\n")
            changed.append(page)
    return changed


# Entry point: rewrite the pages, or only verify them with --check.
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        problems = check()
        for line in problems:
            print(f"[FAIL] {line}")
        if not problems:
            print("[ OK ] 所有页面的页眉、菜单与页脚都与单一来源一致")
        return 1 if problems else 0
    unlisted, dangling = nav_mismatch()
    for page in unlisted:
        print(f"[WARN] {page} 不在页眉菜单里，先把它加进 HEADER_LINKS 或 HEADER_MENUS")
    for page in dangling:
        print(f"[WARN] 菜单指向不存在的页面: {page}")
    changed = sync()
    for page in changed:
        print(f"[sync] {page}")
    print(f"完成：{len(changed)} 个页面更新")
    return 1 if unlisted or dangling else 0


if __name__ == "__main__":
    sys.exit(main())
