'''
 *
 *      unicorn_runner.py
 *      Runs ELF programs on the Unicorn engine.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import logging
import struct
import time
from typing import Dict, List, Optional

from .elf_parser import ELFParser
from .elf_loader import (
    ELFLoader, MemoryRegion, MemoryProtection, PAGE_SIZE, align_up, align_down,
)
from .syscall_emulator import SyscallEmulator
from .elf_runner import ExecutionResult

try:
    from unicorn import (
        Uc, UC_ARCH_X86, UC_MODE_32, UC_MODE_64,
        UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC,
        UC_HOOK_INSN, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED,
        UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED,
        UcError,
    )
    from unicorn.x86_const import (
        UC_X86_REG_RAX, UC_X86_REG_RDX, UC_X86_REG_RSI, UC_X86_REG_RDI,
        UC_X86_REG_RSP, UC_X86_REG_RIP, UC_X86_REG_RCX,
        UC_X86_REG_RFLAGS,
        UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_R10,
        UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
        UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
        UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP,
        UC_X86_REG_ES,
        UC_X86_REG_SS, UC_X86_REG_FS, UC_X86_REG_GS,
        UC_X86_INS_SYSCALL, UC_X86_INS_INT,
    )
    _UNICORN_AVAILABLE = True
    _UNICORN_IMPORT_ERROR: Optional[Exception] = None
except Exception as e:  # ImportError and friends: the module must import even without unicorn
    _UNICORN_AVAILABLE = False
    _UNICORN_IMPORT_ERROR = e

logger = logging.getLogger(__name__)


# Report whether the unicorn library could be imported.
def unicorn_available() -> bool:
    return _UNICORN_AVAILABLE


# Raised when the Unicorn path cannot be used, so the caller can fall back.
class UnicornRunError(Exception):
    pass


# Translate the loader's protection bits into a UC_PROT_* mask.
def _prot_to_uc(flags: int) -> int:
    prot = 0
    if flags & MemoryProtection.READ:
        prot |= UC_PROT_READ
    if flags & MemoryProtection.WRITE:
        prot |= UC_PROT_WRITE
    if flags & MemoryProtection.EXEC:
        prot |= UC_PROT_EXEC
    if prot == 0:
        prot = UC_PROT_READ | UC_PROT_WRITE
    return prot


# Let SyscallEmulator run against Unicorn's memory instead of a bytearray.
# self.memory is the loader's own dict, so what the mmap handlers add or drop is
# visible on both sides at once. Unicorn owns the contents; the mirrored
# bytearrays only supply the initial bytes for a fresh mapping, and new regions
# reach the engine through sync_uc_mappings().
class UnicornLoaderAdapter:

# Share the loader's memory dict with the engine; nothing is mapped yet.
    def __init__(self, uc: "Uc", parser, memory: Dict[int, MemoryRegion],
                 heap_start: int, brk: int):
        self.uc = uc
        self.parser = parser
        self.memory = memory
        self.heap_start = heap_start
        self.brk = brk
# page-aligned ranges already mapped on the uc side: start to size
        self.uc_mapped: Dict[int, int] = {}

# -- the memory primitives, named exactly as in ELFLoader because that is all SyscallEmulator calls --

# Read straight out of Unicorn, turning UcError into MemoryAccessError.
    def read_memory(self, addr: int, size: int) -> bytes:
        try:
            return bytes(self.uc.mem_read(addr, size))
        except UcError as e:
            from .elf_loader import MemoryAccessError
            raise MemoryAccessError(f"unicorn read fault at 0x{addr:x}: {e}")

# Write straight into Unicorn, turning UcError into MemoryAccessError.
    def write_memory(self, addr: int, data: bytes) -> None:
        try:
            self.uc.mem_write(addr, data)
        except UcError as e:
            from .elf_loader import MemoryAccessError
            raise MemoryAccessError(f"unicorn write fault at 0x{addr:x}: {e}")

# Read a 1, 2, 4 or 8 byte little-endian integer.
    def read_int(self, addr: int, size: int, signed: bool = False) -> int:
        data = self.read_memory(addr, size)
        fmt_map = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}
        fmt = fmt_map.get(size, 'I')
        if signed:
            fmt = fmt.lower()
        return struct.unpack('<' + fmt, data)[0]

# Write a 1, 2, 4 or 8 byte little-endian integer.
    def write_int(self, addr: int, value: int, size: int) -> None:
        fmt_map = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}
        fmt = fmt_map.get(size, 'I')
        max_val = 1 << (size * 8)
        self.write_memory(addr, struct.pack('<' + fmt, value & (max_val - 1)))

# Grow the heap, mapping the new pages into Unicorn first.
    def brk_extend(self, addr: int) -> int:
        if addr < self.heap_start:
            return self.brk
        heap_region = self.memory.get(self.heap_start)
        if heap_region is None:
            return self.brk
        current_end = self.heap_start + heap_region.size
        if addr > current_end:
            new_size = align_up(addr - self.heap_start, PAGE_SIZE)
            max_heap_size = 128 * 1024 * 1024
            if new_size > max_heap_size:
                return self.brk
# map the new pages into uc first, then grow the mirror
            map_start = align_down(current_end, PAGE_SIZE)
            map_end = align_up(self.heap_start + new_size, PAGE_SIZE)
            if map_end > map_start:
                self._uc_map(map_start, map_end - map_start,
                             UC_PROT_READ | UC_PROT_WRITE)
            heap_region.data = heap_region.data + bytearray(new_size - heap_region.size)
            heap_region.size = new_size
        self.brk = addr
        return self.brk

# -- uc mapping sync --

# Map a page-aligned range, refusing to overlap an existing mapping.
    def _uc_map(self, start: int, size: int, prot: int) -> None:
        start = align_down(start, PAGE_SIZE)
        size = align_up(size, PAGE_SIZE)
# skip anything overlapping an existing mapping; callers keep fixed-address mmap requests non-overlapping
        for ms, msz in self.uc_mapped.items():
            if start < ms + msz and start + size > ms:
                return
        self.uc.mem_map(start, size, prot)
        self.uc_mapped[start] = size

# Unmap a range that uc_mapped still records.
    def _uc_unmap(self, start: int, size: int) -> None:
        if start in self.uc_mapped:
            try:
                self.uc.mem_unmap(start, self.uc_mapped[start])
            except UcError:
                pass
            del self.uc_mapped[start]

# Map one loader region into Unicorn and copy its bytes across.
    def map_region(self, region: MemoryRegion) -> None:
        start = region.page_aligned_start()
        size = region.page_aligned_end() - start
        self._uc_map(start, size, _prot_to_uc(region.flags))
# write the file contents back; the BSS tail stays the zero pages uc mapped
        if len(region.data) > 0:
            try:
                self.uc.mem_write(region.start, bytes(region.data))
            except UcError as e:
                raise UnicornRunError(f"写入映射内容失败 0x{region.start:x}: {e}")

# Map the regions Unicorn has not seen and unmap the ones the loader lost.
    def sync_uc_mappings(self) -> None:
# added, so map it
        for start, region in list(self.memory.items()):
            rs = region.page_aligned_start()
            if rs not in self.uc_mapped:
                self.map_region(region)
# removed, so unmap it
        want = {r.page_aligned_start() for r in self.memory.values()}
        for ms in [k for k in self.uc_mapped if k not in want]:
            self._uc_unmap(ms, self.uc_mapped[ms])


# Run an ELF program on Unicorn, with the same signature as ELFRunner.
class UnicornRunner:

# Refuse to build without the unicorn library; no file is read yet.
    def __init__(self, elf_path: str, base_addr: Optional[int] = None,
                 enable_aslr: bool = False, strict_mode: bool = True):
        if not _UNICORN_AVAILABLE:
            raise UnicornRunError(
                f"unicorn 库不可用（{_UNICORN_IMPORT_ERROR}），"
                "请 pip install unicorn 后重试，或改用自研引擎兜底")
        self.elf_path = elf_path
        self.base_addr = base_addr
        self.enable_aslr = enable_aslr
        self.strict_mode = strict_mode

        self.parser: Optional[ELFParser] = None
        self.loader: Optional[ELFLoader] = None
        self.adapter: Optional[UnicornLoaderAdapter] = None
        self.syscall_emulator: Optional[SyscallEmulator] = None
        self.uc: Optional[Uc] = None
        self.is_64bit = True

        self.is_loaded = False
        self.entry_point = 0
        self.stack_pointer = 0
        self.instruction_count = 0
        self.exit_code = 0
        self.fault_addr = 0
        self.fault_msg = ""
        self.guest_exited = False

# input handed to the guest by set_stdin(), kept until load() builds the emulator
        self._stdin_data = None

# -- loading --

# Read, load and mirror the image into Unicorn, then install the hooks.
    def load(self) -> bool:
        try:
            with open(self.elf_path, 'rb') as f:
                data = f.read()
            self.parser = ELFParser(data)
            if not self.parser.parse():
                logger.error(f"unicorn: ELF 解析失败: {self.parser.parse_error}")
                return False

            from .elf_constants import ELFType, ELFMachine
            header = self.parser.header
            if header.e_type not in (ELFType.ET_EXEC, ELFType.ET_DYN):
                logger.error(f"unicorn: 不支持的 ELF 类型 {header.e_type}")
                return False
            if header.e_machine not in (ELFMachine.EM_386, ELFMachine.EM_X86_64):
                logger.error(f"unicorn: 不支持的架构 {header.e_machine}")
                return False
            self.is_64bit = not self.parser.is_32bit

            self.loader = ELFLoader(
                self.parser, self.base_addr,
                enable_aslr=self.enable_aslr,
                strict_protection=self.strict_mode)
            self.loader.load()
            self.entry_point = self.loader.entry_point

            mode = UC_MODE_64 if self.is_64bit else UC_MODE_32
            self.uc = Uc(UC_ARCH_X86, mode)

            self.adapter = UnicornLoaderAdapter(
                self.uc, self.parser, self.loader.memory,
                self.loader.heap_start, self.loader.brk)
            for region in list(self.loader.memory.values()):
                self.adapter.map_region(region)

            self.syscall_emulator = SyscallEmulator(self.adapter)
            if self._stdin_data is not None:
                self.syscall_emulator.set_stdin(self._stdin_data)
            self.syscall_emulator.stdout_buffer.clear()
            self.syscall_emulator.stderr_buffer.clear()

            self._install_hooks()
            self.is_loaded = True
            logger.info(f"unicorn: ELF loaded: {self.elf_path} "
                        f"entry=0x{self.entry_point:x}")
            return True
        except UnicornRunError:
            raise
        except Exception as e:
            logger.error(f"unicorn: 加载失败: {e}")
            return False

# -- hooks --

# Hook the syscall entry, the instruction count and the memory faults.
    def _install_hooks(self):
        assert self.uc is not None
        if self.is_64bit:
            self.uc.hook_add(UC_HOOK_INSN, self._hook_syscall, None,
                             1, 0, UC_X86_INS_SYSCALL)
        else:
            self.uc.hook_add(UC_HOOK_INSN, self._hook_int80, None,
                             1, 0, UC_X86_INS_INT)
        self.uc.hook_add(UC_HOOK_CODE, self._hook_code)
        self.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED
                         | UC_HOOK_MEM_FETCH_UNMAPPED,
                         self._hook_mem_invalid)

# Count every instruction Unicorn executes.
    def _hook_code(self, uc, address, size, user_data):
        self.instruction_count += 1

# Record the faulting access and stop the emulation.
    def _hook_mem_invalid(self, uc, access, address, size, value, user_data):
        self.fault_addr = address
        self.fault_msg = f"invalid memory access={access} at 0x{address:x}"
        logger.error(f"unicorn: {self.fault_msg}")
        uc.emu_stop()
        return False

# Run one guest syscall and push any new mappings into Unicorn.
    def _do_syscall(self, number: int, args: List[int]) -> int:
        assert self.syscall_emulator is not None
        try:
            ret = self.syscall_emulator.handle_syscall(number, *args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
            self.exit_code = code
# the syscall hook turns _GuestExit into emu_stop, so the flag is what tells the
# caller that the program really ended instead of running out of emulation
            self.guest_exited = True
            raise _GuestExit(code)
# mmap, munmap and brk can add or drop mappings, so sync them into uc
        try:
            assert self.adapter is not None
            self.adapter.sync_uc_mappings()
        except Exception as e:
            logger.error(f"unicorn: 同步映射失败: {e}")
        return ret

# Handle the 64-bit SYSCALL instruction.
    def _hook_syscall(self, uc, user_data):
# the unicorn 2.x instruction hook signature is (uc, user_data).
# Note that QEMU still executes the SYSCALL itself after the hook returns and advances RIP on its own,
# so RIP must never be bumped by 2 here or the next instruction is skipped. Verified by experiment.
        rax = uc.reg_read(UC_X86_REG_RAX)
        args = [uc.reg_read(r) for r in (
            UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX,
            UC_X86_REG_R10, UC_X86_REG_R8, UC_X86_REG_R9)]
        try:
            ret = self._do_syscall(rax, args)
        except _GuestExit:
            uc.emu_stop()
            return
        uc.reg_write(UC_X86_REG_RAX, ret & 0xFFFFFFFFFFFFFFFF)

# Handle the 32-bit int 0x80 syscall entry.
    def _hook_int80(self, uc, user_data):
# Same for int 0x80: QEMU advances EIP after the hook returns, so do not add anything.
        eax = uc.reg_read(UC_X86_REG_EAX)
        args = [uc.reg_read(r) for r in (
            UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
            UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)]
        try:
            ret = self._do_syscall(eax, args)
        except _GuestExit:
            uc.emu_stop()
            return
        uc.reg_write(UC_X86_REG_EAX, ret & 0xFFFFFFFF)

# -- running --

# Emulate to completion and report what the guest did.
    def run(self, argv=None, envp=None,
            max_instructions: Optional[int] = None) -> ExecutionResult:
        import os as _os
        if not self.is_loaded:
            if not self.load():
                return ExecutionResult(exit_code=-1, stderr="unicorn: 加载失败")
        assert self.uc is not None and self.loader is not None
        if argv is None:
            argv = [self.elf_path]
        if envp is None:
            envp = dict(_os.environ)

# the stack layout must match the in-house CPU (CPUEmulator._setup_argv_envp_64/32) byte for byte,
# otherwise _start reads a shifted argc and argv. loader.setup_argv_envp is deliberately not used.
        if self.is_64bit:
            sp = self._build_stack_64(argv, envp)
        else:
            sp = self._build_stack_32(argv, envp)
        self.stack_pointer = sp

# initial registers, matching CPUEmulator._init_registers with RFLAGS=0x202
        if self.is_64bit:
            self.uc.reg_write(UC_X86_REG_RSP, sp)
            self.uc.reg_write(UC_X86_REG_RIP, self.entry_point)
            self.uc.reg_write(UC_X86_REG_RFLAGS, 0x202)
        else:
            self._setup_segments_32()
            self.uc.reg_write(UC_X86_REG_ESP, sp & 0xFFFFFFFF)
            self.uc.reg_write(UC_X86_REG_EIP, self.entry_point & 0xFFFFFFFF)

        self.instruction_count = 0
        self.exit_code = 0
        self.fault_addr = 0
        self.fault_msg = ""
        self.guest_exited = False
        start = time.time()
        try:
# the constructors run on the guest's own stack, before _start, and may exit the program
            if self._run_constructors(self.loader.preinit_functions + self.loader.init_functions):
                self.loader.initialized = True
            else:
                logger.warning("unicorn: 构造函数未全部执行")
        except _GuestExit as e:
            self.exit_code = e.code
        
# a constructor that called exit ends the run before _start is ever reached
        exited_in_init = self.guest_exited
        try:
            if not exited_in_init:
# until=0, so the run ends through emu_stop or a fault, plus a 15s timeout and an instruction cap
                self.uc.emu_start(self.entry_point, 0,
                                  timeout=15 * 1000 * 1000,
                                  count=max_instructions or 0)
        except UcError as e:
# an emu_stop from the syscall hook is a normal exit; anything else is a fault
            if self.fault_msg:
                pass
            elif self.exit_code == 0 and "HOOK" not in str(e):
                self.fault_msg = f"UcError: {e}"
                self.fault_addr = self._current_ip()
                logger.error(f"unicorn: {self.fault_msg}")
        except _GuestExit as e:
            self.exit_code = e.code

# destructors run in reverse order once the program has stopped
        if not exited_in_init:
            self._run_constructors(reversed(self.loader.fini_functions))
        execution_time = time.time() - start

        stdout_text = b''.join(self.syscall_emulator.stdout_buffer).decode(
            'utf-8', errors='replace')
        stderr_text = b''.join(self.syscall_emulator.stderr_buffer).decode(
            'utf-8', errors='replace')
        mem_usage = sum(len(r.data) for r in self.loader.memory.values())
        signal = 11 if (self.fault_msg and self.exit_code == 0) else 0
        return ExecutionResult(
            exit_code=self.exit_code if not signal else -signal,
            stdout=stdout_text, stderr=stderr_text,
            instruction_count=self.instruction_count,
            execution_time=execution_time, memory_usage=mem_usage,
            signal=signal, fault_addr=self.fault_addr)

# Return the stack top, held clear of the AT_RANDOM page.
    def _stack_top_clamped(self) -> int:
        top = self.loader.stack_top
        if top >= 0x7fff0000:
            top = 0x7ffefff0
        return top

# Build the 64-bit startup stack exactly as the in-house CPU does.
    def _build_stack_64(self, argv, envp) -> int:
        rsp = self._stack_top_clamped() & ~0xF

# Push one 64-bit word into Unicorn memory and return the new stack pointer.
        def push_qword(value: int) -> int:
            nonlocal rsp
            rsp -= 8
            self.adapter.write_memory(rsp, struct.pack('<Q', value & 0xFFFFFFFFFFFFFFFF))
            return rsp

# Push raw bytes into Unicorn memory and return the new stack pointer.
        def push_data(data: bytes) -> int:
            nonlocal rsp
            rsp -= len(data)
            self.adapter.write_memory(rsp, data)
            return rsp

        envp_addrs = [push_data(f"{k}={v}\x00".encode())
                      for k, v in reversed(list(envp.items()))]
        argv_addrs = [push_data((arg + '\x00').encode()) for arg in reversed(argv)]
        rsp &= ~0x7

        push_qword(0)
        push_qword(0)
        for addr in reversed(envp_addrs):
            push_qword(addr)
        push_qword(0)
        for addr in reversed(argv_addrs):
            push_qword(addr)
        push_qword(len(argv))
        return rsp

# Build the 32-bit startup stack exactly as the in-house CPU does.
    def _build_stack_32(self, argv, envp) -> int:
        esp = self._stack_top_clamped() & ~0x3

# Push one 32-bit word into Unicorn memory and return the new stack pointer.
        def push_dword(value: int) -> int:
            nonlocal esp
            esp -= 4
            self.adapter.write_memory(esp, struct.pack('<I', value & 0xFFFFFFFF))
            return esp

# Push raw bytes into Unicorn memory and return the new stack pointer.
        def push_data(data: bytes) -> int:
            nonlocal esp
            esp -= len(data)
            self.adapter.write_memory(esp, data)
            return esp

        envp_addrs = [push_data(f"{k}={v}\x00".encode())
                      for k, v in reversed(list(envp.items()))]
        argv_addrs = [push_data((arg + '\x00').encode()) for arg in reversed(argv)]
        esp &= ~0x3

        push_dword(0)
        push_dword(0)
        for addr in reversed(envp_addrs):
            push_dword(addr)
        push_dword(0)
        for addr in reversed(argv_addrs):
            push_dword(addr)
        push_dword(len(argv))
        return esp

# Return the instruction pointer for the current width.
    def _current_ip(self) -> int:
        assert self.uc is not None
        if self.is_64bit:
            return self.uc.reg_read(UC_X86_REG_RIP)
        return self.uc.reg_read(UC_X86_REG_EIP)
    
# Call one guest function on the engine and report whether it returned; the SysV and cdecl
# entry state is built by hand because the loader has no CPU to call through here.
    def _call_guest_function(self, func_addr: int, args=None,
                             budget: int = 1000000) -> bool:
        if not func_addr:
            return True
        
        assert self.uc is not None and self.adapter is not None
        sentinel = self.loader.scratch_address()
        if not sentinel:
            logger.warning(f"unicorn: 无法调用 0x{func_addr:x}，找不到可写返回地址")
            return False
        
        sp_reg = UC_X86_REG_RSP if self.is_64bit else UC_X86_REG_ESP
        ip_reg = UC_X86_REG_RIP if self.is_64bit else UC_X86_REG_EIP
        arg_regs = (UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX,
                    UC_X86_REG_RCX, UC_X86_REG_R8, UC_X86_REG_R9) if self.is_64bit else ()
        
        saved_sp = self.uc.reg_read(sp_reg)
        saved_ip = self.uc.reg_read(ip_reg)
        
        try:
            new_sp = saved_sp - (8 if self.is_64bit else 4)
            self.adapter.write_memory(
                new_sp, struct.pack('<Q', sentinel) if self.is_64bit
                else struct.pack('<I', sentinel & 0xFFFFFFFF))
            self.uc.reg_write(sp_reg, new_sp)
            
            for reg, arg in zip(arg_regs, args or ()):
                self.uc.reg_write(reg, arg & (0xFFFFFFFFFFFFFFFF if self.is_64bit else 0xFFFFFFFF))
            
# emu_start stops when the instruction pointer reaches the sentinel, so no
# instruction has to be planted there
            self.uc.emu_start(func_addr, sentinel, count=budget)
            return self._current_ip() == sentinel
        except UcError as e:
            logger.warning(f"unicorn: 调用 0x{func_addr:x} 失败: {e}")
            return False
        finally:
            self.uc.reg_write(sp_reg, saved_sp)
            self.uc.reg_write(ip_reg, saved_ip)
    
# Run a list of constructors in order; True only when every one of them returned.
    def _run_constructors(self, func_addrs) -> bool:
        ok = True
        for func_addr in func_addrs:
            logger.debug(f"unicorn: 运行构造函数 0x{func_addr:x}")
            if not self._call_guest_function(func_addr):
                logger.warning(f"unicorn: 构造函数 0x{func_addr:x} 未返回")
                ok = False
        return ok
    
# Install the smallest flat GDT a 32-bit guest will accept.
    def _setup_segments_32(self):
        assert self.uc is not None
# GDT: NULL plus CODE(0x08) plus DATA(0x10), placed in low free memory
        gdt_addr = 0x1000
        try:
            self.uc.mem_map(gdt_addr, PAGE_SIZE,
                            UC_PROT_READ | UC_PROT_WRITE)
        except UcError:
            pass
# Pack one 8-byte GDT descriptor.
        def desc(base, limit, access, flags):
            return struct.pack('<IHHBB',
                               limit & 0xFFFF, base & 0xFFFF,
                               ((base >> 16) & 0xFF), access,
                               (((limit >> 16) & 0x0F) | ((flags & 0x0F) << 4)),
                               ((base >> 24) & 0xFF))
        gdt = (b'\x00' * 8
               + desc(0, 0xFFFFF, 0x9A, 0xC)   # CODE
               + desc(0, 0xFFFFF, 0x92, 0xC))  # DATA
        try:
            self.uc.mem_write(gdt_addr, gdt)
        except UcError:
            pass
        try:
            from unicorn.x86_const import (UC_X86_REG_GDTR, UC_X86_REG_CS,
                                           UC_X86_REG_DS)
            self.uc.reg_write(UC_X86_REG_GDTR, (0, gdt_addr, len(gdt) - 1, 0x0))
            for seg, sel in ((UC_X86_REG_CS, 0x08), (UC_X86_REG_DS, 0x10),
                             (UC_X86_REG_ES, 0x10), (UC_X86_REG_SS, 0x10),
                             (UC_X86_REG_FS, 0x10), (UC_X86_REG_GS, 0x10)):
                try:
                    self.uc.reg_write(seg, sel)
                except UcError:
                    pass
        except Exception as e:
            logger.warning(f"unicorn: 32 位段设置降级: {e}")

# -- debugging and inspection API, the subset that matches ELFRunner --

# Return (address, mnemonic, length, operands) for count instructions.
    def disassemble(self, addr=None, count: int = 10):
        from .cpu_emulator import MemoryController, InstructionDecoder
        if addr is None:
            addr = self._current_ip() or self.entry_point
        mem = MemoryController(self.loader)
        dec = InstructionDecoder(self.is_64bit)
        result = []
        cur = addr
        for _ in range(count):
            try:
                name, length, operands = dec.decode(mem, cur)
                result.append((cur, name, length, operands))
                cur += length
            except Exception:
                break
        return result

# Return (start, size, name, rwx) per region, sorted by address.
    def get_memory_map(self):
        if not self.loader:
            return []
        result = []
        for start, region in self.loader.memory.items():
            perms = ('r' if region.readable else '-')
            perms += ('w' if region.writable else '-')
            perms += ('x' if region.executable else '-')
            result.append((start, region.size, region.name, perms))
        return sorted(result, key=lambda x: x[0])

# Set the data the guest will read from stdin; it survives a later load().
    def set_stdin(self, data: str) -> None:
        self._stdin_data = data
        if self.syscall_emulator:
            self.syscall_emulator.set_stdin(data)


# Raised inside a hook so a guest exit can unwind out of Unicorn.
class _GuestExit(Exception):
# Carry the guest's exit code up to run().
    def __init__(self, code: int):
        super().__init__(f"guest exit {code}")
        self.code = code


# Load and run an ELF file on Unicorn in one call.
def run_elf_unicorn(elf_path: str, argv=None, envp=None,
                    max_instructions: Optional[int] = None) -> ExecutionResult:
    runner = UnicornRunner(elf_path)
    return runner.run(argv, envp, max_instructions)
