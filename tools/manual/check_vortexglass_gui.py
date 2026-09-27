'''
 *
 *      check_vortexglass_gui.py
 *      Real compositor/client process smoke test with transparent PNG captures.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys._launcher_detected = True

import forkexec
import pngcodec
import process as proc
from vortexglass.client import Client
from vortexglass.service import ServiceManager


def run():
    parser = argparse.ArgumentParser(description="VortexGlass GUI process smoke test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--theme-dir")
    parser.add_argument("--desktop", action="store_true", help="use the display (e.g. under xvfb-run)")
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    proc.boot_system()
    manager = ServiceManager()
    children = []
    try:
        status = manager.start(mode=None if options.desktop else "offscreen", theme_dir=options.theme_dir)
        result = {"service": status, "host_pid": manager.handle.pid, "ppid": manager.pcb.ppid,
                  "clients": []}
        for name in ("guicalc", "guiclock", "guicanvas"):
            image_path = options.output / f"{name}.png"
            arguments = shlex.join(["--capture", str(image_path), "--duration", "3"])
            pcb = forkexec.fork_exec(f"app:{name}.py", background=True,
                                     env={"PYSPOS_APP_ARGS": arguments})
            children.append(pcb)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with Client() as client:
                windows = client.request("status")["windows"]
            if windows == 3 and all((options.output / f"{name}.png").exists()
                                    for name in ("guicalc", "guiclock", "guicanvas")):
                break
            time.sleep(0.02)
        assert windows == 3, "three independent GUI clients must own three compositor windows"
        for pcb, name in zip(children, ("guicalc", "guiclock", "guicanvas")):
            image = pngcodec.read_png(str(options.output / f"{name}.png"))
            alpha = image.pixels[3::4]
            result["clients"].append({"name": name, "pid": pcb.pid,
                                      "size": [image.width, image.height],
                                      "alpha_min": min(alpha), "alpha_max": max(alpha)})
            assert min(alpha) < 255, f"{name} must preserve translucent pixels"
            if name == "guicanvas":
                assert min(alpha) == 0, "canvas must preserve fully transparent pixels"
            finished = proc.wait_for(pcb.pid, timeout=8)
            assert finished and finished.exit_code == 0, f"{name} failed"
        with Client() as client:
            result["remaining_windows"] = client.request("status")["windows"]
        assert result["remaining_windows"] == 0
        endpoint = manager.endpoint
        manager.stop()
        result["endpoint_removed"] = not endpoint.exists()
        assert result["endpoint_removed"]
        (options.output / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        for pcb in children:
            handle = proc._table().handles.get(pcb.pid)
            if handle and handle.is_alive():
                proc.send_signal(pcb.pid, proc.SIGTERM)
                handle.join(2)
        manager.stop()


if __name__ == "__main__":
    run()
