'''
 *
 *      check_ota_manifest.py
 *      OTA manifest self-check: every version.json entry must point at a package that exists with a matching hash.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OTA = os.path.join(REPO, "docs", "ota")
VJ = os.path.join(OTA, "version.json")


# Hash a file in 64 KiB blocks so a large zip does not have to fit in memory.
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


# Verify docs/ota/version.json against the packages on disk and return 1 on any error.
def main():
    if not os.path.exists(VJ):
        print("[FAIL] 找不到 docs/ota/version.json")
        return 1
    data = json.load(open(VJ, encoding="utf-8"))
    errs, warns = [], []

    top_ver = data.get("version")
    top_url = data.get("download_url")
    top_sha = data.get("sha256")
    top_size = data.get("file_size")

    # ---- top level (the current version) ----
    if top_url and not top_url.startswith("http"):
        p = os.path.join(OTA, top_url)
        if not os.path.exists(p):
            errs.append(f"顶层 download_url 指向不存在的文件: {top_url}")
        else:
            real = os.path.getsize(p)
            if top_size is not None and real != top_size:
                errs.append(f"file_size 不符: JSON={top_size} 实际={real}")
            if top_sha:
                actual = sha256_of(p)
                if actual != top_sha:
                    errs.append(f"sha256 不符: JSON={top_sha[:16]}… 实际={actual[:16]}…")
                else:
                    print(f"[ OK ] 当前版本 {top_ver} 包校验通过"
                          f"（{real} 字节，sha256 一致）")

    # ---- every changelog entry ----
    changelog = data.get("changelog", [])
    if not changelog:
        errs.append("changelog 为空")
    print(f"[INFO] changelog 共 {len(changelog)} 条")

    for entry in changelog:
        ver = entry.get("version", "?")
        url = entry.get("download_url")
        if not url:
            errs.append(f"{ver}: 缺 download_url")
            continue
        if url.startswith("http"):
            warns.append(f"{ver}: download_url 是外链，未校验")
            continue
        p = os.path.join(OTA, url)
        if not os.path.exists(p):
            errs.append(f"{ver}: 包不存在 {url}")
            continue
        if entry.get("file_size") is not None and \
                os.path.getsize(p) != entry["file_size"]:
            errs.append(f"{ver}: file_size 不符")
        if entry.get("sha256"):
            if sha256_of(p) != entry["sha256"]:
                errs.append(f"{ver}: sha256 不符")
        else:
            warns.append(f"{ver}: sha256 为 null（3.0.0 指向 GitHub tag，可接受）")

    # ---- the top-level version must be the first changelog entry ----
    if changelog and changelog[0].get("version") != top_ver:
        errs.append(f"顶层 version={top_ver} 与 changelog 首位 "
                    f"{changelog[0].get('version')} 不一致")

    # ---- develop_stage validity ----
    stage = (data.get("develop_stage") or "").lower()
    if stage not in {"beta", "rc", "release", "alpha", "pre", "dev"}:
        warns.append(f"develop_stage={stage!r} 不在约定取值内")

    # ---- whether the releases.html static fallback is in sync ----
    rel = os.path.join(OTA, "releases.html")
    marker = "const fallbackVersionData = "
    if os.path.exists(rel):
        h = open(rel, encoding="utf-8").read()
        i = h.find(marker)
        if i >= 0:
            j = i + len(marker)
            try:
                obj, _ = json.JSONDecoder().raw_decode(h[j:])
                a = [c.get("version") for c in obj.get("changelog", [])]
                b = [c.get("version") for c in changelog]
                if a != b:
                    errs.append(f"releases.html 静态兜底已过期: {a} vs {b}")
                else:
                    print("[ OK ] releases.html 静态兜底与 version.json 同步")
            except ValueError:
                errs.append("releases.html 的 fallbackVersionData 不是合法 JSON")

    # ---- zips in the directory that nobody registered ----
    registered = {e.get("download_url") for e in changelog}
    registered.add(top_url)
    for f in sorted(os.listdir(OTA)):
        if f.endswith(".zip") and f not in registered:
            warns.append(f"目录里的 {f} 未登记在 version.json（历史包？）")

    for w in warns:
        print(f"[WARN] {w}")
    for e in errs:
        print(f"[FAIL] {e}")
    print()
    print("结论:", "OTA 清单一致" if not errs else f"{len(errs)} 个问题")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
