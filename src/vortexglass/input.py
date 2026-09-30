"""Toolkit-independent names, alongside the v1 numeric key compatibility fields."""

KEYS = {16777216: "Escape", 16777217: "Tab", 16777219: "Backspace",
        16777220: "Enter", 16777221: "Enter", 16777223: "Delete",
        16777232: "Home", 16777233: "End", 16777234: "Left",
        16777235: "Up", 16777236: "Right", 16777237: "Down",
        16777238: "PageUp", 16777239: "PageDown"}


def key_event(key, text, modifiers):
    return {"type": "key", "key": key, "text": text, "modifiers": modifiers,
            "name": KEYS.get(key, chr(key) if 32 <= key <= 126 else ""),
            "mods": [name for flag, name in ((0x02000000, "Shift"), (0x04000000, "Control"),
                                             (0x08000000, "Alt"), (0x10000000, "Meta"))
                     if modifiers & flag]}
