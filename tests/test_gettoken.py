'''
 *
 *      test_gettoken.py
 *      gettoken grading: score first, machine-tap detection and stratified question sampling.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import pathlib
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "src/apps")


# gettoken.py guards against direct execution, so exec its body under __name__ == '__exec__' the way the open command does.
def _load_gettoken():
    # gettoken.py guards on __name__ == "__exec__" against being run directly,
    # so exec the module body the way the open command loads it.
    src = pathlib.Path("src/apps/gettoken.py").read_text(encoding="utf-8")
    ns = {"__name__": "__exec__"}
    exec(compile(src, "gettoken.py", "exec"), ns)
    return ns


_ns = _load_gettoken()


# Attribute proxy onto the exec'd gettoken namespace.
class _GT:
# Forward the lookup to the exec'd module namespace.
    def __getattr__(self, name):
        return _ns[name]


gt = _GT()


# A pool of 30 true and 30 false items, so stratified sampling has room to balance.
def _pool():
    return [{"question": f"q{i}", "answer": True} for i in range(30)] + [
        {"question": f"f{i}", "answer": False} for i in range(30)]


# Sampling returns 5 true and 5 false questions in any order, closing the 'answer y to everything' exploit.
def test_balanced_sampling():
    # Stratified sampling: 5 true and 5 false, shuffled (closes the "answer y to everything for 79" hole)
    for _ in range(5):
        picked = gt.select_questions(_pool())
        assert len(picked) == 10
        assert sum(1 for q in picked if q["answer"] is True) == 5
        assert sum(1 for q in picked if q["answer"] is False) == 5


# A pool too small to stratify degrades to returning it as it is.
def test_sampling_fallback_when_pool_small():
    pool = [{"question": "only", "answer": True}]
    assert len(gt.select_questions(pool)) == 1


# A real user run (10 correct, mean 2.69s, slowest 3.91s) must score 100 and not be flagged as automated.
def test_user_case_100_points_fast_passes():
    # Replay of a real user run: 10 correct answers, times from 1.5s, slowest 3.91s, mean 2.69s
    # The old algorithm called a mean under 3s cheating; the new one has to pass it
    times = [3.13, 3.91, 2.33, 1.5, 2.65, 3.46, 2.45, 2.33, 2.53, 2.6]
    score, taps, valid = gt.grade([(True, t) for t in times])
    assert (score, taps, valid) == (100, 0, True)


# One suspiciously fast answer voids only that item; the rest of the paper still counts.
def test_machine_taps_void_single_item_not_whole_paper():
    # One fast tap: that item scores nothing while the rest of the paper stays valid
    results = [(True, 0.05)] + [(True, 2.0)] * 9
    score, taps, valid = gt.grade(results)
    assert (score, taps, valid) == (90, 1, True)


# Every answer landing in tens of milliseconds means the whole paper is void.
def test_mass_tapping_voids_paper():
    results = [(True, 0.01)] * 10
    score, taps, valid = gt.grade(results)
    assert taps == 10 and valid is False


# Ten wrong answers score zero and the paper is still valid, so the cheat detector cannot manufacture a pass.
def test_wrong_answers_still_fail():
    results = [(False, 5.0)] * 10
    score, taps, valid = gt.grade(results)
    assert score == 0 and valid is True


# A recent failure keeps the cooldown running, an old one has expired, and a record with no fail_ts must not lock the user out.
def test_cooldown():
    import time
    assert gt.cooldown_remaining(time.time() - 10) > 0
    assert gt.cooldown_remaining(time.time() - 1000) == 0
    assert gt.cooldown_remaining(0) == 0  # old records with no fail_ts stay compatible
