# VortexGlass 系统合成器

VortexGlass 是由 PySpOS 的 PID 1 启动的真实后台服务。独立应用通过本机 socket
申请窗口、提交画面和接收事件；合成器管理宿主窗口、焦点、输入与装饰，应用自己实现
界面和业务逻辑。应用不需要导入 Qt，也不需要改动合成器代码。

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

`guicalc` 提供计算器，`guiclock` 刷新本地时间，`guicanvas` 提供透明画布、鼠标绘图、撤销
与 PNG 导出；`guifiles` 支持目录浏览和分页，点击 UTF-8 文件可以在独立记事本窗口编辑，
`guinotes` 支持多行编辑、撤销和保存，`guimonitor` 查看系统状态。标题栏支持拖动、最小化、
最大化和关闭，右下角支持调整大小。`open spaceglass --window` 也使用同一 socket 服务。
`open spaceglass --render=preview.png` 保留旧的离线主题预览。

桌面后端使用 Qt 6 的 `FramelessWindowHint` 和 `WA_TranslucentBackground`，
直接以 RGBA 绘制主题和客户区，不添加宿主标题栏，也不把透明像素填成黑色。
Linux/X11 需要支持透明窗口的桌面合成器；Qt 6 的桌面功能取决于宿主系统支持。
这里的服务管理 PySpOS 应用窗口，并不替换宿主 Wayland/X11 显示服务器。

## 运行时毛玻璃与折射

玻璃边框沿用 Uinxed-Kernel 的 `wm_frost_rt` / `gfx_blur_rect` 思路：合成锐利背景和
位于当前窗口下方的 PySpOS 窗口，对固定扩展区域做半径 8 的横向、纵向整数 box blur，
再裁回玻璃区域。实现使用 NumPy 前缀和，工作量随像素数增长，不随模糊半径增长。
折射独立于反光贴图：边缘的浅透镜改变背景采样坐标，双线性插值后才覆盖原主题 PNG。
`reflection.png` 保持原尺寸并锚定屏幕横坐标，拖动时窗口从光带下经过。

处理范围为标题栏、两侧和底部的玻璃带，客户区仍由应用的 RGBA 决定，完全透明的
画布保持透明。四条玻璃带独立取上下文，避免客户区的大面积像素计算。大窗口采用
二分之一分辨率过滤，再平滑放大；这是性能近似，普通窗口使用原分辨率过滤。
纹理按场景修订号、位置和尺寸缓存，内容、位置、层叠顺序发生变化才重算，无定时轮询。

壁纸优先取 `PYSPOS_GLASS_WALLPAPER` 指定的本地图片，其次读取 Plasma 的壁纸配置；
没有可用图片时使用纯色背景。改变壁纸后重启服务。软件场景包含本服务管理的窗口，
不读取宿主其他应用的画面。Qt 的 X11/xcb 平台还会请求 KWin 对玻璃带做 GPU 背景模糊，
能否生效取决于宿主合成器及其模糊配置；原生 Wayland 平台目前使用软件场景，
不提供宿主其他应用的折射采样。

socket `snapshot` 返回可复用的透明前景 PNG，保持原 API 语义；桌面背景的玻璃效果
只在宿主窗口绘制时合成。对比图与性能检查可用：

```sh
python3 tools/manual/check_vortexglass_frost.py --output /tmp/vortexglass-frost --theme-dir /path/to/vortexglass
```

工具生成 `comparison.png` 与 `review.json`，分别检查绘制结果和完整重算、纹理缓存命中的耗时。
耗时为本机中位数，不作为跨设备 FPS 保证。GUI 依赖现在包括 `PyQt6` 和 `numpy`。

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

PySpOS 的职责划分参照成熟合成器的 client/surface 与 compositor/shell 分工：Wayland
让客户端提交自己的图像缓冲区，再由 compositor 定义窗口管理和扩展 shell 协议；VortexGlass
采用更易跨平台部署的本机 JSON socket，并提供 Python SDK。架构参考
[Wayland 的 client-rendered buffer 与 surface commit](https://wayland.freedesktop.org/docs/book/Architecture.html)、
[wlroots 的 tinywl 最小 compositor 示例](https://github.com/swaywm/wlroots/tree/master/tinywl)、
[Qt Wayland 的 compositor 与 client shell 双端协议](https://doc.qt.io/qt-6/qtwaylandcompositor-custom-shell-example.html)。
这里实现的是 VortexGlass 的 API，不是可以接入 GTK、Qt 或 `wl_surface` 的 Wayland display server。

推荐应用使用 `vortexglass.application.View` 与 `Application`：应用模块持有窗口状态，
定义 `scene()` 或自行实现 `paint()`，处理点击、键盘、指针和滚轮事件。事件含 `window`
ID，所以一个 `Application` 可以打开多扇互不相同的窗口。设置 `interval = 1` 可每秒
请求重绘；其他应用没有定时器时，事件循环会阻塞等待。低层调用者仍可直接使用 `Client`。

```python
from vortexglass.application import Application, View
from vortexglass.drawing import button, label

class Counter(View):
    title, size = "独立应用", (360, 180)
    def __init__(self): self.value = 0
    def scene(self, width, _height):
        return [label(24, 24, f"计数：{self.value}", 28),
                button("add", 24, 86, width - 48, 44, "增加")]
    def handle(self, event):
        if event["type"] == "click" and event.get("target") == "add":
            self.value += 1
            return True
        return False

with Application() as app:
    app.open(Counter())
    app.run()
```

完整的独立应用和光栅绘制样例位于 [`examples/gui_counter/`](../examples/gui_counter/)。
若需接入任意绘制库，`Surface.present_pixels()` 接受紧密排列、每像素 RGBA8888 的 bytes；
应用端自行生成像素，不限于合成器内置的矩形、文字、按钮和直线。SDK 会将 RGBA 缓冲区
切为 64 KiB 的顺序分块，全部上传完成后才原子切换当前画面。

更高级或其他语言的客户端可以直接实现下表 JSON socket 操作，无需 Python 界面层代码。

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
| `set_title` | 修改自有窗口的标题 |
| `buffer_begin` / `buffer_write` / `buffer_commit` / `buffer_cancel` | 有大小限制的 RGBA8888 分块上传；只有 `commit` 替换已显示画面 |
| `snapshot` | 取回本连接窗口的 PNG，需 Qt 后端 |

显示列表支持 `rect`、`text`、`button`、`line`；颜色格式为 `#RRGGBB` 或
`#RRGGBBAA`。文字支持 `sans-serif` 和 `monospace`。`create` 可选订阅 `pointer`、`scroll`、
`focus` 事件；事件包含 `click`、带整数 key 和可移植 `name` / `mods` 名称的 `key`、指针
`press` / `move` / `release`、滚动增量、`resize`、`state` 与 `close`。坐标相对于客户区。
每个窗口归创建它的连接所有，其他连接不能更新、销毁或截图。断开连接自动回收全部
所属窗口，关闭单个窗口不退出合成器服务。停止整个服务需要监督进程独有的控制令牌。

为限制资源占用，每条 JSON 最大 256 KiB，每个显示列表最多 256 项，每个连接最多
8 个窗口，全局最多 32 个窗口和 800 万客户区像素，每连接单笔上传及全局缓冲暂存都受
像素预算限制；慢客户端的待发送数据有 1 MiB 上限。
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
