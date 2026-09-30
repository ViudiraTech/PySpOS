"""Clock: application-owned interface using the public VortexGlass SDK."""

from datetime import datetime
from vortexglass.application import View, run_app
from vortexglass.drawing import button, label, rectangle


class Clock(View):
    title, size, background = "VortexGlass · Clock", (440, 190), "#142136a8"

    min_size = (380, 190)
    interval = 1

    def scene(self, width, _height):
        now = datetime.now()
        return [label(24, 18, "SYSTEM CLOCK", 12, "#a7bfd9"),
                label(24, 48, now.strftime("%H:%M:%S"), 54),
                label(26, 120, now.strftime("%A, %Y-%m-%d"), 17),
                button("close", width - 106, 145, 80, 30, "Close")]

    def handle(self, _event):
        return False


def main(argv=None):
    run_app(Clock, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
