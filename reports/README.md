# 改版与性能检查记录

2026-09-27，本机 Linux x86_64 / Python 3.14.7 / Chromium。

## 网页结构

首页已重写 HTML：系统分层示意 → 项目索引 → PySpOS 介绍与启动命令 → SpaceOS 8 介绍与实际运行截图 → 两行历史项目索引 → 时间线与联系。

全站功能说明使用标题与正文对齐的连续条目；版本数据使用开放的元数据行；安装步骤、代码和终端示例去掉圆角底板与阴影。没有引入前端框架，移除了远程 Google Fonts 请求。使用系统字体、共享设计 token 和静态装饰。

布局参考：[IBM Design Language](https://www.ibm.com/design/language/layout/overview/)、[GOV.UK Layout](https://design-system.service.gov.uk/styles/layout/)、[web.dev Typography](https://web.dev/learn/design/typography)。参考它们的网格、阅读宽度与字阶方法，并按现有中文内容重新组织。

浏览器检查覆盖 9 页 × 6 宽度（320 / 390 / 768 / 960 / 1024 / 1440）× 2 主题，共 108 种组合：没有页面级横向溢出、图片加载失败或 JavaScript 运行异常；主体条目没有圆角底板或阴影。另验证移动菜单与 Escape、主题跨页保存、剪贴板命令复制、减少动态效果设置。明细见 [website/review.json](website/review.json)。

截图：[首页](website/home-light.png)、[手机首页](website/home-mobile.png)、[深色首页](website/home-dark.png)、[PySpOS 详情](website/pyspos-light.png)、[手机深色下载页](website/download-mobile-dark.png)。

## 调度 tick 性能

每组 2,000 次 tick，5 轮中位数，同一台机器，任务 nice 在 -5…5 间循环。基线为编辑前保存的实现；脚本是 `tools/benchmark_runtime.py`。

| 可运行任务 | 原实现 | 优化后 | 速度比 |
| --- | ---: | ---: | ---: |
| 1 | 3.21 ms | 1.73 ms | 1.85× |
| 32 | 28.96 ms | 14.39 ms | 2.01× |
| 256 | 179.05 ms | 69.87 ms | 2.56× |
| 1024 | 717.76 ms | 275.23 ms | 2.61× |

优化维护了队列总权重和加权 vruntime 偏移，使平均虚拟时间与总权重查询不再遍历队列。最小 vruntime 使用实际参与查询的最小堆，并定期压缩失效记录；deadline 选取仍遍历可运行任务，保留现有简化 EEVDF 的选择语义。参考 [Linux EEVDF](https://docs.kernel.org/scheduler/sched-eevdf.html)，没有把该模拟实现描述为完整 Linux 调度器。

单任务运行 20,000 tick 的 tracemalloc 峰值从 2,054,562 B 降至 211,120 B，约降低 89.7%。原实现留下 6,667 条无效堆记录；优化后为 0，最近切换历史上限为 2,048 条。该数据是调度样本的分配峰值，不是完整系统 RSS。

另将编辑前与优化后的实现进行 10,000 tick 对照，交替修改 nice、阻塞、唤醒与停止/继续：选中的 PID 完全一致，平均虚拟时间在 1e-6 误差内一致。回归测试另覆盖 PID 复用、重复入队、队列账本和历史容量。

原始数据：[performance/baseline.json](performance/baseline.json)、[performance/optimized.json](performance/optimized.json)。

## 子进程等待

子进程回收从 30 / 50 ms 定时轮询改成 `multiprocessing.connection.wait` 等待进程 sentinel 与注册通知；`wait_for` 使用 Condition 与单调时钟。注册发生在成功 start 之后，并按 handle 保留身份，避免把未启动或已复用的 PID 当作旧进程。

在 0.5 秒空闲区间内，原监控线程调用 sleep 10 次，优化后为 0 次。25 个空子进程启动后至 wait_for 返回的中位数从 20.30 ms 降至 5.48 ms，p95 从 40.46 ms 降至 5.83 ms。测量包含子进程收尾与监控耗时，不包含完整应用启动，也不能换算为整个系统吞吐量。实现参考 [Python multiprocessing 的 sentinel / wait API](https://docs.python.org/3/library/multiprocessing.html)。

复现：`python3 tools/benchmark_process_events.py [源码目录]`。原始数据：[performance/events.json](performance/events.json)。

## 测试

`python3 -m pytest -q --durations=8`：371 通过，12 跳过（需显式开启的 Tk 图形交互）。现有 Python 3.14 fork 在多线程进程中的弃用警告仍会出现。Ruff 检查通过，HTML 链接/结构、设计 token、对比度、OTA 清单均通过。

测试按子系统分组，手工检查迁至 tools/manual，站点检查迁至 tools/checks 并纳入 pytest。共享启动标志和导入路径由一处配置；测试用户目录与历史路径使用临时目录；测试收集不再启动交互答题。操作说明见 [../tests/README.md](../tests/README.md)。
