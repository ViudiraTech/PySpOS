# PySpOS 3.2.0 模拟操作系统

<span style="color:cyan">***这是一个使用 Python 制作的模拟操作系统，方便让新手理解操作系统基本操作。***</span>

## 当前版本

- 📦 **版本**: v3.2.0 (RC 1，预发布)
- 📅 **发布日期**: 2026-09-24
- ⚠ **注意**: RC 阶段功能已冻结、以修 bug 为主；3.1.0 正式版仍可从 OTA 地址获取。
- 🧪 **测试**: `pytest tests/` 42 项全绿（EEVDF / SPC / OTA 降级 / shell / ELF 双引擎 / SPF / gettoken 审核）

## 3.2.0 更新内容

- 🧠 **EEVDF 调度器**（`src/process.py`）：对标 Linux 6.6+ 的 Earliest Eligible Virtual Deadline First，含完整 PCB、nice 权重表、虚拟截止期与信号状态机
- ⚡ **ELF 默认换 Unicorn 引擎**（`src/elf_loader/unicorn_runner.py`）：真 x86 语义；自研 CPU 模拟器保留为兜底
- 🪟 **修 `open` 沙箱**：修复 apps 因 builtins 白名单过窄而全线 `NameError` 的历史 bug
- 🧩 **`main.py` 拆分**：1217 行单体拆为 `src/shell/*` 包，`main.py` 保留兼容 facade
- 🚦 **Shell 补齐**：`pwd/whoami/cat/grep/mkdir/touch/cp/mv/history/ps/kill/signal/sysmon`，支持 `>` `>>` 重定向与 `cat | grep` 管道、readline 历史
- 📦 **SpaceConfig v2**（`.spc`）：转义、行尾注释、`null`、列表类型 + Schema 校验 + `spc_validate/get/set/migrate`
- 🛡️ **gettoken 审核重写**：分数为主、速度不再定罪；拦截机器连点；题库分层抽题修复"全蒙 y 得 79 分"漏洞
- ⛔ **OTA 临时禁用**：服务器维护中（本地安装/回滚不受影响），开关见 `src/pyspos.py: OTA_ENABLED`
- 🧹 清理历史代码归档、统一路径解析、构建脚本合并、补 MIT License 与依赖清单

## 3.1.0 更新内容

- 添加 ELF 运行功能（Windows 也可以跑）
- 优化网页
- 使用部分 C 代码写 ELF 程序（`splibc/`）

## 快速开始

```bash
git clone https://github.com/ViudiraTech/PySpOS.git
cd PySpOS

# 依赖：unicorn 是 ELF 默认引擎，缺失会自动降级到自研模拟器
pip install -r requirements.txt

# 启动
./start.sh            # Linux / macOS
start.bat             # Windows
```

## 在线访问

- 🌐 **官方网站**: <https://viudiratech.rainyland.top>
- 📦 **OTA 更新地址**（维护中）: <https://viudiratech.rainyland.top/ota/>

## 支持系统

- Windows 7 及以上
- Linux 各种发行版
- macOS

⚠ 这里更推荐使用 Windows 运行，兼容性会更好。

## 常用命令速查

| 命令 | 说明 |
| --- | --- |
| `help` | 全部命令 |
| `ls` / `cd` / `cat` / `grep` | 文件操作（支持 `cat x.txt \| grep foo`） |
| `echo hi > a.txt` | 输出重定向（`>>` 追加） |
| `open gettoken` | 通过答题获取 bootloader 解锁 Token |
| `open getroot` | 获取 ROOT 权限（需二次确认，写审计日志） |
| `run <file.elf>` | 运行 ELF；`--stats/--map/--disasm N/--strace` 可观测 |
| `run --engine native <file.elf>` | 强制使用自研 CPU 模拟器兜底 |
| `ps` / `kill <pid>` / `signal <pid> SIGTERM` | 模拟进程管理与信号 |
| `sysmon` | 版本/槽位/进程/OTA 一屏总览 |
| `spc_validate` / `spc_get` / `spc_set` / `spc_migrate` | SpaceConfig 工具链 |
| `ota_status` / `ota_rollback` | OTA 状态与本地回滚 |

## 项目结构（3.2.0）

```
PySpOS/
├── src/
│   ├── main.py            # 入口 facade（仅启动状态 + 兼容重导出）
│   ├── kernel.py          # 主循环与提示符
│   ├── process.py         # PCB + EEVDF 调度器
│   ├── spc.py             # SpaceConfig v2 解析/Schema
│   ├── ota.py             # OTA + A/B 槽（云端当前禁用）
│   ├── btcfg.py           # Bootloader 配置与校验
│   ├── elf_loader/        # ELF 解析/加载/Unicorn 引擎/自研模拟器
│   ├── shell/             # 命令实现与分发（sys/elf/ota/proc/dispatch）
│   ├── apps/              # 应用程序（含 gettoken/getroot/unlock…）
│   └── spfapps/           # SPF 脚本应用
├── splibc/                # SpLibC（C 实现，供 ELF 测试程序使用）
├── tests/                 # pytest 测试
├── build_update.py        # 唯一更新包构建入口
└── requirements.txt
```

## 架构速览

```
launcher(选槽位) → hotreset_env(子进程热重启) → kernel.loop()
  → shell.dispatch.handle_command
      ├─ sys_cmds   (help/ls/cd/open/cat/…)
      ├─ elf_cmd    (run: Unicorn → 失败自动降级自研引擎)
      ├─ ota_cmds   (ota_*，云端开关在 pyspos.py)
      └─ proc_cmds  (ps/kill/signal/sysmon → process.py EEVDF)
```

## TODOS

- [x] 实现 OTA 更新（从云端拉取更新）
- [x] 实现一个简易的恢复模式
- [ ] 实现 SpaceGlass 毛玻璃效果（666SpaceOS6 都没上，先给这个小玩意上）
- [x] 把 json 配置文件改成我们的 spc 格式（SpaceConfig）
- [x] 移植 spf 解析（SPF 2.0：变量/算术/输入/引入）
- [x] 实现模拟进程管理，并实现 signal（EEVDF 调度）
- [ ] 实现一个图形化的 app，可以操控 PySpOS（比如可以发 signal，解锁 BL 之类的）
- [x] 实现一个 ELF 加载器（支持 Windows，Unicorn 引擎）
- [ ] 动态链接（INTERP）与 TLS 支持
- [ ] 真正的后台/并发进程（当前为协作式教学模型）

## FAQ

- Q: 你们这个 ELF 是怎么跑的？
  - A: 通过在用户态模拟一台 x86\_64 计算机来运行：默认由 **Unicorn Engine** 执行真实 x86 指令，syscall 转发到内置的模拟层；若环境没装 unicorn，会自动降级到本项目自研的 CPU 模拟器（`SpaceCPU 1 Pro`）。因此 Windows 也能跑。
- Q: 为什么同时保留两个 ELF 引擎？
  - A: Unicorn 快且语义准，自研模拟器是无依赖的教学实现（体现 OS 原理）。`run --engine auto|unicorn|native` 可选，默认 auto。
- Q: 你们的调度器是什么算法？
  - A: EEVDF（Earliest Eligible Virtual Deadline First），对标 Linux 6.6+：按权重推进 vruntime，`lag >= 0` 的 eligible 任务中选虚拟截止期最早者；详见 `src/process.py` 顶部注释。
- Q: 你们为什么没有开源协议？
  - A: 3.2.0 起采用 **MIT License**（见仓库根目录 `LICENSE`）。
- Q: 你们这个项目有什么用？
  - A: 让新手理解操作系统基本操作，也供作者学习操作系统原理。注意这是模拟操作系统，不是能在裸机上跑的系统。
- Q: 你们的代码是开源的吗？
  - A: 是的，当前代码见 [ViudiraTech/PySpOS](https://github.com/ViudiraTech/PySpOS)；3.1.0 及之前的原始版本保留在 [GoutouStdio-cn/PySpOS](https://github.com/GoutouStdio-cn/PySpOS)。
- Q: 你们的代码是怎么写的？
  - A: Python 为主，另有部分 C（用于 `splibc/` 的 ELF 测试程序），核心代码在 `src/` 目录。
- Q: 我也想写在线 OTA 更新，能给我点建议吗？
  - A: 可以参考我们的代码。更新包别直接放 GitHub Pages（慢），推荐用 CDN 加速；**一定要写请求头**（别问我为什么）；上线前务必做签名/哈希校验和失败回滚路径。

## 贡献者

- GoutouStdio-cn / ViudiraTech
- 王俊X（我同学）
- 陈X（我同学）
