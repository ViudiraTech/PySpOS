# PySpOS 服务管理器

`launcher.py` 首先验证 Bootloader 策略和槽位，验证通过才导入所选系统的服务管理器。
终端、验证上下文和 fastboot 请求通过引导 unit 事务完成。`hotreset_env` 用相同的管理器
启动、等待和清理真实 runtime 子进程；每次热重启重新验证上下文，失败退出码传回 launcher。
旧槽位缺少管理器时仍可使用兼容启动流程。

runtime 的声明位于 `src/units/`，启动入口是 `shell.service`：

```text
process-table.service → locale.service → oobe.service → boot-commit.service
                                                             ↓
                                                       sysinit.target
                                                        ↙          ↘
                                                   ota.service  vortexglass.service
                                                        ↘          ↙
                                                       default.target
                                                             ↓
                                                        shell.service
```

初始化、OOBE 和 OTA 状态初始化是必需服务；VortexGlass 是可选服务，失败会显示
`[FAILED]` 并释放部分启动资源，终端 shell 仍可进入。fastboot 在整个图启动前分流，
继续跳过 OOBE 与 shell。签名槽位仍只在 OOBE 成功后提交启动成功。

## 依赖与生命周期

unit 文件使用 `[Unit]` / `[Service]`，支持：

| 字段 | 行为 |
| --- | --- |
| `Description` | 状态与日志中的描述 |
| `Requires` | 一同拉起；与 `After` 配合时依赖失败阻止启动；显式停止或重启会传递到依赖方 |
| `Wants` | 一同拉起；失败不阻止本 unit 启动 |
| `After` / `Before` | 仅排序，不自动拉起目标；停止时顺序反向 |
| `Type` | `oneshot` 初始化或 `simple` 持续服务；`.target` 文件为集合目标 |
| `ExecStart` / `ExecStop` | 注册的 Python 动作名称 |

`target` 默认排在其 Requires/Wants 之后。启动前拓扑排序整个事务，排序环会在任何动作
执行前报错。已启动的 unit 不重复启动。停止时会尝试所有清理动作，不因一项失败漏掉其他项。
oneshot 的成功状态保留为 `active`，表示初始化结果仍有效。`systemctl stop shell`
让交互循环在当前命令返回后退出，随后清理其余服务。

例如 `vortexglass.service`：

```ini
[Unit]
Description=VortexGlass compositor
Requires=sysinit.target
After=sysinit.target

[Service]
Type=simple
ExecStart=vortexglass-start
ExecStop=vortexglass-stop
```

这是面向 PySpOS 的 systemd 风格子集：不执行任意宿主 shell 的 `ExecStart`，
不实现 systemd 的所有 unit 字段、并行 job 执行、enable/install、自动崩溃重启或持久 journal。
未知字段明确报错。process-backed 服务在状态查询时检查存活和协议就绪状态。

## 命令与日志

```text
systemctl list-units
systemctl status vortexglass
systemctl list-dependencies shell
systemctl restart vortexglass
service vortexglass stop
journalctl
journalctl -u vortexglass
```

省略后缀默认为 `.service`；target 需保留 `.target` 后缀。旧的 `service <unit> <action>`
语法继续可用。`status` 返回 0 表示 active、3 表示非 active，未知 unit 或操作会报错。

启动控制台打印 `[ .... ] Starting ...`、`[  OK  ] Started ...`、`[FAILED] Failed ...`
与 `[DEPEND] Required unit failed ...`。journal 保留当前 runtime 最近 2048 条结构化记录，
按 `Sep 27 20:30:00 PySpOS init[1]: unit.service: message` 格式显示。
VortexGlass 的子进程输出也带 unit 和 PID 进入 journal，停止服务后仍可查看；
热重启会创建新的 runtime journal，launcher 与监督器的状态直接打印到控制台。

## 终端输入

前台 app 的 stdin 中继只在子进程存活时拥有输入。POSIX 中继同时等待终端可读和
进程退出，并通过不预取的内核字节读取传递 UTF-8 输入；退出状态发布前停止并回收中继。
这样旧 app 不会在下一个 prompt 阻塞读取或吞掉新命令的字符。后台服务仍使用 `/dev/null`。
Windows 控制台中继使用可取消的按键读取并保留基本退格、整行和 Unicode 输入；PTY
回归覆盖 Linux 上的连续 app 退出、提前输入、中英文命令及前台 app 的交互输入。

```sh
python3 -m pytest tests/boot/test_service_manager.py tests/process/test_stdin_ownership.py -q
```

依赖语义参考 [systemd.unit](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
和 [s6-rc](https://skarnet.org/software/s6-rc/overview.html)。高性能模糊方案对照了
[KWin Dual Kawase](https://phabricator.kde.org/D9848)，折射方案对照了
[Better Blur DX](https://github.com/xarblu/kwin-effects-better-blur-dx)，软件模糊最终沿用
本机 Uinxed-Kernel 的 separable box blur。
