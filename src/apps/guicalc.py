"""Calculator: application-owned interface using the public VortexGlass SDK."""

import ast
from decimal import Decimal, DecimalException
import operator
from vortexglass.application import View, run_app
from vortexglass.drawing import button, label, rectangle


def calculate(expression):
    if not expression or len(expression) > 64:
        raise ValueError("expression length")
    operators = {ast.Add: operator.add, ast.Sub: operator.sub,
                 ast.Mult: operator.mul, ast.Div: operator.truediv}

    def evaluate(node, depth=0):
        if depth > 12:
            raise ValueError("expression depth")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = Decimal(str(node.value))
        elif isinstance(node, ast.BinOp) and type(node.op) in operators:
            result = operators[type(node.op)](evaluate(node.left, depth + 1),
                                               evaluate(node.right, depth + 1))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            result = evaluate(node.operand, depth + 1)
            if isinstance(node.op, ast.USub):
                result = -result
        else:
            raise ValueError("unsupported expression")
        if not result.is_finite() or abs(result) > Decimal("1e100"):
            raise ValueError("result out of range")
        return result

    return format(evaluate(ast.parse(expression, mode="eval").body).normalize(), "f")


class Calculator(View):
    title, size, background = "VortexGlass · Calculator", (340, 380), "#132033ec"

    min_size = (300, 370)

    def __init__(self):
        self.expression = ""

    def scene(self, width, _height):
        items = [label(20, 16, "CALCULATOR", 12, "#8daacb"),
                 rectangle(16, 44, width - 32, 66, "#091322dc", 8),
                 label(28, 60, self.expression[-22:] or "0", 28)]
        keys = ("7", "8", "9", "/", "4", "5", "6", "*",
                "1", "2", "3", "-", "C", "0", ".", "+")
        cell = (width - 40) // 4
        for index, key in enumerate(keys):
            items.append(button(key, 16 + index % 4 * (cell + 2),
                                126 + index // 4 * 47, cell, 42, key))
        items.append(button("=", 16, 320, width - 32, 42, "=", "#2f7ca6e8"))
        return items

    def handle(self, event):
        key = event.get("target") if event["type"] == "click" else event.get("text", "")
        if event["type"] == "key" and event.get("key") in (16777220, 16777221):
            key = "="
        if key == "C":
            self.expression = ""
        elif key == "=":
            try:
                self.expression = calculate(self.expression)
            except (ValueError, SyntaxError, DecimalException):
                self.expression = "Error"
        elif key and key in "0123456789.+-*/()" and len(self.expression) < 64:
            if self.expression == "Error":
                self.expression = ""
            self.expression += key
        else:
            return False
        return True


def main(argv=None):
    run_app(Calculator, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
