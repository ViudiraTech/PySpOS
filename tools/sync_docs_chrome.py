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

# Drop-down menus in the header, shown after the plain links. (label, [(text, page, icon)])
# The icons match the product glyphs used on the home page: terminal, chip and window.
HEADER_MENUS = [
    ("下载", [
        ("PySpOS 更新包", "ota/index.html", "terminal"),
        ("PySpOS 版本历史", "ota/releases.html", "clock"),
        ("SpaceOS 9 镜像", "spaceos9-download.html", "chip"),
        ("SpaceOS 8 镜像", "spaceos8-download.html", "window"),
    ]),
    ("存档", [
        ("SpaceOS 7", "spaceos7.html", "archive"),
        ("SpaceOS 6", "spaceos6.html", "archive"),
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


# Line icons, 24x24, drawn for this site. Pages use them as <svg class="icon"><use href="#i-name"/></svg>.
# Stroke, fill and size come from CSS (.icon), so one set works in both themes.
ICONS = {
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4.5M12 17.5h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "download": '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    "terminal": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M7 10l3 2.5L7 15M12.5 15H17"/>',
    "chip": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/><rect x="10" y="10" width="4" height="4" rx=".5"/>'
            '<path d="M9.5 3.5v3M14.5 3.5v3M9.5 17.5v3M14.5 17.5v3M3.5 9.5h3M3.5 14.5h3M17.5 9.5h3M17.5 14.5h3"/>',
    "window": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M3 9.5h18M6.5 7h.01M9 7h.01"/>',
    "layers": '<path d="M12 4l9 4.5-9 4.5-9-4.5z"/><path d="M3 12.5l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>',
    "fork": '<circle cx="6.5" cy="5.5" r="2"/><circle cx="6.5" cy="18.5" r="2"/><circle cx="17.5" cy="9" r="2"/>'
            '<path d="M6.5 7.5v9M17.5 11c0 3.5-4 4.5-9 6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "code": '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12"/>',
    "swap": '<path d="M4 8h13M13.5 4.5L17 8l-3.5 3.5M20 16H7M10.5 12.5L7 16l3.5 3.5"/>',
    "plug": '<path d="M9 3.5v5M15 3.5v5M6.5 8.5h11v3.5a5.5 5.5 0 0 1-11 0zM12 17.5v3"/>',
    "disk": '<ellipse cx="12" cy="6.5" rx="7.5" ry="3"/><path d="M4.5 6.5v11c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-11M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/>',
    "server": '<rect x="3.5" y="4" width="17" height="6.5" rx="2"/><rect x="3.5" y="13.5" width="17" height="6.5" rx="2"/>'
              '<path d="M7 7.25h.01M7 16.75h.01"/>',
    "archive": '<rect x="3.5" y="4.5" width="17" height="4.5" rx="1.5"/>'
               '<path d="M5 9v9.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V9M10 13h4"/>',
    "mail": '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M4.5 7.5l7.5 6 7.5-6"/>',
    "shield": '<path d="M12 3.5l7 2.5v5.5c0 4.2-3 7.4-7 9-4-1.6-7-4.8-7-9V6z"/><path d="M8.8 12l2.4 2.4 4-4.4"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l5.5 3.5-5.5 3.5z"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "external": '<path d="M14 5h5v5M19 5l-8 8M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
}

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


# One inline icon that references the sprite.
def icon(name, extra=""):
    cls = f"icon {extra}".strip()
    return f'<svg class="{cls}" aria-hidden="true"><use href="#i-{name}"/></svg>'


# The brand mark: three stacked layers, the same picture as the home page illustration.
BRAND_MARK = (
    '<svg class="brand-mark" viewBox="0 0 28 28" aria-hidden="true">'
    '<rect class="m1" x="3" y="4" width="22" height="6" rx="2"/>'
    '<rect class="m2" x="3" y="11" width="22" height="6" rx="2"/>'
    '<rect class="m3" x="3" y="18" width="22" height="6" rx="2"/></svg>'
)


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
        current = " is-current" if any(t == page for _x, t, _i in items) else ""
        out.append(f'          <li><details class="menu{current}"><summary>{escape(label)}{icon("chevron", "chev")}</summary>')
        out.append("            <ul>")
        for text, target, name in items:
            link = render_link(page, text, target).replace(">", f">{icon(name)}", 1)
            out.append(f"              <li>{link}</li>")
        out.append("            </ul>")
        out.append("          </details></li>")
    github = render_link(page, "GitHub", GITHUB).replace("</a>", f"{icon('external', 'ext')}</a>")
    out.append(f"          <li>{github}</li>")
    return "\n".join(out)


# Render the hidden SVG sprite that holds every icon.
def render_sprite():
    out = ['  <svg class="sprite" aria-hidden="true" focusable="false">']
    for name, body in ICONS.items():
        out.append(f'    <symbol id="i-{name}" viewBox="0 0 24 24">{body}</symbol>')
    out.append("  </svg>")
    return "\n".join(out)


# Render the theme script, sprite, skip link and header for one page.
def render_chrome(page):
    root = root_prefix(page)
    version = asset_version("js/theme-init.js")
    return "\n".join([
        f'  <script src="{root}js/theme-init.js?v={version}"></script>',
        render_sprite(),
        '  <a class="skip-link" href="#main">跳到正文</a>',
        '  <header class="site-header">',
        '    <div class="container header-inner">',
        f'      <a class="brand" href="{root}index.html">{BRAND_MARK}GoutouStdio</a>',
        '      <nav class="site-nav" id="site-nav" aria-label="主导航">',
        "        <ul>",
        render_menu(page),
        "        </ul>",
        "      </nav>",
        '      <div class="header-actions">',
        '        <button class="icon-btn" id="theme-toggle" type="button" aria-label="切换主题" title="切换主题">'
        f'{icon("moon", "icon-moon")}{icon("sun", "icon-sun")}</button>',
        '        <button class="icon-btn nav-toggle" id="nav-toggle" type="button" aria-label="菜单" title="菜单" '
        f'aria-controls="site-nav" aria-expanded="false">{icon("menu", "icon-menu")}{icon("close", "icon-close")}</button>',
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
        linked.update(target for _text, target, _icon in items)
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
