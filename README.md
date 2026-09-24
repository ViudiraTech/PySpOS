<div align="center">

# PySpOS

**用 Python 写的模拟操作系统** — 真子进程、EEVDF 调度器、Unicorn ELF 引擎、curses 首次开机向导。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](requirements.txt)
[![Release](https://img.shields.io/github/v/release/ViudiraTech/PySpOS?include_prereleases)](https://github.com/ViudiraTech/PySpOS/releases)
[![CI](https://github.com/ViudiraTech/PySpOS/actions/workflows/ci.yml/badge.svg)](https://github.com/ViudiraTech/PySpOS/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/ViudiraTech/PySpOS?style=social)](https://github.com/ViudiraTech/PySpOS)

[快速开始](#quickstart) · [命令速查](#commands) · [架构](#architecture) · [路线图](#roadmap) · [FAQ](#faq) · [许可](#license)

</div>

---

PySpOS 是一个教学向的**模拟操作系统**：在用户态把进程调度、内存映射、
文件系统和引导流程都实现一遍，让想理解操作系统原理的人能直接读源码改源码。
它不是能在裸机上跑的系统。

## ✨ 特性

| 领域 | 能力 | 位置 |
| --- | --- | --- |
| 调度 | EEVDF（对标 Linux 6.6+）：权重表、vruntime、虚拟截止期、信号状态机 | `src/process.py` |
| 进程 | 真子进程 fork/exec、PID 0 swapper / 1 init / 2 shell、孤儿收养、僵尸回收 | `src/forkexec.py` |
| 作业 | `cmd &` 后台、`jobs` / `fg` / `bg` / `wait`、进程组与会话 | `src/shell/proc_cmds.py` |
| 引导 | 11 步 curses OOBE 首次开机向导、真实时区（zoneinfo + TZ）、i18n | `src/oobe.py` |
| 终端 | CJK 双宽布局、控制字符净化、`stty sane` 自愈、输入重试上限 | `src/tui.py` `src/ttyutil.py` |
| ELF | 默认 Unicorn 执行真 x86 指令，syscall 转发到模拟层 | `src/elf_loader/unicorn_runner.py` |
| 配置 | SpaceConfig v2：转义、行尾注释、null、列表、Schema 校验 | `src/spc.py` |
| Shell | 元数据驱动的命令注册表、分组 help、Tab 补全、管道与重定向 | `src/commands.py` |
| OTA | A/B 槽位与本地回滚（云端维护中，默认关闭） | `src/ota.py` |

ELF 同时保留自研模拟器（`SpaceCPU 1 Pro`）作为无依赖兜底，Windows 也能跑。

<a id="quickstart"></a>

## 🚀 快速开始

前置：Python 3.10+，已在 3.10 / 3.12 / 3.14 与 Linux、macOS、Windows 上验证。

```bash
git clone https://github.com/ViudiraTech/PySpOS.git
cd PySpOS
pip install -r requirements.txt

./start.sh          # Linux / macOS
start.bat           # Windows
```

首次启动会进入 OOBE 向导（语言 / 时区 / 用户名），完成后写入
`etc/.oobe_done`，之后每次开机直接进 shell。

`unicorn` 是 ELF 的默认引擎，装不上会自动降级到自研模拟器，不影响启动。

跑测试：

```bash
python3 -m pytest tests/ -q
```

> [!NOTE]
> 开机若出现「按 Enter 疯狂刷 `^M`」，是上一次会话异常退出把终端留在了
> `icrnl` 关闭状态。手动跑 `stty sane` 即可；3.2.0 起程序已内置该自愈
> 逻辑（见 [FAQ](#终端里按-enter-会疯狂刷-m是-bug-吗)）。

<a id="commands"></a>

## 💻 命令速查

| 命令 | 说明 |
| --- | --- |
| `help` / `help <cmd>` | 分组命令表 / 单命令详情 |
| `ls` `cd` `cat` `grep` | 文件操作，支持 `cat x.txt \| grep foo` |
| `echo hi > a.txt` | 输出重定向，`>>` 追加 |
| `open gettoken` | 答题获取 bootloader 解锁 Token |
| `open getroot` | 获取 ROOT 权限，需二次确认并写审计日志 |
| `oobe` | 手动重跑首次开机向导 |
| `run <file.elf>` | 运行 ELF，`--stats` / `--map` / `--disasm N` / `--strace` 可观测 |
| `run --engine native <f>` | 强制用自研模拟器兜底 |
| `ps` `kill <pid>` `signal <pid> SIGTERM` | 进程管理与信号 |
| `<cmd> &` / `jobs` / `fg` / `bg` / `wait` | 后台作业与进程组控制 |
| `sysmon` | 版本、槽位、进程、OTA 一屏总览 |
| `spc_validate` `spc_get` `spc_set` `spc_migrate` | SpaceConfig 工具链 |
| `ota_status` / `ota_rollback` | OTA 状态与本地回滚 |
| `recovery.erase` | 真出厂重置 |

## 📋 3.2.0 更新内容

| 分类 | 变更 |
| --- | --- |
| 调度器 | EEVDF 完整实现，含 nice 权重表与信号状态机 |
| 进程 | apps 从协作式模拟升级为真子进程；PID 0/1/2 引导语义；孤儿收养与僵尸回收 |
| 作业 | 后台作业、进程组、`$!`、作业控制 |
| 引导 | OOBE 11 步向导、真实时区与语言、标记文件持久化 |
| 终端 | CJK 双宽渲染、控制字符净化、终端输入自愈与重试上限 |
| 配置 | SpaceConfig v2 解析器与 Schema 工具链 |
| ELF | 默认切换到 Unicorn 引擎 |
| Shell | `main.py` 拆分为 `src/shell/*`；命令注册表、Tab 补全、`PATH=apps/` |
| 修复 | `open` 沙箱 builtins 白名单过窄导致 apps 全线 `NameError` |
| 修复 | Pipe 端点接反、`TypeError` 语义混淆、curses 多窗口覆盖 |
| 修复 | apps 在 EOF 下无限空转（`zzlsb` 等） |
| 修复 | 子进程 stdio 中继协议不匹配导致输出丢失、后台作业挂死 |
| 整理 | 清理历史归档、统一路径解析、合并构建脚本、补 MIT License |
| 审计 | gettoken 改为分数为主、拦截机器连点、题库分层抽题 |

## 🗂️ 项目结构

```text
PySpOS/
├── launcher.py           # 槽位选择 + 终端状态恢复
├── src/
│   ├── main.py           # 入口 facade（启动状态 + 兼容重导出）
│   ├── kernel.py         # 主循环与提示符
│   ├── process.py        # PCB + EEVDF + PID 0/1/2 引导
│   ├── forkexec.py       # 真子进程引擎 + stdio 中继 + syscall RPC
│   ├── ttyutil.py        # 终端输入防御（stty sane / 归一化 / 重试上限）
│   ├── tui.py            # curses TUI（CJK 宽度、布局、字符净化）
│   ├── oobe.py           # 首次开机向导
│   ├── syslocale.py      # 时区（zoneinfo + TZ）与 i18n
│   ├── spc.py            # SpaceConfig v2
│   ├── ota.py            # OTA + A/B 槽
│   ├── btcfg.py          # Bootloader 配置与校验
│   ├── commands.py       # 命令注册表 / 补全 / PATH 解析
│   ├── elf_loader/       # ELF 解析、Unicorn 引擎、自研模拟器
│   ├── shell/            # 命令实现与分发
│   ├── common/           # paths / audit / reset
│   ├── apps/             # 应用程序
│   └── spfapps/          # SPF 脚本应用
├── splibc/               # SpLibC（C 实现，供 ELF 测试程序使用）
├── tests/                # pytest 测试（112 项）
├── build_update.py       # 唯一更新包构建入口
└── requirements.txt
```

<a id="architecture"></a>

## 🏗️ 架构速览

```text
launcher（选槽位 + stty sane）
  └─ hotreset_env（子进程热重启）
      └─ kernel.loop()
          ├─ oobe.maybe_run_oobe()   首次开机，未完成时先走向导
          └─ shell.dispatch.handle_command
              ├─ sys_cmds   help / ls / cd / open / cat
              ├─ elf_cmd    run（Unicorn → 失败降级自研引擎）
              ├─ ota_cmds   ota_*（云端开关在 pyspos.py）
              └─ proc_cmds  ps / kill / signal / jobs / fg / bg / wait
                  └─ forkexec.fork_exec()   真子进程 + stdio 中继 + RPC
                      └─ process.py  EEVDF（0 swapper / 1 init / 2 shell）
```

apps 通过 `src/apps/api.py` 以 syscall RPC 请求特权操作，避免直接触碰
父进程内存。

<a id="roadmap"></a>

## 🗺️ 路线图

- [x] OTA 更新与恢复模式
- [x] SpaceConfig 替换 json 配置
- [x] SPF 2.0 解析
- [x] 模拟进程管理与 signal（EEVDF）
- [x] ELF 加载器（支持 Windows，Unicorn 引擎）
- [x] 真子进程 fork/exec + PID 1 init 语义 + 后台作业
- [x] OOBE 首次开机向导 + 真实时区语言
- [ ] 动态链接（INTERP）与 TLS 支持
- [ ] 图形化 TUI 与 SpaceGlass 毛玻璃效果
- [ ] 可操控 PySpOS 的图形化 app（发 signal、解锁 BL 等）

<a id="faq"></a>

## ❓ FAQ

**你们的 ELF 是怎么跑的？**

在用户态模拟一台 x86_64 计算机：默认由 Unicorn Engine 执行真实 x86
指令，syscall 转发到内置模拟层；没装 unicorn 就降级到自研的 `SpaceCPU 1 Pro`。
所以 Windows 也能跑。`run --engine auto|unicorn|native` 可切换，默认 auto。

**为什么保留两个 ELF 引擎？**

Unicorn 快且语义准，自研模拟器是无依赖的教学实现（体现 OS 原理）。两者
都保留是刻意的：对照着读能看清「真实内核怎么调度」和「教科书怎么调度」
的差别。

**调度器是什么算法？**

EEVDF（Earliest Eligible Virtual Deadline First），对标 Linux 6.6+：按权重
推进 vruntime，在 `lag >= 0` 的 eligible 任务里选虚拟截止期最早者。详见
`src/process.py` 顶部注释。

**apps 是真进程还是模拟的？**

3.2.0 起是真子进程（`multiprocessing` fork 语义）。每个 app 独立 PID，
由 `process.py` 的 EEVDF 记账，孤儿被 init(1) 收养、退出后回收成僵尸再清理。

**终端里按 Enter 会疯狂刷 `^M`，是 bug 吗？**

3.2.0 前确实存在。根因是 curses 会话或子进程 `os._exit()` 跳过收尾，把
tty 留在 `icrnl` 关闭状态，回车的 `\r` 不再翻译成 `\n` 而被原样回显；
`input()` 读到 `^M` 这样的垃圾串就进入无限重试。

3.2.0 加了 `src/ttyutil.py`（`stty sane` 恢复 + 输入归一化 + 重试上限），
并在 `tui.py`、`forkexec.py`、`oobe.py` 三处退出路径都接上兜底。

**OOBE 是什么？**

Out-Of-Box Experience。检测不到 `etc/.oobe_done` 时在 `kernel.loop()` 里
跑 11 步设置，时区通过 `zoneinfo` 真实设置 `TZ`。可随时用 `oobe` 命令重跑。

**我想做在线 OTA 更新，有什么建议？**

更新包别直接放 GitHub Pages（慢），推荐用 CDN 加速。请求头一定要写
（别问为什么）。上线前务必做签名/哈希校验，并准备好失败回滚路径。

**这个项目有什么用？**

让新手理解操作系统基本操作，也供作者学习 OS 原理。再次强调：这是模拟
操作系统，不是能在裸机上跑的系统。

**代码开源吗？**

是，全部代码现已迁移到
[ViudiraTech/PySpOS](https://github.com/ViudiraTech/PySpOS)，本仓库是唯一
活跃来源。

原仓库 [GoutouStdio-cn/PySpOS](https://github.com/GoutouStdio-cn/PySpOS)
已被 owner **归档为只读**（issue 与 PR 均已关闭），仅作历史存档。
想找 3.2.0 之前的老版本，去那边的 `beta_version` / `pre_version` 两个 tag；
3.2.0 起的历史版本看本仓库的 Releases。

**代码怎么写的？**

Python 为主，另有部分 C（`splibc/` 里的 ELF 测试程序）。核心代码在 `src/`。

## 🌐 在线访问

- 官网：<https://viudiratech.rainyland.top>
- OTA 更新地址（维护中）：<https://viudiratech.rainyland.top/ota/>

## 🖥️ 支持系统

Windows 7 及以上、Linux 各发行版、macOS。兼容性上更推荐 Windows。

## 🙏 贡献者

- ViudiraTech
- 王俊X
- 陈X

<a id="license"></a>

## 📄 许可

[MIT License](LICENSE) © 2022-2026 GoutouStdio
