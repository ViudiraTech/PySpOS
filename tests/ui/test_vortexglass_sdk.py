"""Application-owned RGBA and input APIs are distinct from host window creation."""

import threading

import pytest

from apps.guinotes import Notes
from apps.guifiles import Files
from vortexglass.application import Application, View
from vortexglass.client import Client
from vortexglass.protocol import ProtocolError
from vortexglass.server import Server
from vortexglass.widgets import TextEditor


@pytest.fixture(params=["unix", "tcp"] if __import__("os").name != "nt" else ["tcp"])
def server(tmp_path, request):
    service = Server(tmp_path / "endpoint.json", transport=request.param)
    service.open()
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    yield service
    service.stop()
    thread.join(3)
    assert not thread.is_alive()


def test_custom_rgba_frame_is_committed_atomically_and_is_owned(server):
    with Client(server.endpoint) as app, Client(server.endpoint) as other:
        window = app.create("custom renderer", 160, 80, "#00000000",
                            min_width=160, min_height=80,
                            events=["pointer", "scroll", "focus"])
        assert {"pixel-buffer", "pointer", "scroll", "focus"} <= set(app.info["capabilities"])
        pixels = bytes((220, 20, 30, 128)) * (160 * 80)
        assert app.present_pixels(window, 160, 80, pixels)["revision"] == 1
        rendered = server.model.snapshot(window)
        assert rendered.pixels == pixels
        assert rendered.pixel_size == (160, 80)
        assert rendered.items == []
        with pytest.raises(ProtocolError, match="belong"):
            other.request("buffer_begin", window=window, width=160, height=80,
                          format="rgba8888")
        assert app.present(window, [{"type": "text", "text": "vector content"}])["revision"] == 2
        assert server.model.snapshot(window).pixels is None


def test_buffer_staging_is_atomic_sequential_and_cancellable(server):
    with Client(server.endpoint) as first, Client(server.endpoint) as second:
        window = first.create(width=160, height=80, background="#00000000")
        before = server.model.snapshot(window)
        upload = first.request("buffer_begin", window=window, width=160, height=80,
                               format="rgba8888")["buffer"]
        with pytest.raises(ProtocolError, match="incomplete"):
            first.request("buffer_commit", buffer=upload)
        with pytest.raises(ProtocolError, match="sequential"):
            first.request("buffer_write", buffer=upload, offset=1, data="AAAA")
        with pytest.raises(ProtocolError, match="belong"):
            second.request("buffer_write", buffer=upload, offset=0, data="AAAA")
        assert server.model.snapshot(window) == before
        first.request("buffer_cancel", buffer=upload)
        assert not server.model.uploads


def test_client_upload_rejects_wrong_pixels_and_cancels_a_large_staging_buffer(server):
    with Client(server.endpoint) as client:
        window = client.create(width=1600, height=1200)
        with pytest.raises(ValueError, match=r"width \* height"):
            client.present_pixels(window, 1600, 1200, b"tiny")
        upload = client.request("buffer_begin", window=window, width=1600, height=1200,
                                format="rgba8888")
        assert upload["chunk_size"] == 64 * 1024
        client.request("buffer_cancel", buffer=upload["buffer"])
        with pytest.raises(ProtocolError, match="buffer size"):
            client.request("buffer_begin", window=window, width=1400, height=1200,
                           format="rgba8888")


class SampleView(View):
    size = (160, 80)
    min_size = (160, 80)

    def __init__(self):
        self.events = []

    def handle(self, event):
        self.events.append(event)
        return False


def test_application_sdk_routes_pointer_and_scroll_to_owning_view(server):
    received = []
    with Application(server.endpoint) as app:
        one, two = SampleView(), SampleView()
        first, second = app.open(one), app.open(two)
        server.emit(server.model.snapshot(first.id).owner,
                    {"type": "pointer", "window": first.id, "phase": "move", "x": 18, "y": 22})
        server.emit(server.model.snapshot(second.id).owner,
                    {"type": "scroll", "window": second.id, "dx": 0, "dy": 120})
        for _ in range(2):
            app.dispatch(app.client.next_event(1))
        assert [event["window"] for event in one.events] == [first.id]
        assert one.events[0]["x"] == 18
        assert [event["window"] for event in two.events] == [second.id]
        assert two.events[0]["dy"] == 120


def test_text_editor_edits_cjk_text_and_undoes_by_keyboard_event():
    editor = TextEditor("你好")
    assert editor.handle({"type": "key", "name": "Enter"})
    assert editor.handle({"type": "key", "name": "!", "text": "!"})
    assert editor.content == "你好\n!"
    assert editor.handle({"type": "key", "name": "Z", "mods": ["Control"]})
    assert editor.content == "你好\n"
    editor.scene(0, 0, 300, 100)
    assert editor.cells("你好") == 4


def test_notes_save_is_atomic_and_loads_the_selected_file(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    path = isolated / "draft.txt"
    notes = Notes(path)
    assert notes.handle({"type": "key", "name": "H", "text": "H"})
    notes.handle({"type": "key", "name": "i", "text": "i"})
    assert notes.handle({"type": "key", "name": "S", "mods": ["Control"]})
    assert path.read_text(encoding="utf-8") == "Hi"
    assert Notes(path).content == "Hi"
    notes.content += "!"
    notes.handle({"type": "close"})
    assert path.read_text(encoding="utf-8") == "Hi!"
    assert sorted(item.name for item in isolated.iterdir()) == ["draft.txt"]


def test_file_browser_paginates_and_opens_text_in_an_independent_window(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    for index in range(12):
        (root / f"note-{index:02}.txt").write_text(f"note {index}", encoding="utf-8")

    class WindowOwner:
        def __init__(self):
            self.opened = []
            self.app = self

        def open(self, view, **options):
            self.opened.append((view, options))

    browser = Files(root)
    browser.window = WindowOwner()
    browser.scene(600, 300)
    assert browser.page_size == 5
    assert len(browser.scene(600, 300)) <= 32
    assert browser.handle({"type": "scroll", "dy": -120})
    assert browser.offset == browser.page_size
    assert browser.handle({"type": "click", "target": f"entry:{browser.offset}"})
    editor, options = browser.window.app.opened[0]
    assert editor.content == "note 5"
    assert options["title"] == "Notes · note-05.txt"
