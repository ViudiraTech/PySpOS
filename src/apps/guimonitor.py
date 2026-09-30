"""Monitor: application-owned interface using the public VortexGlass SDK."""

from datetime import datetime
import os
from pathlib import Path
import platform
import shutil
from vortexglass.application import View, run_app
from vortexglass.drawing import button, label, rectangle


class Monitor(View):
    title, size, background = "PySpOS · System Monitor", (460, 310), "#132033ec"

    min_size = (440, 310)
    interval = 1

    def scene(self, width, _height):
        disk = shutil.disk_usage(Path.home())
        try:
            load = ", ".join(f"{value:.2f}" for value in os.getloadavg())
        except (AttributeError, OSError):
            load = "当前平台不提供"
        lines = (f"平台: {platform.system()} {platform.release()}",
                 f"逻辑 CPU: {os.cpu_count() or '?'}",
                 f"负载 1/5/15 分钟: {load}",
                 f"磁盘已用: {(disk.total - disk.free) / 2**30:.1f} GiB",
                 f"磁盘可用: {disk.free / 2**30:.1f} GiB",
                 f"更新时间: {datetime.now():%H:%M:%S}")
        items = [label(20, 16, "SYSTEM MONITOR", 14, "#9bc5e9"),
                 rectangle(16, 52, width - 32, 225, "#0b1829de", 8)]
        items.extend(label(28, 68 + index * 32, line, 15)
                     for index, line in enumerate(lines))
        return items

    def handle(self, _event):
        return False


def main(argv=None):
    run_app(Monitor, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
