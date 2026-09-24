#
#   elf_loader/unicorn_runner.py
#   基于 Unicorn Engine 的 ELF 运行器（默认引擎，自研 CPU 模拟器保留为兜底）。
#
#   设计：
#   - 复用现有 ELFParser + ELFLoader 做解析、分段加载、栈/堆构建、argv/envp 排布；
#   - 内存镜像进 Unicorn，CPU 执行由 Unicorn 承担（真 x86 语义）；
#   - syscall（64 位 SYSCALL / 32 位 int 0x80）通过指令钩子转交给既有的
#     SyscallEmulator；mmap/munmap/brk 引起的新映射通过 sync 回写 Unicorn；
#   - 任何环节失败（无 unicorn 库 / 映射失败 / 执行异常）抛 UnicornRunError，
#     上层自动降级到自研 CPU 模拟器。
#
#   已知限制（与自研引擎一致，不扩大承诺范围）：
#   - 仅支持静态链接的 ET_EXEC / ET_DYN（不支持 INTERP 动态链接器）；
#   - TLS（arch_prctl 设置 FS 基址）未透传给 Unicorn，用到 TLS 的二进制可能失败；
#   - signals/多线程/clone 未实现，遇到直接返回 -ENOSYS 由程序侧处理。
#

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
        UC_X86_REG_RSP, UC_X86_REG_RIP,
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
except Exception as e:  # ImportError 等：无 unicorn 时模块仍可 import
    _UNICORN_AVAILABLE = False
    _UNICORN_IMPORT_ERROR = e

logger = logging.getLogger(__name__)


def unicorn_available() -> bool:
    return _UNICORN_AVAILABLE


class UnicornRunError(Exception):
    pass


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


class UnicornLoaderAdapter:
    """让 SyscallEmulator 能在 Unicorn 内存上工作的 loader 兼容层。

    关键约定：
    - self.memory 与 ELFLoader.memory 是同一个 dict 对象，mmap 处理函数
      的增删对双方立即可见；
    - 内存内容以 Unicorn 为准（read_memory 直读 uc），镜像里的 bytearray
      仅用于“新映射同步进 uc”时提供初始内容；
    - brk/mmap 产生的新区域由 sync_uc_mappings() 统一映射进 uc。
    """

    def __init__(self, uc: "Uc", parser, memory: Dict[int, MemoryRegion],
                 heap_start: int, brk: int):
        self.uc = uc
        self.parser = parser
        self.memory = memory
        self.heap_start = heap_start
        self.brk = brk
        # uc 侧已映射的页对齐区间：start -> size
        self.uc_mapped: Dict[int, int] = {}

    # -- 与 ELFLoader 同名的内存原语（SyscallEmulator 只认这几个）--

    def read_memory(self, addr: int, size: int) -> bytes:
        try:
            return bytes(self.uc.mem_read(addr, size))
        except UcError as e:
            from .elf_loader import MemoryAccessError
            raise MemoryAccessError(f"unicorn read fault at 0x{addr:x}: {e}")

    def write_memory(self, addr: int, data: bytes) -> None:
        try:
            self.uc.mem_write(addr, data)
        except UcError as e:
            from .elf_loader import MemoryAccessError
            raise MemoryAccessError(f"unicorn write fault at 0x{addr:x}: {e}")

    def read_int(self, addr: int, size: int, signed: bool = False) -> int:
        data = self.read_memory(addr, size)
        fmt_map = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}
        fmt = fmt_map.get(size, 'I')
        if signed:
            fmt = fmt.lower()
        return struct.unpack('<' + fmt, data)[0]

    def write_int(self, addr: int, value: int, size: int) -> None:
        fmt_map = {1: 'B', 2: 'H', 4: 'I', 8: 'Q'}
        fmt = fmt_map.get(size, 'I')
        max_val = 1 << (size * 8)
        self.write_memory(addr, struct.pack('<' + fmt, value & (max_val - 1)))

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
            # 先映射新增页进 uc，再扩展镜像
            map_start = align_down(current_end, PAGE_SIZE)
            map_end = align_up(self.heap_start + new_size, PAGE_SIZE)
            if map_end > map_start:
                self._uc_map(map_start, map_end - map_start,
                             UC_PROT_READ | UC_PROT_WRITE)
            heap_region.data = heap_region.data + bytearray(new_size - heap_region.size)
            heap_region.size = new_size
        self.brk = addr
        return self.brk

    # -- uc 映射同步 --

    def _uc_map(self, start: int, size: int, prot: int) -> None:
        start = align_down(start, PAGE_SIZE)
        size = align_up(size, PAGE_SIZE)
        # 与已有映射重叠则跳过（mmap 固定地址等场景由调用方保证不重叠）
        for ms, msz in self.uc_mapped.items():
            if start < ms + msz and start + size > ms:
                return
        self.uc.mem_map(start, size, prot)
        self.uc_mapped[start] = size

    def _uc_unmap(self, start: int, size: int) -> None:
        if start in self.uc_mapped:
            try:
                self.uc.mem_unmap(start, self.uc_mapped[start])
            except UcError:
                pass
            del self.uc_mapped[start]

    def map_region(self, region: MemoryRegion) -> None:
        start = region.page_aligned_start()
        size = region.page_aligned_end() - start
        self._uc_map(start, size, _prot_to_uc(region.flags))
        # 回填文件内容（BSS 部分保持 uc 映射的零页）
        if len(region.data) > 0:
            try:
                self.uc.mem_write(region.start, bytes(region.data))
            except UcError as e:
                raise UnicornRunError(f"写入映射内容失败 0x{region.start:x}: {e}")

    def sync_uc_mappings(self) -> None:
        """mmap/munmap 系统调用后调用：增删与 uc 侧保持一致。"""
        # 新增 → 映射
        for start, region in list(self.memory.items()):
            rs = region.page_aligned_start()
            if rs not in self.uc_mapped:
                self.map_region(region)
        # 删除 → 解除映射
        want = {r.page_aligned_start() for r in self.memory.values()}
        for ms in [k for k in self.uc_mapped if k not in want]:
            self._uc_unmap(ms, self.uc_mapped[ms])


class UnicornRunner:
    """与 ELFRunner 同签名的 Unicorn 驱动运行器。"""

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

    # -- 加载 --

    def load(self) -> bool:
        try:
            with open(self.elf_path, 'rb') as f:
                data = f.read()
            self.parser = ELFParser(data)
            if not self.parser.parse():
                logger.error("unicorn: ELF 解析失败")
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

    # -- 钩子 --

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

    def _hook_code(self, uc, address, size, user_data):
        self.instruction_count += 1

    def _hook_mem_invalid(self, uc, access, address, size, value, user_data):
        self.fault_addr = address
        self.fault_msg = f"invalid memory access={access} at 0x{address:x}"
        logger.error(f"unicorn: {self.fault_msg}")
        uc.emu_stop()
        return False

    def _do_syscall(self, number: int, args: List[int]) -> int:
        assert self.syscall_emulator is not None
        try:
            ret = self.syscall_emulator.handle_syscall(number, *args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
            self.exit_code = code
            raise _GuestExit(code)
        # mmap/munmap/brk 可能增删映射 → 同步进 uc
        try:
            assert self.adapter is not None
            self.adapter.sync_uc_mappings()
        except Exception as e:
            logger.error(f"unicorn: 同步映射失败: {e}")
        return ret

    def _hook_syscall(self, uc, user_data):
        # unicorn 2.x INSN 钩子签名为 (uc, user_data)。
        # 注意：QEMU 在钩子返回后仍会“执行” SYSCALL 本体并自行推进 RIP，
        # 因此这里绝不能再手动 RIP+2（否则会跳过下一条指令）。实测验证。
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

    def _hook_int80(self, uc, user_data):
        # 同上：int 0x80 钩子返回后 QEMU 自行推进 EIP，不手动加。
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

    # -- 运行 --

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

        # 栈排布必须与自研 CPU（CPUEmulator._setup_argv_envp_64/32）逐字节一致，
        # 否则 _start 读到的 argc/argv 全错位。刻意不用 loader.setup_argv_envp。
        if self.is_64bit:
            sp = self._build_stack_64(argv, envp)
        else:
            sp = self._build_stack_32(argv, envp)
        self.stack_pointer = sp

        # 初始寄存器（对齐 CPUEmulator._init_registers：RFLAGS=0x202）
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
        start = time.time()
        try:
            # until=0（不会命中则靠 emu_stop/异常结束）+ 15s 超时 + 指令上限
            self.uc.emu_start(self.entry_point, 0,
                              timeout=15 * 1000 * 1000,
                              count=max_instructions or 0)
        except UcError as e:
            # syscall 钩子内已 emu_stop 属正常退出；其余按 fault 处理
            if self.fault_msg:
                pass
            elif self.exit_code == 0 and "HOOK" not in str(e):
                self.fault_msg = f"UcError: {e}"
                self.fault_addr = self._current_ip()
                logger.error(f"unicorn: {self.fault_msg}")
        except _GuestExit as e:
            self.exit_code = e.code
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

    def _stack_top_clamped(self) -> int:
        top = self.loader.stack_top
        if top >= 0x7fff0000:
            top = 0x7ffefff0
        return top

    def _build_stack_64(self, argv, envp) -> int:
        """复刻 CPUEmulator._setup_argv_envp_64 的压栈顺序与对齐。"""
        rsp = self._stack_top_clamped() & ~0xF

        def push_qword(value: int) -> int:
            nonlocal rsp
            rsp -= 8
            self.adapter.write_memory(rsp, struct.pack('<Q', value & 0xFFFFFFFFFFFFFFFF))
            return rsp

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

    def _build_stack_32(self, argv, envp) -> int:
        """复刻 CPUEmulator._setup_argv_envp_32 的压栈顺序与对齐。"""
        esp = self._stack_top_clamped() & ~0x3

        def push_dword(value: int) -> int:
            nonlocal esp
            esp -= 4
            self.adapter.write_memory(esp, struct.pack('<I', value & 0xFFFFFFFF))
            return esp

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

    def _current_ip(self) -> int:
        assert self.uc is not None
        if self.is_64bit:
            return self.uc.reg_read(UC_X86_REG_RIP)
        return self.uc.reg_read(UC_X86_REG_EIP)

    def _setup_segments_32(self):
        """32 位扁平段最小 GDT（教学实现，仅求简单 ELF 可跑）。"""
        assert self.uc is not None
        # GDT: NULL + CODE(0x08) + DATA(0x10)，放在低地址空闲处
        gdt_addr = 0x1000
        try:
            self.uc.mem_map(gdt_addr, PAGE_SIZE,
                            UC_PROT_READ | UC_PROT_WRITE)
        except UcError:
            pass
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

    # -- 调试/观测 API（与 ELFRunner 对齐的子集）--

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

    def set_stdin(self, data: str) -> None:
        if self.syscall_emulator:
            self.syscall_emulator.stdin = data


class _GuestExit(Exception):
    def __init__(self, code: int):
        super().__init__(f"guest exit {code}")
        self.code = code


def run_elf_unicorn(elf_path: str, argv=None, envp=None,
                    max_instructions: Optional[int] = None) -> ExecutionResult:
    runner = UnicornRunner(elf_path)
    return runner.run(argv, envp, max_instructions)
