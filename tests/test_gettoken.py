"""gettoken 新审核算法：分数为主 + 机器连点拦截 + 分层抽题。"""
import pathlib
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "src/apps")


def _load_gettoken():
    # gettoken.py 带有 __name__ == "__exec__" 守卫（防直接运行），
    # 这里模拟 open 命令的加载方式执行模块体。
    src = pathlib.Path("src/apps/gettoken.py").read_text(encoding="utf-8")
    ns = {"__name__": "__exec__"}
    exec(compile(src, "gettoken.py", "exec"), ns)
    return ns


_ns = _load_gettoken()


class _GT:
    def __getattr__(self, name):
        return _ns[name]


gt = _GT()


def _pool():
    return [{"question": f"q{i}", "answer": True} for i in range(30)] + [
        {"question": f"f{i}", "answer": False} for i in range(30)]


def test_balanced_sampling():
    # 分层抽题：5 真 5 假 + 乱序（修复“全蒙 y 得 79 分”漏洞）
    for _ in range(5):
        picked = gt.select_questions(_pool())
        assert len(picked) == 10
        assert sum(1 for q in picked if q["answer"] is True) == 5
        assert sum(1 for q in picked if q["answer"] is False) == 5


def test_sampling_fallback_when_pool_small():
    pool = [{"question": "only", "answer": True}]
    assert len(gt.select_questions(pool)) == 1


def test_user_case_100_points_fast_passes():
    # 用户真实案例回放：10 题全对，用时含 1.5s，最慢 3.91s，平均 2.69s
    # 旧算法：平均 <3s → 误判作弊；新算法：必须通过
    times = [3.13, 3.91, 2.33, 1.5, 2.65, 3.46, 2.45, 2.33, 2.53, 2.6]
    score, taps, valid = gt.grade([(True, t) for t in times])
    assert (score, taps, valid) == (100, 0, True)


def test_machine_taps_void_single_item_not_whole_paper():
    # 1 次连点：该题不得分，整卷仍有效
    results = [(True, 0.05)] + [(True, 2.0)] * 9
    score, taps, valid = gt.grade(results)
    assert (score, taps, valid) == (90, 1, True)


def test_mass_tapping_voids_paper():
    results = [(True, 0.01)] * 10
    score, taps, valid = gt.grade(results)
    assert taps == 10 and valid is False


def test_wrong_answers_still_fail():
    results = [(False, 5.0)] * 10
    score, taps, valid = gt.grade(results)
    assert score == 0 and valid is True


def test_cooldown():
    import time
    assert gt.cooldown_remaining(time.time() - 10) > 0
    assert gt.cooldown_remaining(time.time() - 1000) == 0
    assert gt.cooldown_remaining(0) == 0  # 兼容无 fail_ts 的旧记录
