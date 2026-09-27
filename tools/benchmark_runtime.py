#!/usr/bin/env python3
"""Repeatable scheduler timing and retained-memory benchmark (no hard time gates)."""

import argparse
import importlib.util
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path


def load_process(path):
    spec = importlib.util.spec_from_file_location("benchmark_process", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def measure(module, counts, ticks, repeats):
    results = []
    for count in counts:
        samples = []
        for _ in range(repeats):
            rq = module.EEVDFRunQueue()
            for i in range(count):
                rq.enqueue(module.PCB(pid=i + 3, comm="bench", nice=(i % 11) - 5))
            rq.tick(0)
            start = time.perf_counter()
            for _ in range(ticks):
                rq.tick(1)
            samples.append(time.perf_counter() - start)
        results.append({
            "tasks": count, "ticks": ticks,
            "median_s": statistics.median(samples),
            "heap_entries": len(rq._heap), "timeline_entries": len(rq.timeline),
        })
    rq = module.EEVDFRunQueue()
    rq.enqueue(module.PCB(pid=3, comm="solo"))
    rq.tick(0)
    tracemalloc.start()
    for _ in range(20000):
        rq.tick(10)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "scheduler": results,
        "retained_heap_entries_20k": len(rq._heap),
        "retained_timeline_entries_20k": len(rq.timeline),
        "trace_peak_bytes_20k": peak,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-module", type=Path,
                        default=Path(__file__).resolve().parents[1] / "src/process.py")
    parser.add_argument("--tasks", type=int, nargs="+", default=[1, 32, 256, 1024])
    parser.add_argument("--ticks", type=int, default=2000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min([*args.tasks, args.ticks, args.repeats]) < 1:
        parser.error("tasks, ticks and repeats must be positive")
    report = measure(load_process(args.process_module), args.tasks, args.ticks, args.repeats)
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        old = {(row["tasks"], row["ticks"]): row for row in baseline["scheduler"]}
        for row in report["scheduler"]:
            previous = old.get((row["tasks"], row["ticks"]))
            if previous:
                row["speedup"] = previous["median_s"] / row["median_s"]
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(content, end="")


if __name__ == "__main__":
    main()
