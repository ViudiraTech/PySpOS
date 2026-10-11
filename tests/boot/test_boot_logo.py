'''
 *
 *      test_boot_logo.py
 *      Boot splash loads from the logo file, classic banner as fallback.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import kernel


# A missing logo file falls back to the classic banner instead of breaking boot.
def test_missing_logo_falls_back_to_classic(tmp_path):
    assert kernel._load_ascii_logo(str(tmp_path / "missing.txt")) == \
        kernel._CLASSIC_ASCII_LOGO


# A present file is used verbatim (minus the trailing newline print adds).
def test_logo_file_loads_verbatim(tmp_path):
    art = tmp_path / "art.txt"
    art.write_text("  X\nY  \n", encoding="utf-8")
    assert kernel._load_ascii_logo(str(art)) == "  X\nY  "


# The shipped splash is the generated mark: multi-line and bounded by 80 cols.
def test_shipped_logo_is_splash_shaped():
    lines = kernel.ascii_logo.splitlines()
    assert len(lines) >= 10
    assert all(len(line) <= 80 for line in lines)
    assert any("#" in line or "@" in line or "%" in line for line in lines)
