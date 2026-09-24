"""出厂重置：6 类残留全覆盖，缺项不崩。"""
import json
import os

from common.reset import factory_reset


def _seed(root):
    os.makedirs(os.path.join(root, "etc"))
    open(os.path.join(root, "etc", "bootcfg.json"), "w").write("{}")
    open(os.path.join(root, "etc", ".oobe_done"), "w").write("x")
    os.makedirs(os.path.join(root, "etc.bak-20240101-000000"))
    os.makedirs(os.path.join(root, "slot_a", "__pycache__"))
    os.makedirs(os.path.join(root, "slot_b"))
    open(os.path.join(root, "current_slot"), "w").write("slot_b")
    os.makedirs(os.path.join(root, "ota"))
    open(os.path.join(root, "ota", "update.zip"), "w").write("z")
    bank_dir = os.path.join(root, "src", "apps")
    os.makedirs(bank_dir)
    with open(os.path.join(bank_dir, "question_bank.json"), "w") as f:
        json.dump({"questions": [{"q": 1}], "history": [{"score": 1}]}, f)
    os.makedirs(os.path.join(root, "src", "shell", "__pycache__"))
    open(os.path.join(root, "src", "shell", "x.pyc"), "w").write("p")


def test_factory_reset_clears_everything(tmp_path):
    root = str(tmp_path)
    _seed(root)
    hist = os.path.join(root, "fake_home_hist")
    open(hist, "w").write("h")
    import common.reset as reset_mod
    old = reset_mod.READLINE_HISTORY
    reset_mod.READLINE_HISTORY = hist
    try:
        report = factory_reset(root)
    finally:
        reset_mod.READLINE_HISTORY = old

    assert not os.path.exists(os.path.join(root, "etc"))
    assert not os.path.exists(os.path.join(root, "etc.bak-20240101-000000"))
    assert not os.path.exists(os.path.join(root, "slot_a"))
    assert not os.path.exists(os.path.join(root, "slot_b"))
    with open(os.path.join(root, "current_slot")) as f:
        assert f.read() == "slot_a"
    assert not os.path.exists(os.path.join(root, "ota", "update.zip"))
    with open(os.path.join(root, "src", "apps", "question_bank.json")) as f:
        bank = json.load(f)
    assert bank["history"] == [] and bank["questions"] == [{"q": 1}]
    assert not os.path.exists(hist)
    assert not os.path.exists(os.path.join(root, "src", "shell", "__pycache__"))
    assert not os.path.exists(os.path.join(root, "src", "shell", "x.pyc"))
    assert all(ok for ok, _ in report.values())


def test_factory_reset_idempotent_on_empty(tmp_path):
    report = factory_reset(str(tmp_path), include_host_history=False)
    assert all(ok for ok, _ in report.values())
    with open(os.path.join(str(tmp_path), "current_slot")) as f:
        assert f.read() == "slot_a"
