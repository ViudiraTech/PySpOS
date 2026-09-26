'''
 *
 *      elf_runner.py
 *      Drives a loaded ELF program on the CPU emulator.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
import logging
import time

from .elf_parser import ELFParser
from .elf_loader import (
    ELFLoader, LoadedSegment, MemoryRegion,
    ELFLoaderError, MemoryAccessError
)
from .cpu_emulator import CPUEmulator, SyscallInterrupt
from .syscall_emulator import SyscallEmulator

logger = logging.getLogger(__name__)


# What one run of a guest program produced.
@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    instruction_count: int = 0
    execution_time: float = 0.0
    memory_usage: int = 0
    signal: int = 0
    fault_addr: int = 0
    
# Summarise the run for logging.
    def __str__(self) -> str:
        return (f"ExecutionResult(exit_code={self.exit_code}, "
                f"instructions={self.instruction_count}, "
                f"time={self.execution_time:.3f}s)")


# Counts collected while the ELF file was being loaded.
@dataclass
class LoaderStats:
    segments_loaded: int = 0
    symbols_resolved: int = 0
    relocations_applied: int = 0
    init_functions: int = 0
    fini_functions: int = 0
    memory_regions: int = 0
    load_time: float = 0.0


# Own the whole pipeline: parse, load, emulate, emulate syscalls, report.
class ELFRunner:
    
# Record the path and the options; nothing is read from disk yet.
    def __init__(self, elf_path: str, base_addr: Optional[int] = None,
                 enable_aslr: bool = False, strict_mode: bool = True):
        self.elf_path = elf_path
        self.base_addr = base_addr
        self.enable_aslr = enable_aslr
        self.strict_mode = strict_mode
        
        self.parser: Optional[ELFParser] = None
        self.loader: Optional[ELFLoader] = None
        self.cpu: Optional[CPUEmulator] = None
        self.syscall_emulator: Optional[SyscallEmulator] = None
        
        self.is_loaded = False
        self.is_running = False
        self.is_initialized = False
        
        self.stdout_buffer: List[str] = []
        self.stderr_buffer: List[str] = []
        
        self.custom_syscall_handlers: Dict[int, Callable] = {}
        self.symbol_hooks: Dict[str, Callable] = {}
        
        self.stats = LoaderStats()
        
        self._breakpoints: set = set()
        self._watchpoints: Dict[int, int] = {}
        self._debug_mode = False
    
# Read, parse and load the file, then build the syscall emulator and the CPU.
    def load(self) -> bool:
        if self.is_loaded:
            return True
        
        load_start = time.time()
        
        try:
            with open(self.elf_path, 'rb') as f:
                data = f.read()
            
            self.parser = ELFParser(data)
            
            if not self.parser.parse():
                logger.error(f"Failed to parse ELF file: {self.elf_path}")
                return False
            
            from .elf_constants import ELFType, ELFMachine
            header = self.parser.header
            
            if header.e_type not in (ELFType.ET_EXEC, ELFType.ET_DYN):
                logger.error(f"Unsupported ELF type: {header.e_type}")
                return False
            
            if header.e_machine not in (ELFMachine.EM_386, ELFMachine.EM_X86_64):
                logger.error(f"Unsupported architecture: {header.e_machine}")
                return False
            
            self.loader = ELFLoader(
                self.parser, 
                self.base_addr,
                enable_aslr=self.enable_aslr,
                strict_protection=self.strict_mode
            )
            
            self.loader.load()
            
            self.stats.segments_loaded = len(self.loader.segments)
            self.stats.symbols_resolved = len(self.loader.symbols)
            self.stats.init_functions = len(self.loader.init_functions)
            self.stats.fini_functions = len(self.loader.fini_functions)
            self.stats.memory_regions = len(self.loader.memory)
            
            self.syscall_emulator = SyscallEmulator(self.loader)
            self._setup_output_capture()
            
            self.cpu = CPUEmulator(self.loader, self._handle_syscall)
            
            self.stats.load_time = time.time() - load_start
            self.is_loaded = True
            
            logger.info(f"ELF loaded: {self.elf_path}")
            logger.info(f"  Entry: 0x{self.loader.entry_point:x}")
            logger.info(f"  Arch: {'x86_64' if not self.parser.is_32bit else 'i386'}")
            logger.info(f"  Base: 0x{self.loader.base_addr:x}")
            logger.info(f"  Segments: {self.stats.segments_loaded}")
            logger.info(f"  Symbols: {self.stats.symbols_resolved}")
            logger.info(f"  Load time: {self.stats.load_time:.3f}s")
            
            return True
            
        except FileNotFoundError:
            logger.error(f"ELF file not found: {self.elf_path}")
            return False
        except ELFLoaderError as e:
            logger.error(f"ELF loader error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading ELF file: {e}")
            return False
    
# Reserved hook for redirecting guest output; it does nothing.
    def _setup_output_capture(self) -> None:
        pass
    
# Dispatch a syscall to a registered handler, else to the emulator.
    def _handle_syscall(self, number: int, *args) -> int:
        if number in self.custom_syscall_handlers:
            return self.custom_syscall_handlers[number](*args)
        
        return self.syscall_emulator.handle_syscall(number, *args)
    
# Run the init functions once the image is loaded.
    def initialize(self) -> bool:
        if not self.is_loaded:
            return False
        
        if self.is_initialized:
            return True
        
        self.loader.run_init_functions(self.cpu)
        self.is_initialized = True
        
        return True
    
# Run the guest to completion and report what it did.
    def run(self, 
            argv: Optional[List[str]] = None,
            envp: Optional[Dict[str, str]] = None,
            max_instructions: Optional[int] = None) -> ExecutionResult:
        
        if not self.is_loaded:
            if not self.load():
                return ExecutionResult(
                    exit_code=-1,
                    stderr="Failed to load ELF file"
                )
        
        if argv is None:
            argv = [self.elf_path]
        
        if envp is None:
            import os
            envp = dict(os.environ)
        
        self.syscall_emulator.stdout_buffer.clear()
        self.syscall_emulator.stderr_buffer.clear()
        
        sp, argc = self.loader.setup_argv_envp(argv, envp)
        
        self.cpu.set_argv_envp(argv, envp)
        
        self.initialize()
        
        self.is_running = True
        start_time = time.time()
        exit_code = 0
        signal = 0
        fault_addr = 0
        
        try:
            exit_code = self.cpu.run(max_instructions)
        except SystemExit as e:
            exit_code = e.code if e.code is not None else 0
        except MemoryAccessError as e:
            logger.error(f"Memory access error: {e}")
            exit_code = -11
            signal = 11
        except SyscallInterrupt as e:
            result = self._handle_syscall(e.number, *e.syscall_args)
            self.cpu._set_reg(0, result)
        except Exception as e:
            logger.error(f"Execution error: {e}")
            exit_code = -1
        finally:
            self.is_running = False
        
        execution_time = time.time() - start_time
        
        self._run_fini_handlers()
        
        stdout_text = b''.join(self.syscall_emulator.stdout_buffer).decode('utf-8', errors='replace')
        stderr_text = b''.join(self.syscall_emulator.stderr_buffer).decode('utf-8', errors='replace')
        
        result = ExecutionResult(
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            instruction_count=self.cpu.instruction_count,
            execution_time=execution_time,
            memory_usage=self._calculate_memory_usage(),
            signal=signal,
            fault_addr=fault_addr
        )
        
        logger.info(f"Execution completed: {result}")
        
        return result
    
# Let the loader walk the fini functions once the program has stopped.
    def _run_fini_handlers(self) -> None:
        if self.loader:
            self.loader.run_fini_functions(self.cpu)
    
# Return the total number of bytes held by the mapped regions.
    def _calculate_memory_usage(self) -> int:
        if not self.loader:
            return 0
        
        total = 0
        for region in self.loader.memory.values():
            total += len(region.data)
        return total
    
# Execute one instruction; False means the program should stop.
    def step(self) -> bool:
        if not self.is_loaded:
            return False
        
        try:
            ip = self.cpu._get_ip()
            
            if self._debug_mode and ip in self._breakpoints:
                logger.info(f"Breakpoint hit at 0x{ip:x}")
                return False
            
            name, length, operands = self.cpu.decoder.decode(self.cpu.memory, ip)
            result = self.cpu._execute(name, length, operands)
            self.cpu.instruction_count += 1
            
            if self._debug_mode:
                self._check_watchpoints()
            
            return result != 'exit'
        except SyscallInterrupt as e:
            result = self._handle_syscall(e.number, *e.syscall_args)
            self.cpu._set_reg(0, result)
            return True
        except SystemExit:
            return False
        except Exception as e:
            logger.error(f"Step error: {e}")
            return False
    
# Return the watchpoints whose value changed, re-arming each one.
    def _check_watchpoints(self) -> List[Tuple[int, int, int]]:
        triggered = []
        for addr, original in self._watchpoints.items():
            try:
                current = self.cpu.memory.read_dword(addr)
                if current != original:
                    triggered.append((addr, original, current))
                    self._watchpoints[addr] = current
                    logger.info(f"Watchpoint at 0x{addr:x}: 0x{original:x} -> 0x{current:x}")
            except:
                pass
        return triggered
    
# Return a snapshot of the runner and the CPU state.
    def get_state(self) -> Dict[str, Any]:
        if not self.cpu:
            return {}
        
        return {
            'loaded': self.is_loaded,
            'running': self.is_running,
            'initialized': self.is_initialized,
            'cpu': self.cpu.get_state(),
            'memory_regions': len(self.loader.memory) if self.loader else 0,
            'instruction_count': self.cpu.instruction_count,
            'stats': self.stats,
        }
    
# Override one syscall number with a Python callable.
    def register_syscall_handler(self, number: int, handler: Callable) -> None:
        self.custom_syscall_handlers[number] = handler
    
# Record a hook for a symbol name; nothing consumes it yet.
    def register_symbol_hook(self, name: str, handler: Callable) -> None:
        self.symbol_hooks[name] = handler
        if self.loader and name in self.loader.symbols:
            pass
    
# Set the data the guest will read from stdin.
    def set_stdin(self, data: str) -> None:
        if self.syscall_emulator:
            self.syscall_emulator.stdin = data
    
# Return everything the guest has written to stdout.
    def get_stdout(self) -> str:
        return b''.join(self.syscall_emulator.stdout_buffer).decode('utf-8', errors='replace')
    
# Return everything the guest has written to stderr.
    def get_stderr(self) -> str:
        return b''.join(self.syscall_emulator.stderr_buffer).decode('utf-8', errors='replace')
    
# Return size bytes of guest memory, from the entry point by default.
    def dump_memory(self, addr: Optional[int] = None, size: int = 256) -> bytes:
        if not self.cpu:
            return b''
        
        if addr is None:
            addr = self.loader.entry_point if self.loader else 0
        
        try:
            return self.cpu.memory.read_bytes(addr, size)
        except Exception as e:
            logger.error(f"Memory dump error: {e}")
            return b''
    
# Return the CPU registers keyed by name for the current width.
    def dump_registers(self) -> Dict[str, int]:
        if not self.cpu:
            return {}
        
        state = self.cpu.get_state()
        registers = state.get('registers', {})
        
        result = {}
        is_64bit = state.get('is_64bit', True)
        
        if is_64bit:
            reg_names = ['RAX', 'RCX', 'RDX', 'RBX', 'RSP', 'RBP', 'RSI', 'RDI',
                        'R8', 'R9', 'R10', 'R11', 'R12', 'R13', 'R14', 'R15',
                        'RIP', 'RFLAGS']
        else:
            reg_names = ['EAX', 'ECX', 'EDX', 'EBX', 'ESP', 'EBP', 'ESI', 'EDI',
                        'EIP', 'EFLAGS']
        
        for i, name in enumerate(reg_names):
            if i in registers:
                result[name] = registers[i]
        
        return result
    
# Return (address, mnemonic, length, operands) for count instructions.
    def disassemble(self, addr: Optional[int] = None, 
                   count: int = 10) -> List[Tuple[int, str, int, List]]:
        if not self.cpu:
            return []
        
        if addr is None:
            addr = self.cpu._get_ip()
        
        result = []
        current_addr = addr
        
        for _ in range(count):
            try:
                name, length, operands = self.cpu.decoder.decode(
                    self.cpu.memory, current_addr
                )
                result.append((current_addr, name, length, operands))
                current_addr += length
            except Exception:
                break
        
        return result
    
# Return (start, size, name, rwx) per region, sorted by address.
    def get_memory_map(self) -> List[Tuple[int, int, str, str]]:
        if not self.loader:
            return []
        
        result = []
        for start, region in self.loader.memory.items():
            perms = ''
            perms += 'r' if region.readable else '-'
            perms += 'w' if region.writable else '-'
            perms += 'x' if region.executable else '-'
            result.append((start, region.size, region.name, perms))
        
        return sorted(result, key=lambda x: x[0])
    
# Return a symbol's address, or None.
    def get_symbol(self, name: str) -> Optional[int]:
        if not self.loader:
            return None
        return self.loader.resolve_symbol(name)
    
# Return the name of the symbol at addr, or None.
    def get_symbol_at(self, addr: int) -> Optional[str]:
        if not self.loader:
            return None
        return self.loader.get_symbol_at(addr)
    
# Stop at addr; this also turns debug mode on.
    def add_breakpoint(self, addr: int) -> None:
        self._breakpoints.add(addr)
        self._debug_mode = True
        logger.info(f"Breakpoint added at 0x{addr:x}")
    
# Forget the breakpoint at addr.
    def remove_breakpoint(self, addr: int) -> None:
        self._breakpoints.discard(addr)
        logger.info(f"Breakpoint removed at 0x{addr:x}")
    
# Report the dword at addr whenever it changes.
    def add_watchpoint(self, addr: int) -> None:
        try:
            original = self.cpu.memory.read_dword(addr)
            self._watchpoints[addr] = original
            self._debug_mode = True
            logger.info(f"Watchpoint added at 0x{addr:x}")
        except Exception as e:
            logger.error(f"Failed to add watchpoint: {e}")
    
# Forget the watchpoint at addr.
    def remove_watchpoint(self, addr: int) -> None:
        self._watchpoints.pop(addr, None)
        logger.info(f"Watchpoint removed at 0x{addr:x}")


# Load and run an ELF file in one call.
def run_elf(elf_path: str,
            argv: Optional[List[str]] = None,
            envp: Optional[Dict[str, str]] = None,
            max_instructions: Optional[int] = None,
            base_addr: Optional[int] = None,
            enable_aslr: bool = False) -> ExecutionResult:
    
    runner = ELFRunner(elf_path, base_addr, enable_aslr=enable_aslr)
    return runner.run(argv, envp, max_instructions)


# Step-at-a-time driver sitting on top of an ELFRunner.
class ELFDebugger:
    
# Wrap a runner and start with an empty breakpoint set.
    def __init__(self, runner: ELFRunner):
        self.runner = runner
        self.breakpoints: set = set()
        self.watchpoints: Dict[int, int] = {}
        self.is_debugging = False
        self.history: List[Dict] = []
        self.max_history = 1000
    
# Add a breakpoint here and on the runner.
    def add_breakpoint(self, addr: int) -> None:
        self.breakpoints.add(addr)
        self.runner.add_breakpoint(addr)
    
# Remove a breakpoint from here and from the runner.
    def remove_breakpoint(self, addr: int) -> None:
        self.breakpoints.discard(addr)
        self.runner.remove_breakpoint(addr)
    
# Add a watchpoint on the runner.
    def add_watchpoint(self, addr: int) -> None:
        self.runner.add_watchpoint(addr)
    
# Remove a watchpoint from the runner.
    def remove_watchpoint(self, addr: int) -> None:
        self.runner.remove_watchpoint(addr)
    
# Step until a breakpoint or the instruction cap, printing at every stop.
    def run_with_debugging(self, 
                          argv: Optional[List[str]] = None,
                          envp: Optional[Dict[str, str]] = None,
                          max_instructions: Optional[int] = None) -> ExecutionResult:
        
        if not self.runner.is_loaded:
            if not self.runner.load():
                return ExecutionResult(exit_code=-1)
        
        if argv is None:
            argv = [self.runner.elf_path]
        if envp is None:
            import os
            envp = dict(os.environ)
        
        self.runner.cpu.set_argv_envp(argv, envp)
        self.runner.initialize()
        
        self.is_debugging = True
        instruction_count = 0
        
        try:
            while True:
                ip = self.runner.cpu._get_ip()
                
                if ip in self.breakpoints:
                    logger.info(f"Breakpoint hit at 0x{ip:x}")
                    self._debug_prompt()
                
                self.history.append({
                    'ip': ip,
                    'registers': dict(self.runner.cpu.state.regs),
                })
                if len(self.history) > self.max_history:
                    self.history.pop(0)
                
                if not self.runner.step():
                    break
                
                instruction_count += 1
                
                if max_instructions and instruction_count >= max_instructions:
                    logger.info(f"Max instructions reached: {max_instructions}")
                    break
                
                if instruction_count % 10000 == 0:
                    logger.debug(f"Executed {instruction_count} instructions")
        
        except Exception as e:
            logger.error(f"Debug execution error: {e}")
        finally:
            self.is_debugging = False
        
        return ExecutionResult(
            exit_code=self.runner.cpu._get_reg(0),
            stdout=self.runner.get_stdout(),
            stderr=self.runner.get_stderr(),
            instruction_count=instruction_count
        )
    
# Print the registers and the next instruction at a breakpoint.
    def _debug_prompt(self) -> None:
        regs = self.runner.dump_registers()
        ip = regs.get('RIP', regs.get('EIP', 0))
        
        print(f"\n=== Debug Break at 0x{ip:x} ===")
        print("Registers:")
        for name, value in list(regs.items())[:8]:
            print(f"  {name}: 0x{value:016x}")
        
        disasm = self.runner.disassemble(ip, 1)
        if disasm:
            addr, name, length, operands = disasm[0]
            print(f"\nNext: {name} at 0x{addr:x}")
        
        print("================================\n")
    
# Execute one instruction, descending into calls.
    def step_into(self) -> bool:
        return self.runner.step()
    
# Run through a call by breaking on the instruction that follows it.
    def step_over(self) -> bool:
        ip = self.runner.cpu._get_ip()
        disasm = self.runner.disassemble(ip, 1)
        
        if disasm:
            _, name, length, _ = disasm[0]
            if name == 'CALL':
                next_ip = ip + length
                temp_bp = next_ip
                self.add_breakpoint(temp_bp)
                while self.runner.step():
                    current_ip = self.runner.cpu._get_ip()
                    if current_ip == temp_bp:
                        break
                self.remove_breakpoint(temp_bp)
                return True
        
        return self.runner.step()
    
# Step until the next breakpoint; False means the program ended.
    def continue_execution(self) -> bool:
        while self.runner.step():
            ip = self.runner.cpu._get_ip()
            if ip in self.breakpoints:
                self._debug_prompt()
                return True
        return False
    
# Walk the frame pointers, newest frame first.
    def get_backtrace(self) -> List[Tuple[int, Optional[str]]]:
        if not self.runner.cpu:
            return []
        
        backtrace = []
        ip = self.runner.cpu._get_ip()
        bp = self.runner.cpu._get_reg(5)
        
        sym = self.runner.get_symbol_at(ip)
        backtrace.append((ip, sym))
        
        max_frames = 20
        for _ in range(max_frames):
            try:
                if bp == 0:
                    break
                
                ret_addr = self.runner.cpu.memory.read_qword(bp + 8)
                next_bp = self.runner.cpu.memory.read_qword(bp)
                
                if ret_addr == 0 or next_bp == 0:
                    break
                
                sym = self.runner.get_symbol_at(ret_addr)
                backtrace.append((ret_addr, sym))
                
                bp = next_bp
            except:
                break
        
        return backtrace
    
# Print the frames as '#index address in symbol'.
    def print_backtrace(self) -> None:
        bt = self.get_backtrace()
        print("\nBacktrace:")
        for i, (addr, sym) in enumerate(bt):
            if sym:
                print(f"  #{i}: 0x{addr:x} in {sym}")
            else:
                print(f"  #{i}: 0x{addr:x}")
