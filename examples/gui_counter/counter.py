"""Run against any VortexGlass endpoint; no changes to the compositor are needed."""

from vortexglass.application import Application, View
from vortexglass.drawing import button, label


class Counter(View):
    title, size, min_size = "Independent counter", (360, 180), (320, 180)

    def __init__(self):
        self.value = 0

    def scene(self, width, height):
        return [label(24, 24, f"Count: {self.value}", 28),
                button("add", 24, 86, width - 48, 44, "Add one")]

    def handle(self, event):
        if event["type"] == "click" and event.get("target") == "add":
            self.value += 1
            return True
        return False


if __name__ == "__main__":
    with Application() as app:
        app.open(Counter())
        app.run()
