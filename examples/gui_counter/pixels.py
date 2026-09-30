"""An app-owned raster renderer. Drag over the surface to change the colour field."""

from vortexglass.application import Application, View


class ColourField(View):
    title, size = "Client-rendered RGBA surface", (480, 320)
    background = "#00000000"

    def __init__(self):
        self.centre = (240, 160)

    def paint(self, window):
        width, height = window.width, window.height
        cx, cy = self.centre
        pixels = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = bytes((x * 255 // width, y * 255 // height,
                                                  min(255, abs(x - cx) + abs(y - cy)), 200))
        window.present_pixels(pixels)

    def handle(self, event):
        if event["type"] == "pointer" and event.get("buttons", 0) & 1:
            self.centre = event["x"], event["y"]
            return True
        return False


if __name__ == "__main__":
    with Application() as app:
        app.open(ColourField())
        app.run()
