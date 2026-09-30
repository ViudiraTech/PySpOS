"""Optional client-side display-list helpers. No GUI toolkit is required."""


def label(x, y, value, size=16, color="#e6edf3"):
    return {"type": "text", "x": x, "y": y, "text": str(value), "size": size, "color": color}


def rectangle(x, y, width, height, color, radius=0):
    return {"type": "rect", "x": x, "y": y, "width": width, "height": height,
            "color": color, "radius": radius}


def button(target, x, y, width, height, value, color="#30465fdc"):
    return {"type": "button", "id": target, "x": x, "y": y, "width": width,
            "height": height, "text": value, "color": color, "size": 18, "radius": 6}


def line(x, y, x2, y2, color="#e6edf3", width=1):
    return {"type": "line", "x": x, "y": y, "x2": x2, "y2": y2,
            "color": color, "width": width}
