'''
 *
 *      __init__.py
 *      ELF loader package.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

__version__ = "2.0.0"
__develop_stage__ = "stable"
__cpu_emulator_name__ = "SpaceCPU 1 Pro"
__supported_archs__ = ["x86", "x86_64"]
__syscall_abi__ = "SpaceOS ABI 兼容"

from .elf_constants import (
    ELFClass, ELFData, ELFOSABI, ELFType,
    ELFMachine, SectionHeaderType, SectionHeaderFlags, ProgramHeaderType,
    ProgramHeaderFlags, SymbolBinding, SymbolType, DynamicTag,
    RelocationTypeX86_64, RelocationTypeI386
)
from .elf_parser import ELFParser, ELFHeader, ProgramHeader, SectionHeader
from .elf_parser import ELFSymbol, ELFDynamic, ELFRelocation, ELFRelocationA
from .elf_loader import (
    ELFLoader, MemoryRegion, LoadedSegment,
    ELFLoaderError, MemoryAccessError, MemoryProtectionError,
    RelocationError, SymbolResolutionError,
    TLSInfo, SymbolVersion, PLTEntry, AuxvEntry, AuxvType,
    MemoryProtection
)
from .syscall_emulator import SyscallEmulator
from .cpu_emulator import CPUEmulator, CPUState, Register32, Register64
from .elf_runner import (
    ELFRunner, ELFDebugger, ExecutionResult, LoaderStats, run_elf
)

# The Unicorn engine is an optional dependency; without the library these names degrade to None and callers fall back to the in-house emulator.
try:
    from .unicorn_runner import (
        UnicornRunner, UnicornRunError, run_elf_unicorn, unicorn_available,
    )
except Exception:  # ImportError and friends
    UnicornRunner = None
    UnicornRunError = type("UnicornRunError", (Exception,), {})
    run_elf_unicorn = None

# Report whether the Unicorn engine can be used on this host.
    def unicorn_available() -> bool:
        return False

__all__ = [
    '__version__',
    '__develop_stage__',
    '__cpu_emulator_name__',
    '__supported_archs__',
    '__syscall_abi__',
    'ELFClass', 'ELFData', 'ELFOSABI',
    'ELFType', 'ELFMachine', 'SectionHeaderType', 'SectionHeaderFlags',
    'ProgramHeaderType', 'ProgramHeaderFlags', 'SymbolBinding',
    'SymbolType', 'DynamicTag', 'RelocationTypeX86_64', 'RelocationTypeI386',
    'ELFParser',
    'ELFHeader',
    'ProgramHeader',
    'SectionHeader',
    'ELFSymbol',
    'ELFDynamic',
    'ELFRelocation',
    'ELFRelocationA',
    'ELFLoader',
    'MemoryRegion',
    'LoadedSegment',
    'MemoryProtection',
    'TLSInfo',
    'SymbolVersion',
    'PLTEntry',
    'AuxvEntry',
    'AuxvType',
    'ELFLoaderError',
    'MemoryAccessError',
    'MemoryProtectionError',
    'RelocationError',
    'SymbolResolutionError',
    'SyscallEmulator',
    'CPUEmulator',
    'CPUState',
    'Register32',
    'Register64',
    'ELFRunner',
    'ELFDebugger',
    'ExecutionResult',
    'LoaderStats',
    'run_elf',
    'UnicornRunner',
    'UnicornRunError',
    'run_elf_unicorn',
    'unicorn_available',
]
