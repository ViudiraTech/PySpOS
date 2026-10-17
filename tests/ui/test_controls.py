'''
 *
 *      test_controls.py
 *      Slider, Switch and Progress: hit-testing, drag capture and keyboard.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

from vortexglass import controls, model


def _press(x, y):
    return {"type": "pointer", "phase": "press", "x": x, "y": y}


def _move(x, y):
    return {"type": "pointer", "phase": "move", "x": x, "y": y}


def _release(x, y):
    return {"type": "pointer", "phase": "release", "x": x, "y": y}


# A press inside takes the pointer and only the matching release gives it back,
# so a drag that wanders out of the rectangle keeps working.
def test_drag_survives_leaving_the_rectangle():
    slider = controls.Slider(0, 100, 0)
    slider.scene(100, 100, 200, 24)
    assert slider.handle(_press(110, 112)) is True
    assert slider.active is True and slider.value < 10
    assert slider.handle(_move(350, 400)) is True
    assert slider.value > 90
    assert slider.handle(_release(350, 400)) is True
    assert slider.active is False


# A press outside must not steal the pointer from whoever has it.
def test_press_outside_does_nothing():
    slider = controls.Slider(0, 100, 50)
    slider.scene(100, 100, 200, 24)
    assert slider.handle(_press(10, 10)) is False
    assert slider.active is False and slider.value == 50


# Keyboard follows the ARIA slider pattern: arrows step, Page keys move ten,
# Home and End jump to the ends.
def test_slider_keyboard_follows_aria():
    slider = controls.Slider(0, 100, 50, step=5)
    slider.scene(0, 0, 200, 24)
    slider.handle({"type": "key", "key": 0x01000014})     # Right
    assert slider.value == 55
    slider.handle({"type": "key", "key": 0x01000012})     # Left
    assert slider.value == 50
    slider.handle({"type": "key", "key": 0x01000017})     # PageDown: ten steps
    assert slider.value == 0
    slider.handle({"type": "key", "key": 0x01000011})     # End
    assert slider.value == 100
    slider.handle({"type": "key", "key": 0x01000010})     # Home
    assert slider.value == 0


# Values are snapped to the step and clamped to the range, whichever way they
# arrive.
def test_slider_snaps_and_clamps():
    slider = controls.Slider(-20, 19, 0, step=1)
    slider.scene(0, 0, 200, 24)
    slider.set(1000)
    assert slider.value == 19
    slider.set(-1000)
    assert slider.value == -20
    assert controls.Slider(0, 10, 3, step=0.5).value == 3


# A zero range cannot be divided, so it is refused where the mistake is made.
def test_slider_rejects_an_empty_range():
    import pytest
    with pytest.raises(ValueError, match="maximum"):
        controls.Slider(5, 5, 5)


# on_change fires only when the value really moves, so a repaint is never caused
# by setting the value it already has.
def test_on_change_fires_only_on_a_real_move():
    seen = []
    slider = controls.Slider(0, 10, 5, on_change=seen.append)
    slider.scene(0, 0, 200, 24)
    assert slider.set(5) is False
    assert seen == []
    assert slider.set(6) is True
    assert seen == [6]


# A switch applies on press: per the GNOME HIG it is for state that takes effect
# the moment you touch it.
def test_switch_toggles_on_press_and_key():
    seen = []
    switch = controls.Switch(False, on_change=seen.append)
    switch.scene(0, 0, 40, 24)
    assert switch.handle(_press(20, 12)) is True
    assert switch.value is True and seen == [True]
    switch.handle({"type": "key", "key": 0x20})            # Space
    assert switch.value is False and seen == [True, False]


# Every control draws a scene the compositor would accept, including at the
# extremes where a bar would otherwise be zero pixels wide.
def test_scenes_match_the_compositor_protocol():
    for control in (controls.Slider(0, 100, 25), controls.Slider(0, 100, 0),
                    controls.Slider(-20, 19, -20, label_width=32),
                    controls.Switch(True), controls.Switch(False),
                    controls.Progress(0.4), controls.Progress(0)):
        model.validate_scene(control.scene(10, 10, 180, 24))


# route() hands an event to the first control that claims it.
def test_route_stops_at_the_first_claim():
    slider = controls.Slider(0, 100, 0)
    switch = controls.Switch(False)
    switch.scene(200, 0, 40, 24)
    slider.scene(0, 0, 100, 24)
    assert controls.route([switch, slider], _press(50, 12)) is True
    assert slider.active is True and switch.value is False
