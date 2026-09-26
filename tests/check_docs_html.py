'''
 *
 *      check_docs_html.py
 *      Docs static site self-check: tag balance, dead links, anchors and product status consistency.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import glob
import os
import re
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, "docs")

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


# HTML parser collecting tag balance, ids and every local link target.
class PageCheck(HTMLParser):
# Start with an empty open-tag stack, error list, link list and id set.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errs = []
        self.links = []
        self.ids = set()

# Record ids and link targets, and push every non-void tag onto the stack.
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and "href" in d:
            self.links.append(d["href"])
        if tag == "link" and d.get("rel") == "stylesheet" and "href" in d:
            self.links.append(d["href"])
        if tag == "script" and d.get("src"):
            self.links.append(d["src"])
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

# Pop the open-tag stack, recording a mismatch or a stray end tag.
    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errs.append(f"L{self.getpos()[0]}: 多余的 </{tag}>")
            return
        opened, pos = self.stack.pop()
        if opened != tag:
            self.errs.append(
                f"L{self.getpos()[0]}: </{tag}> 与 <{opened}>(L{pos[0]}) 不匹配")


# Feed one page to the parser, then verify local links and in-page anchors exist.
def check_page(path):
    c = PageCheck()
    c.feed(open(path, encoding="utf-8").read())
    if c.stack:
        c.errs.append("未闭合: "
                      + ", ".join(f"<{t}>(L{p[0]})" for t, p in c.stack))

    base = os.path.dirname(path)
    for href in c.links:
        if href.startswith(("http://", "https://", "mailto:", "data:", "#")):
            if href.startswith("#") and len(href) > 1 and href[1:] not in c.ids:
                c.errs.append(f"页内锚点不存在: {href}")
            continue
        target = href.split("#")[0]
        if target and not os.path.exists(os.path.join(base, target)):
            c.errs.append(f"死链: {href}")
    return c


# Check that the product status story is self-consistent.
def check_product_states():
    errs = []
    idx = os.path.join(DOCS, "index.html")
    if os.path.exists(idx):
        s = open(idx, encoding="utf-8").read()
        m = re.search(r'<ol class="index-list">(.*?)</ol>', s, re.S)
        items = re.findall(r'<li([^>]*)>(.*?)</li>', m.group(1), re.S) if m else []
        if not items:
            errs.append("首页缺少作品索引（.index-list）")
        for cls, body in items:
            title = re.search(r'<h3>([^<]+)<', body)
            badge = re.search(r'badge[^"]*">\s*([^<]+?)\s*<', body)
            if not (title and badge):
                errs.append("作品条目缺少标题或状态徽标")
                continue
            t, b = title.group(1).strip(), badge.group(1).strip()
            retired = "index-retired" in cls
            says_retired = "停止" in b or "停更" in b
            if retired != says_retired:
                errs.append(
                    f"作品 {t}: 视觉状态(retired={retired})"
                    f"与徽标「{b}」矛盾")
            # A retired entry must not be a dead end: it needs at least one way out
            if retired and not re.search(r'<a\s+href="[^"#]', body):
                errs.append(f"作品 {t}: 停更条目没有任何可点击出口")

    # The SpaceOS 6/7 detail pages need a retirement notice pointing at PySpOS
    for ver in ("6", "7"):
        p = os.path.join(DOCS, f"spaceos{ver}.html")
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8").read()
        m = re.search(r'<div class="notice notice-warn"[^>]*>(.*?)</div>\s*</div>',
                      s, re.S)
        if not m:
            errs.append(f"spaceos{ver}.html: 缺少停更提示块（.notice.notice-warn）")
            continue
        banner = m.group(1)
        if "停止开发" not in banner:
            errs.append(f"spaceos{ver}.html: 提示块未明确写「停止开发」")
        if "pyspos.html" not in banner:
            errs.append(f"spaceos{ver}.html: 提示块未指向当前维护的 PySpOS")
    return errs


# Check every docs page, print a per-page table and return 1 if anything failed.
def main():
    pages = sorted(glob.glob(os.path.join(DOCS, "*.html"))
                   + glob.glob(os.path.join(DOCS, "ota", "*.html")))
    if not pages:
        print("[FAIL] 找不到任何 HTML 页面")
        return 1

    total = 0
    print(f"{'页面':28} {'结果':>6}  说明")
    print("-" * 62)
    for p in pages:
        c = check_page(p)
        rel = os.path.relpath(p, REPO)
        print(f"{rel:28} {len(c.errs):>6}  {'OK' if not c.errs else '有问题'}")
        for e in c.errs[:6]:
            print(f"      - {e}")
        total += len(c.errs)

    print("-" * 62)
    state_errs = check_product_states()
    if state_errs:
        print("产品状态一致性:")
        for e in state_errs:
            print(f"      - {e}")
        total += len(state_errs)
    else:
        print("产品状态一致性: OK（停更/维护/开发中标记自洽，且停更卡都指向替代品）")

    print()
    print(f"结论: {'全部通过' if not total else f'{total} 个问题'}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
