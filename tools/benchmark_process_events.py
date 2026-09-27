#!/usr/bin/env python3
"""Measure idle pump wakeups and waiting for 25 empty real child processes.

Run as a standalone process: python3 tools/benchmark_process_events.py [source-dir].
The source directory must contain process.py and forkexec.py. Timings include
child finalization and monitoring after start(), not complete app startup.
"""

import importlib.util,sys,time,threading,os,json,statistics
from pathlib import Path
folder=Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "src"
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,file);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
proc=load('process',folder/'process.py');fork=load('forkexec',folder/'forkexec.py')
sleeps=[]
def profile(frame,event,arg):
 if event=='c_call' and arg is time.sleep and threading.current_thread().name=='pyspos-pump':sleeps.append(1)
threading.setprofile(profile)
fork._ensure_pump()
time.sleep(.1);start=len(sleeps);cpu=time.process_time();time.sleep(.5);idle_cpu=time.process_time()-cpu;idle_sleeps=len(sleeps)-start
latency=[]
for _ in range(25):
 table=proc._table();pcb=table.spawn('instant',remote=True);handle=fork._CTX.Process(target=os.getpid);handle.start();table.handles[pcb.pid]=handle
 t=time.perf_counter()
 if hasattr(fork,'_watch_child'):fork._watch_child(table,pcb,handle)
 result=table.wait_for(pcb.pid,3)
 assert result and result.state in proc.TERMINAL_STATES
 latency.append((time.perf_counter()-t)*1000)
 handle.join();table.reap(pcb.pid)
report={'idle_interval_s':.5,'idle_poll_sleeps':idle_sleeps,'idle_parent_cpu_ms':idle_cpu*1000,'children':25,'post_start_to_wait_median_ms':statistics.median(latency),'post_start_to_wait_p95_ms':sorted(latency)[23]}
print(json.dumps(report,indent=2))
