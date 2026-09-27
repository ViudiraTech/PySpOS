# 测试与诊断

pytest 用例按子系统归档：`boot/`（引导、签名与恢复）、`process/`（调度与子进程）、`shell/`、`formats/`、`ui/`、`apps/`、`ota/`、`common/` 与 `web/`。

```sh
python3 -m pytest -q
python3 -m pytest tests/process/ tests/shell/ -q
python3 -m pytest -m "not integration" -q
python3 -m pytest -m integration -q
python3 -m pytest tests/web/ -q
```

`integration` 标记真实子进程、本机 socket 或宿主命令测试。其余测试中也有调用应用入口的行为测试；该标记用于筛选主要的集成测试，不代表安全沙箱。没有显示环境时 Tk 交互用例会跳过，离线 PNG 渲染照常测试。

```sh
SPACEGLASS_TK_TESTS=1 xvfb-run -a python3 -m pytest tests/ui/test_spaceglass_app.py -q
```

`conftest.py` 统一启动器标志、工作目录与临时用户目录；导入路径由 pyproject.toml 配置。共用路径从 `tests.support` 导入。测试收集不运行交互式 gettoken 答题，不修改真实用户的 Shell 历史。

网站检查既由 `tests/web/test_docs.py` 收集，也可单独执行 `python3 tools/checks/check_docs_html.py` 等脚本。手工 PTY 检查位于 `tools/manual/`，不进入 pytest 自动收集。原根目录的 ELF smoke 脚本现在是 `tools/manual/check_elf.py`。

性能基准使用 `python3 tools/benchmark_runtime.py --output /tmp/pyspos-benchmark.json`。可用 `--baseline` 对比历史 JSON，用 `--process-module` 测量另一份实现。耗时取多轮中位数，不把机器速度作为 CI 断言。功能回归检查调度账本、公平性、状态唤醒与容量上限。
