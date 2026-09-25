"""shparser：分词 / 语法 / 展开。"""
import os
import sys

import pytest

sys.path.insert(0, "src")
from shell import shparser


def words(line):
    return [(k, v) for k, v in shparser.tokenize(line)]


def test_tokenize_quotes_and_escapes():
    assert words("echo hi") == [
        ("word", [("lit", "echo", False)]),
        ("word", [("lit", "hi", False)])]
    toks = words("echo 'a b' \"c d\" e\\ f")
    assert toks[1] == ("word", [("lit", "a b", True)])
    assert toks[2] == ("word", [("lit", "c d", True)])
    assert toks[3] == ("word", [("lit", "e", False), ("lit", " ", True),
                                ("lit", "f", False)])


def test_tokenize_operators():
    toks = words("a | b && c || d ; e & f > g >> h < i 2> j 2>&1")
    ops = [v for k, v in toks if k == "op"]
    assert ops == ["|", "&&", "||", ";", "&", ">", ">>", "<", "2>", "2>&1"]


def test_tokenize_subst_and_vars():
    toks = words("echo $(a $(b)) `c` $X ${Y} $? $$ $!")
    kinds = [s[0] for _, spans in toks[1:] for s in spans]
    assert kinds.count("subst") == 2
    assert ("var", "X", False) in toks[3][1]
    assert ("var", "Y", False) in toks[4][1]
    assert ("var", "?", False) in toks[5][1]


def test_tokenize_unclosed():
    with pytest.raises(shparser.LexError):
        shparser.tokenize("echo 'abc")
    with pytest.raises(shparser.LexError):
        shparser.tokenize('echo "abc')
    with pytest.raises(shparser.LexError):
        shparser.tokenize("echo $(a")


def test_parse_pipeline_and_chain():
    prog = shparser.parse("a | b && c || d ; e &")
    assert len(prog) == 4
    assert [s["background"] for s, _ in prog] == [False, False, False, True]
    assert [c for _, c in prog] == [None, "&&", "||", None]
    assert len(prog[0][0]["cmds"]) == 2


def test_parse_redirects_and_assign():
    prog = shparser.parse("A=1 B=x cmd > out.txt 2> err >> app < in")
    stmt = prog[0][0]
    assert stmt["cmds"][0]["assign"] == [
        ("A", [("lit", "1", False)]), ("B", [("lit", "x", False)])]
    redirs = stmt["cmds"][0]["redirects"]
    assert (1, ">", redirs[0][2] is not None) == (1, ">", True)
    assert [r[1] for r in redirs] == [">", ">", ">>", "<"]


def test_parse_errors():
    with pytest.raises(shparser.LexError):
        shparser.parse("a | | b")
    with pytest.raises(shparser.LexError):
        shparser.parse("a >")
    with pytest.raises(shparser.LexError):
        shparser.parse("a &&")


def _ctx(**kw):
    ctx = {"vars": {}, "last": 0, "depth": 0, "run_capture": None}
    ctx.update(kw)
    return ctx


def _expand(line, **kw):
    out = []
    for kind, spans in shparser.tokenize(line):
        if kind == "word":
            out.extend(shparser.expand_word(spans, _ctx(**kw)))
    return out


def test_expand_vars_and_specials(tmp_path, monkeypatch):
    monkeypatch.setenv("PYSPOS_TEST_VAR", "vv")
    assert _expand("$PYSPOS_TEST_VAR") == ["vv"]
    assert _expand("${PYSPOS_TEST_VAR}") == ["vv"]
    assert _expand("$NO_SUCH_VAR_XYZ") == []
    assert _expand("a$NO_SUCH_VAR_XYZ") == ["a"]
    assert _expand('"$NO_SUCH_VAR_XYZ"') == [""]
    assert _expand("$?", last=3) == ["3"]
    assert _expand("$$") == [str(os.getpid())]
    assert _expand("~")[0].startswith("/")


def test_expand_subst_and_glob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    ctx_run = lambda line, d: "hi\n"  # noqa: E731
    assert _expand("$(echo hi)", run_capture=ctx_run) == ["hi"]
    assert _expand("`echo hi`", run_capture=ctx_run) == ["hi"]
    assert sorted(_expand("*.txt")) == ["a.txt", "b.txt"]
    assert _expand("no-match-*.txt") == ["no-match-*.txt"]
    assert _expand('"*.txt"') == ["*.txt"]
    assert _expand("a b") == ["a", "b"]
