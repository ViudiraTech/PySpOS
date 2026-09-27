# VortexGlass 系统合成器

VortexGlass 是由 PySpOS 的 PID 1 启动的真实后台服务。GUI 程序通过本机 socket
提交显示列表，由服务创建和绘制所有宿主窗口；客户端不导入 Qt，也不创建 Tk 根窗口。

## 安装与启动

```sh
python3 -m pip install -r requirements.txt -r requirements-gui.txt
```

精简的 Debian/Ubuntu 环境还需要 Qt 依赖的系统运行库：

```sh
sudo apt-get install libegl1 libgl1 libopengl0 libxkbcommon0 fonts-dejavu-core
```

正常启动 PySpOS 后，服务在 shell 进入命令循环前启动。`ps -a` 中可以看到
`vortexglassd` 的 `kind=service`、`ppid=1`。EOF、关机和热重启都会先停止服务并清理端点。

```text
service vortexglass status
service vortexglass restart
open guicalc &
open guiclock &
open guicanvas &
```

`guicalc` 演示按钮、键盘输入与计算；`guiclock` 每秒更新一次；`guicanvas`
演示完全透明的客户区、半透明图形、透明度按钮与鼠标点击。标题栏支持拖动、最小化、
最大化和关闭，右下角支持调整大小。`open spaceglass --window` 也使用同一 socket 服务。
`open spaceglass --render=preview.png` 保留旧的离线主题预览。

桌面后端使用 Qt 6 的 `FramelessWindowHint` 和 `WA_TranslucentBackground`，
直接以 RGBA 绘制主题和客户区，不添加宿主标题栏，也不把透明像素填成黑色。
Linux/X11 需要支持透明窗口的桌面合成器；Qt 6 的桌面功能取决于宿主系统支持。
这里的服务管理 PySpOS 应用窗口，并不替换宿主 Wayland/X11 显示服务器。

## 主题与无显示环境

主题优先使用 `VORTEXGLASS_THEME_DIR` 或系统树的 `assets/themes/vortexglass/`，
也保留原来的主题搜索规则。素材未安装时服务使用内置的半透明边框，socket 协议仍可用。
修改主题环境变量后执行 `service vortexglass restart`。

独立运行服务与客户端时，把同一个端点路径传给两者：

```sh
PYTHONPATH=src python3 -m vortexglass.daemon --endpoint /tmp/my-vortexglass/endpoint.json
PYTHONPATH=src python3 -m vortexglass.demos calc --endpoint /tmp/my-vortexglass/endpoint.json
```

无显示设备或未安装 Qt 时默认使用标准库的 headless 后端，可检查窗口生命周期、协议和事件路由。
它不创建可见窗口，不提供 PNG 截图。安装 GUI 依赖后，可以用 `--offscreen` 启动
真正的 Qt 离屏绘制后端；`--headless` 则显式选择协议后端。

```sh
PYTHONPATH=src python3 -m vortexglass.daemon --offscreen --endpoint /tmp/my-vortexglass/endpoint.json
PYTHONPATH=src python3 -m vortexglass.demos canvas --endpoint /tmp/my-vortexglass/endpoint.json --capture /tmp/canvas.png
```

`--capture` 请求服务返回 PNG，由客户端写入目标文件。加 `--duration=5` 可以截图后
继续保持窗口五秒。前台独立服务退出后会清理端点；被强制杀死时留下的端点目录应在
确认服务已经退出后移除，或使用另一个端点路径启动。

## Socket API

端点描述文件记录协议版本、transport、地址和随机连接令牌。Unix 默认使用
AF_UNIX，Windows 使用绑定 `127.0.0.1` 的 TCP；Unix 描述文件和 socket 权限均为 `0600`。
PySpOS 每次启动创建独立的临时运行目录，并把端点位置传给子进程。

```python
from vortexglass.client import Client

with Client() as gui:
    window = gui.create("Example", 480, 320, background="#00000000")
    gui.present(window, [
        {"type": "rect", "x": 24, "y": 24, "width": 200,
         "height": 120, "color": "#397aa690", "radius": 12},
        {"type": "button", "id": "hello", "x": 24, "y": 170,
         "width": 160, "height": 40, "text": "Hello"},
    ])
    while True:
        event = gui.next_event()
        if event["type"] == "close":
            break
        if event["type"] == "click" and event.get("target") == "hello":
            print("clicked")
```

协议是换行分隔的 JSON。每个请求携带整数 `id` 与 `op`，应答回传 `id`、`ok`
和 `result` 或 `error`。输入消息以 `event` 字段异步发送，可与请求应答交错。

| 操作 | 内容 |
| --- | --- |
| `hello` | 版本和令牌握手；五秒内必须完成 |
| `ping` / `status` | 查询服务状态、窗口数量与当前连接所属窗口 |
| `create` | 创建标题、尺寸和 RGBA 背景指定的窗口 |
| `present` | 原子替换显示列表，可同步修改背景色 |
| `resize` / `destroy` | 调整尺寸或销毁本连接的窗口 |
| `snapshot` | 取回本连接窗口的 PNG，需 Qt 后端 |

显示列表支持 `rect`、`text`、`button`、`line`；颜色格式为 `#RRGGBB` 或
`#RRGGBBAA`。事件包括 `click`、`key`、`resize`、`state`、`close`，坐标相对于客户区。
每个窗口归创建它的连接所有，其他连接不能更新、销毁或截图。断开连接自动回收全部
所属窗口，关闭单个窗口不退出合成器服务。停止整个服务需要监督进程独有的控制令牌。

为限制资源占用，每条 JSON 最大 256 KiB，每个显示列表最多 256 项，每个连接最多
8 个窗口，全局最多 32 个窗口和 800 万客户区像素；慢客户端的待发送数据有 1 MiB 上限。
服务用 selector 等待 socket，Qt 通过排队信号合并重绘，空闲时不轮询。

## 验证

```sh
python3 -m pytest tests/ui/test_vortexglass.py tests/ui/test_vortexglass_qt.py tests/boot/test_vortexglass_service.py -q
python3 tools/manual/check_vortexglass_gui.py --output /tmp/vortexglass-review
```

手工检查工具启动真实服务和三个真实客户端进程，保存 `guicalc.png`、`guiclock.png`、
`guicanvas.png` 与 `review.json`，检查透明像素、同时存在的三个窗口、断开回收和退出清理。
Qt 测试使用离屏平台，真实鼠标键盘事件由 QTest 送入宿主窗口再经 socket 返回客户端。
CI 安装 GUI 依赖并执行这些测试。
