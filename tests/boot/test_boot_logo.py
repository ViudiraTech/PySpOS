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


# The splash keeps the mark left-aligned with the wordmark below it.
def test_splash_left_aligned_with_wordmark_below(capsys):
    kernel.print_splash()
    out = capsys.readouterr().out.splitlines()
    art = kernel.ascii_logo.splitlines()
    assert out[0] == ""
    assert out[1:1 + len(art)] == art
    assert out[1 + len(art)] == ""
    assert "PySpOS" in out[2 + len(art)]
    assert out[-1] == ""


# Density buckets: spaces stay bare, body blue, glow core cyan.
def test_colorize_splash_line_buckets():
    assert kernel._colorize_splash_line("  ") == "  "
    assert kernel._colorize_splash_line(".-") == \
        "\033[94m.\033[0m\033[94m-\033[0m"
    assert kernel._colorize_splash_line("#") == "\033[96m#\033[0m"


# Captured/piped output never carries escapes; the gate honors NO_COLOR.
def test_splash_plain_without_tty(monkeypatch, capsys):
    kernel.print_splash()
    assert "\033[" not in capsys.readouterr().out
    monkeypatch.setenv("NO_COLOR", "1")
    assert kernel._splash_color_enabled() is False


# On a real terminal the splash carries color (gate forced for the test).
def test_splash_colors_on_terminal(monkeypatch, capsys):
    monkeypatch.setattr(kernel, "_splash_color_enabled", lambda: True)
    kernel.print_splash()
    out = capsys.readouterr().out
    assert "\033[94m.\033[0m" in out
    assert "\033[96m#\033[0m" in out
