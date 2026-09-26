'''
 *
 *      elf_loader.py
 *      Maps an ELF image into a process image and relocates it.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import struct
import logging
import random
from typing import Dict, List, Optional, Tuple, Set, Callable, Any, Union
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from collections import OrderedDict

from .elf_parser import ELFParser, ProgramHeader, SectionHeader, ELFSymbol, ELFRelocation, ELFRelocationA
from .elf_constants import (
    ProgramHeaderType, SectionHeaderType,
    DynamicTag, SymbolBinding, SymbolType,
    RelocationTypeX86_64, RelocationTypeI386,
    SpecialSectionIndex, ELFType, ELFMachine,
    PT_GNU_STACK, PT_GNU_RELRO, PT_GNU_PROPERTY,
    DT_GNU_HASH, DT_VERSYM, DT_VERDEF, DT_VERNEED,
    DT_FLAGS_1, DT_FLAGS,
    SectionHeaderFlags, ProgramHeaderFlags
)

logger = logging.getLogger(__name__)


PAGE_SIZE = 0x1000
PAGE_MASK = ~(PAGE_SIZE - 1)

# How many instructions a guest constructor may run before the call is given up on.
CONSTRUCTOR_BUDGET = 1000000


# Round value up to the next multiple of alignment.
def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


# Round value down to the previous multiple of alignment.
def align_down(value: int, alignment: int) -> int:
    return value & ~(alignment - 1)


# Page protection bits, numbered like the x86 PF_* flags.
class MemoryProtection(IntFlag):
    NONE = 0
    READ = 4
    WRITE = 2
    EXEC = 1
    RW = READ | WRITE
    RX = READ | EXEC
    RWX = READ | WRITE | EXEC


# One mapped range of the process image, with the bytes behind it.
@dataclass
class MemoryRegion:
    start: int
    size: int
    data: bytearray
    flags: int = 0
    name: str = ""
    is_mapped: bool = True
    file_backed: bool = False
    growable: bool = False
    
# Return the first address past the region.
    @property
    def end(self) -> int:
        return self.start + self.size
    
# Report whether the region may be read.
    @property
    def readable(self) -> bool:
        return (self.flags & MemoryProtection.READ) != 0
    
# Report whether the region may be written.
    @property
    def writable(self) -> bool:
        return (self.flags & MemoryProtection.WRITE) != 0
    
# Report whether the region may be executed.
    @property
    def executable(self) -> bool:
        return (self.flags & MemoryProtection.EXEC) != 0
    
# Report whether addr falls inside the region.
    def contains(self, addr: int) -> bool:
        return self.start <= addr < self.end
    
# Return the region start rounded down to a page boundary.
    def page_aligned_start(self) -> int:
        return align_down(self.start, PAGE_SIZE)
    
# Return the region end rounded up to a page boundary.
    def page_aligned_end(self) -> int:
        return align_up(self.end, PAGE_SIZE)
    
# Read size bytes at addr, refusing anything that leaves the region.
    def read(self, addr: int, size: int) -> bytes:
        offset = addr - self.start
        if offset < 0 or offset + size > self.size:
            raise MemoryAccessError(
                f"read oob: addr=0x{addr:x}, size={size}, "
                f"region=[0x{self.start:x}, 0x{self.end:x})"
            )
        return bytes(self.data[offset:offset + size])
    
# Write data at addr; a region without write permission raises.
    def write(self, addr: int, data: bytes) -> None:
        if not self.writable:
            raise MemoryProtectionError(f"write to read-only region at 0x{addr:x}")
        offset = addr - self.start
        if offset < 0 or offset + len(data) > self.size:
            raise MemoryAccessError(
                f"write oob: addr=0x{addr:x}, size={len(data)}, "
                f"region=[0x{self.start:x}, 0x{self.end:x})"
            )
        self.data[offset:offset + len(data)] = data
    
# Read a 1, 2, 4 or 8 byte little-endian integer.
    def read_int(self, addr: int, size: int, signed: bool = False) -> int:
        data = self.read(addr, size)
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
        data = struct.pack('<' + fmt, value & (max_val - 1))
        self.write(addr, data)


# One PT_LOAD segment after loading, carrying its relocated address.
@dataclass
class LoadedSegment:
    ph: ProgramHeader
    vaddr: int
    memsz: int
    filesz: int
    data: bytearray
    page_aligned: bool = True


# The PT_TLS segment, that is where the thread-local template lives.
@dataclass
class TLSInfo:
    template_addr: int = 0
    template_size: int = 0
    memsz: int = 0
    filesz: int = 0
    align: int = 1
    first_byte: int = 0
    offset: int = 0
    module_id: int = 0


# One DT_VERSYM entry, the version index attached to a dynamic symbol.
@dataclass
class SymbolVersion:
    index: int
    name: str = ""
    is_hidden: bool = False


# One PLT slot, tied to the GOT entry that has to be filled in for it.
@dataclass
class PLTEntry:
    addr: int
    symbol_name: str
    symbol_index: int
    got_addr: int
    resolver_stub: Optional[Callable] = None


# One key/value pair of the ELF auxiliary vector.
@dataclass
class AuxvEntry:
    key: int
    value: int


# The AT_* keys of the ELF auxiliary vector.
class AuxvType(IntEnum):
    AT_NULL = 0
    AT_IGNORE = 1
    AT_EXECFD = 2
    AT_PHDR = 3
    AT_PHENT = 4
    AT_PHNUM = 5
    AT_PAGESZ = 6
    AT_BASE = 7
    AT_FLAGS = 8
    AT_ENTRY = 9
    AT_UID = 11
    AT_EUID = 12
    AT_GID = 13
    AT_EGID = 14
    AT_CLKTCK = 17
    AT_PLATFORM = 15
    AT_HWCAP = 16
    AT_FPUCW = 18
    AT_DCACHEBSIZE = 19
    AT_ICACHEBSIZE = 20
    AT_UCACHEBSIZE = 21
    AT_SECURE = 23
    AT_BASE_PLATFORM = 24
    AT_RANDOM = 25
    AT_HWCAP2 = 26
    AT_EXECFN = 31
    AT_SYSINFO = 32
    AT_SYSINFO_EHDR = 33


# Base class for every load-time failure.
class ELFLoaderError(Exception):
    pass


# Raised when an address falls outside every mapped region. Callers may pass either a
# message or the (address, is_write) pair, and both styles expose the same attributes.
class MemoryAccessError(ELFLoaderError):
    def __init__(self, *args, address: Optional[int] = None, is_write: bool = False):
        if args and address is None and isinstance(args[0], int):
            address = args[0]
            if len(args) > 1:
                is_write = bool(args[1])
            args = ()
        
        if args:
            message = str(args[0])
        elif address is not None:
            message = (f"invalid memory access at 0x{address:x} "
                       f"({'write' if is_write else 'read'})")
        else:
            message = "invalid memory access"
        
        super().__init__(message)
        self.address = address
        self.is_write = is_write


# Raised when a write hits a region that has no write permission.
class MemoryProtectionError(ELFLoaderError):
    pass


# Raised when a relocation cannot be applied.
class RelocationError(ELFLoaderError):
    pass


# Raised when a relocation needs a symbol nothing can supply.
class SymbolResolutionError(ELFLoaderError):
    pass


# A numbered TLS module; its id is what DTPMOD relocations hand out.
class TLSModule:
    _next_id = 1
    
# Take the next module id.
    def __init__(self):
        self.id = TLSModule._next_id
        TLSModule._next_id += 1


# Turn a parsed ELF file into a runnable process image.
class ELFLoader:
    
    DEFAULT_BASE_ADDR_64 = 0x400000
    DEFAULT_BASE_ADDR_32 = 0x08048000
    STACK_SIZE = 8 * 1024 * 1024
    STACK_TOP_64 = 0x7fff0000
    STACK_TOP_32 = 0xc0000000
    HEAP_START_64 = 0x100000000
    HEAP_START_32 = 0x80000000
    VDSO_BASE = 0x7ffff7ffd000
    
# Pick the load base, honouring an explicit address, ASLR or the defaults.
    def __init__(self, parser: ELFParser, base_addr: Optional[int] = None,
                 enable_aslr: bool = False, strict_protection: bool = True):
        self.parser = parser
        self.enable_aslr = enable_aslr
        self.strict_protection = strict_protection
        
        if base_addr is not None:
            self.base_addr = base_addr
        elif enable_aslr:
            self.base_addr = self._randomize_base()
        else:
            self.base_addr = (self.DEFAULT_BASE_ADDR_64 if not parser.is_32bit 
                            else self.DEFAULT_BASE_ADDR_32)
        
        self.memory: OrderedDict[int, MemoryRegion] = OrderedDict()
        self.segments: List[LoadedSegment] = []
        
        self.entry_point: int = 0
        self.brk: int = 0
        self.heap_start: int = 0
        self.stack_top: int = 0
        self.stack_bottom: int = 0
        
        self.symbols: Dict[str, int] = {}
        self.symbols_by_addr: Dict[int, str] = {}
        self.dynamic_symbols: Dict[str, Tuple[int, int, int]] = {}
        
        self.plt_entries: Dict[int, PLTEntry] = {}
        self.plt_by_name: Dict[str, int] = {}
        self.got_entries: Dict[int, int] = {}
        self.got_plt_base: int = 0
        
        self.relocations_done = False
        self.bind_now = False
        
        self.dynamic_info: Dict[int, int] = {}
        self.needed_libs: List[str] = []
        
        self.tls_info: Optional[TLSInfo] = None
        self.tls_module_id: int = 0
        
        self.init_functions: List[int] = []
        self.fini_functions: List[int] = []
        self.preinit_functions: List[int] = []
        
        self.auxv: List[AuxvEntry] = []
        self.phdr_addr: int = 0
        self.phdr_count: int = 0
        self.phdr_ent_size: int = 0
        
        self.gnu_stack_flags: int = MemoryProtection.RW
        self.has_gnu_stack: bool = False
        self.gnu_relro_start: int = 0
        self.gnu_relro_size: int = 0
        
        self.symbol_versions: Dict[int, SymbolVersion] = {}
        self.verdef: List[Tuple[int, str]] = []
        self.verneed: Dict[str, List[Tuple[int, str]]] = {}
        
        self.loaded = False
        self.initialized = False
        
        self._external_symbol_resolver: Optional[Callable[[str], Optional[int]]] = None
        
# CPU used only to run IFUNC resolvers, built on first use
        self._helper_cpu_obj: Any = None
        
# Choose a page-aligned base inside the window the architecture allows.
    def _randomize_base(self) -> int:
        if self.parser.is_32bit:
            base_range = (0x08048000, 0x40000000)
        else:
            base_range = (0x400000, 0x80000000)
        
        page_count = (base_range[1] - base_range[0]) // PAGE_SIZE
        random_page = random.randint(0, page_count)
        return base_range[0] + random_page * PAGE_SIZE
    
# Run the whole load pipeline; calling it a second time does nothing.
    def load(self) -> 'ELFLoader':
        if self.loaded:
            return self
            
        try:
            self._validate_elf()
            
            load_offset = self._calculate_load_offset()
            
            self._load_segments(load_offset)
            
            self._parse_program_headers(load_offset)
            
            self._parse_dynamic(load_offset)
            
            self._parse_symbol_versions(load_offset)
            
            self._parse_symbols(load_offset)
            
            self._setup_plt_got(load_offset)
            
# heap and stack first: an IFUNC resolver is called while relocations run and needs
# a mapped writable stack to return through. Their layout does not depend on relocations.
            self._setup_heap()
            
            self._create_stack()
            
            self._perform_relocations(load_offset)
            
            self._setup_tls(load_offset)
            
            self._collect_init_fini(load_offset)
            
            self._build_auxv(load_offset)
            
            self.loaded = True
            logger.info(f"ELF loaded: entry=0x{self.entry_point:x}, "
                       f"base=0x{self.base_addr:x}, segments={len(self.segments)}")
            
            return self
            
        except Exception as e:
            logger.error(f"ELF load failed: {e}")
            raise ELFLoaderError(f"Failed to load ELF: {e}") from e
    
# Reject anything that is not a loadable x86 ELF image.
    def _validate_elf(self) -> None:
        header = self.parser.header
        
        if header.e_type not in (ELFType.ET_EXEC, ELFType.ET_DYN):
            raise ELFLoaderError(f"Unsupported ELF type: {header.e_type}")
        
        if header.e_machine not in (ELFMachine.EM_386, ELFMachine.EM_X86_64):
            raise ELFLoaderError(f"Unsupported architecture: {header.e_machine}")
        
        if header.e_phnum == 0:
            raise ELFLoaderError("No program headers found")
        
        loadable = [ph for ph in self.parser.program_headers 
                   if ph.p_type == ProgramHeaderType.PT_LOAD]
        if not loadable:
            raise ELFLoaderError("No loadable segments found")
    
# Return the bias added to every address, which is zero for ET_EXEC.
    def _calculate_load_offset(self) -> int:
        if self.parser.header.e_type == ELFType.ET_EXEC:
            return 0
        return self.base_addr
    
# Load the PT_LOAD segments in address order and note GNU_STACK and RELRO.
    def _load_segments(self, load_offset: int) -> None:
        loadable_segments = [ph for ph in self.parser.program_headers 
                           if ph.p_type == ProgramHeaderType.PT_LOAD]
        
        loadable_segments.sort(key=lambda ph: ph.p_vaddr)
        
        merged_segments = self._merge_segments(loadable_segments)
        
        for ph in merged_segments:
            self._load_segment(ph, load_offset)
        
        for ph in self.parser.program_headers:
            if ph.p_type == PT_GNU_STACK:
                self.has_gnu_stack = True
                self.gnu_stack_flags = ph.p_flags
            elif ph.p_type == PT_GNU_RELRO:
                self.gnu_relro_start = align_down(ph.p_vaddr + load_offset, PAGE_SIZE)
                self.gnu_relro_size = align_up(ph.p_memsz, PAGE_SIZE)
    
# Fuse neighbouring segments that share permissions and alignment.
    def _merge_segments(self, segments: List[ProgramHeader]) -> List[ProgramHeader]:
        if not segments:
            return []
        
        merged = []
        current = segments[0]
        
        for next_seg in segments[1:]:
            current_end = align_up(current.p_vaddr + current.p_memsz, PAGE_SIZE)
            next_start = align_down(next_seg.p_vaddr, PAGE_SIZE)
            
            if (next_start <= current_end and 
                current.p_flags == next_seg.p_flags and
                current.p_align == next_seg.p_align):
                new_filesz = max(current.p_filesz, 
                               next_seg.p_vaddr + next_seg.p_filesz - current.p_vaddr)
                new_memsz = max(current.p_memsz,
                              next_seg.p_vaddr + next_seg.p_memsz - current.p_vaddr)
                current = ProgramHeader(
                    p_type=current.p_type,
                    p_flags=current.p_flags,
                    p_offset=current.p_offset,
                    p_vaddr=current.p_vaddr,
                    p_paddr=current.p_paddr,
                    p_filesz=new_filesz,
                    p_memsz=new_memsz,
                    p_align=current.p_align
                )
            else:
                merged.append(current)
                current = next_seg
        
        merged.append(current)
        return merged
    
# Copy one segment's file bytes into a page-aligned region.
    def _load_segment(self, ph: ProgramHeader, load_offset: int) -> None:
        vaddr = ph.p_vaddr + load_offset
        
        page_start = align_down(vaddr, PAGE_SIZE)
        page_end = align_up(vaddr + ph.p_memsz, PAGE_SIZE)
        aligned_size = page_end - page_start
        
        data = bytearray(aligned_size)
        
        file_offset = ph.p_offset
        file_vaddr_offset = vaddr - page_start
        
        if ph.p_filesz > 0:
            actual_offset = file_offset
            actual_size = min(ph.p_filesz, ph.p_memsz)
            if actual_offset + actual_size <= len(self.parser.data):
                file_data = self.parser.data[actual_offset:actual_offset + actual_size]
                data[file_vaddr_offset:file_vaddr_offset + len(file_data)] = file_data
        
        region = MemoryRegion(
            start=page_start,
            size=aligned_size,
            data=data,
            flags=ph.p_flags,
            name=f"segment_0x{page_start:x}",
            file_backed=True
        )
        
        self.memory[page_start] = region
        self.segments.append(LoadedSegment(
            ph=ph,
            vaddr=vaddr,
            memsz=ph.p_memsz,
            filesz=ph.p_filesz,
            data=data,
            page_aligned=True
        ))
    
# Find the program header table in memory and compute the entry point.
    def _parse_program_headers(self, load_offset: int) -> None:
        header = self.parser.header
        
        for ph in self.parser.program_headers:
            if ph.p_type == ProgramHeaderType.PT_PHDR:
                self.phdr_addr = ph.p_vaddr + load_offset
                break
        
        if self.phdr_addr == 0:
            for seg in self.segments:
                if seg.vaddr <= header.e_phoff < seg.vaddr + seg.memsz:
                    self.phdr_addr = seg.vaddr + header.e_phoff - seg.ph.p_vaddr
                    break
        
        self.phdr_count = header.e_phnum
        self.phdr_ent_size = header.e_phentsize
        self.entry_point = header.e_entry + load_offset
    
# Copy the DT_* tags into a dict, biasing the pointer-valued ones.
    def _parse_dynamic(self, load_offset: int) -> None:
        for dyn in self.parser.dynamics:
            tag = dyn.d_tag
            val = dyn.d_val
            
            if dyn.is_pointer and val != 0:
                val += load_offset
            
            self.dynamic_info[tag] = val
        
        if DT_FLAGS in self.dynamic_info:
            flags = self.dynamic_info[DT_FLAGS]
            if flags & 0x1:
                self.bind_now = True
        
        if DT_FLAGS_1 in self.dynamic_info:
            flags_1 = self.dynamic_info[DT_FLAGS_1]
            if flags_1 & 0x1:
                self.bind_now = True
        
        if DynamicTag.DT_BIND_NOW in self.dynamic_info:
            self.bind_now = True
        
        self.needed_libs = self.parser.get_needed_libraries()
    
# Parse DT_VERSYM, DT_VERDEF and DT_VERNEED when they are present.
    def _parse_symbol_versions(self, load_offset: int) -> None:
        versym_addr = self.dynamic_info.get(DT_VERSYM, 0)
        verdef_addr = self.dynamic_info.get(DT_VERDEF, 0)
        verneed_addr = self.dynamic_info.get(DT_VERNEED, 0)
        
        if versym_addr:
            self._parse_versym(versym_addr, load_offset)
        
        if verdef_addr:
            self._parse_verdef(verdef_addr, load_offset)
        
        if verneed_addr:
            self._parse_verneed(verneed_addr, load_offset)
    
# Read the version index of every dynamic symbol.
    def _parse_versym(self, addr: int, load_offset: int) -> None:
        sym_count = len(self.parser.dynamic_symbols)
        for i in range(sym_count):
            try:
                versym = self._read_memory_int(addr + i * 2, 2)
                index = versym & 0x7fff
                is_hidden = (versym & 0x8000) != 0
                self.symbol_versions[i] = SymbolVersion(index=index, is_hidden=is_hidden)
            except MemoryAccessError:
                break
    
# Read the symbol versions this object defines.
    def _parse_verdef(self, addr: int, load_offset: int) -> None:
        strtab = self.dynamic_info.get(DynamicTag.DT_STRTAB, 0)
        if not strtab:
            return
            
        verdefnum = self.dynamic_info.get(DT_VERDEF, 0)
        current_addr = addr
        
        while current_addr:
            try:
# Elf64_Verdef: vd_version@0 u16, vd_flags@2 u16, vd_ndx@4 u16,
# vd_cnt@6 u16, vd_hash@8 u32, vd_aux@12 u32, vd_next@16 u32.
                vd_ndx = self._read_memory_int(current_addr + 4, 2)
                vd_name_off = self._read_memory_int(current_addr + 20, 4)
                vd_next = self._read_memory_int(current_addr + 16, 4)
                
                name = self._read_string(strtab + vd_name_off)
                self.verdef.append((vd_ndx, name))
                
                current_addr = current_addr + vd_next if vd_next else 0
            except MemoryAccessError:
                break
    
# Read the symbol versions this object needs from other objects.
    def _parse_verneed(self, addr: int, load_offset: int) -> None:
        strtab = self.dynamic_info.get(DynamicTag.DT_STRTAB, 0)
        if not strtab:
            return
            
        current_addr = addr
        
        while current_addr:
            try:
# Elf64_Verneed: vn_version@0 u16, vn_cnt@2 u16, vn_file@4 u32,
# vn_aux@8 u32, vn_next@12 u32.
                vn_file_off = self._read_memory_int(current_addr + 4, 4)
                vn_cnt = self._read_memory_int(current_addr + 2, 2)
                vn_next = self._read_memory_int(current_addr + 12, 4)
                
                filename = self._read_string(strtab + vn_file_off)
                self.verneed[filename] = []
                
                vernaux_addr = current_addr + 8
                for _ in range(vn_cnt):
# Elf64_Vernaux: vna_hash@0 u32, vna_flags@4 u16,
# vna_other@6 u16, vna_name@8 u32, vna_next@12 u32.
                    vna_hash = self._read_memory_int(vernaux_addr + 0, 4)
                    vna_name_off = self._read_memory_int(vernaux_addr + 8, 4)
                    vna_next = self._read_memory_int(vernaux_addr + 12, 4)
                    
                    name = self._read_string(strtab + vna_name_off)
                    self.verneed[filename].append((vna_hash, name))
                    
                    vernaux_addr = vernaux_addr + vna_next if vna_next else 0
                
                current_addr = current_addr + vn_next if vn_next else 0
            except MemoryAccessError:
                break
    
# Record the addresses of the static and the dynamic symbols.
    def _parse_symbols(self, load_offset: int) -> None:
        for sym in self.parser.symbols:
            if sym.name and sym.st_value != 0:
                addr = sym.st_value + load_offset
                if sym.st_shndx != SpecialSectionIndex.SHN_ABS:
                    addr = sym.st_value + load_offset
                else:
                    addr = sym.st_value
                self.symbols[sym.name] = addr
                self.symbols_by_addr[addr] = sym.name
        
        for i, sym in enumerate(self.parser.dynamic_symbols):
            if sym.name:
                self.dynamic_symbols[sym.name] = (sym.st_value, sym.st_size, i)
                if sym.st_value != 0:
                    addr = sym.st_value + load_offset
                    if sym.st_shndx != SpecialSectionIndex.SHN_ABS:
                        addr = sym.st_value + load_offset
                    else:
                        addr = sym.st_value
                    self.symbols[sym.name] = addr
    
# Locate the PLT and the GOT, then index the PLT relocations.
    def _setup_plt_got(self, load_offset: int) -> None:
        plt_addr = 0
        got_addr = 0
        got_plt_addr = 0
        jmprel_addr = self.dynamic_info.get(DynamicTag.DT_JMPREL, 0)
        jmprel_size = self.dynamic_info.get(DynamicTag.DT_PLTRELSZ, 0)
        
        for section in self.parser.section_headers:
            if section.name == '.plt':
                plt_addr = section.sh_addr + load_offset
            elif section.name == '.got.plt':
                got_plt_addr = section.sh_addr + load_offset
            elif section.name == '.got':
                got_addr = section.sh_addr + load_offset
        
        if not got_plt_addr:
            got_plt_addr = self.dynamic_info.get(DynamicTag.DT_PLTGOT, 0)
        
# .got holds the GOT proper, so it is the real base whenever the section exists;
# only the stripped .got.plt layout and DT_PLTGOT point at the first PLT slot instead.
        self.got_plt_base = got_addr or got_plt_addr
        
        if jmprel_addr and jmprel_size:
            self._parse_plt_entries(jmprel_addr, jmprel_size, load_offset, 
                                   plt_addr, got_plt_addr)
    
# Turn the DT_JMPREL table into PLT and GOT entries.
    def _parse_plt_entries(self, jmprel_addr: int, jmprel_size: int, 
                          load_offset: int, plt_addr: int, got_plt_addr: int) -> None:
        pltrel_type = self.dynamic_info.get(DynamicTag.DT_PLTREL, DynamicTag.DT_RELA)
        ent_size = 24 if pltrel_type == DynamicTag.DT_RELA else 16
        if self.parser.is_32bit:
            ent_size = 12 if pltrel_type == DynamicTag.DT_RELA else 8
        
        num_entries = jmprel_size // ent_size
        plt_entry_size = 16 if self.parser.is_32bit else 16
        
        for i in range(num_entries):
            entry_addr = jmprel_addr + i * ent_size
            
            if self.parser.is_32bit:
                r_offset = self._read_memory_int(entry_addr, 4)
                r_info = self._read_memory_int(entry_addr + 4, 4)
                r_addend = self._read_memory_int(entry_addr + 8, 4, signed=True) if pltrel_type == DynamicTag.DT_RELA else 0
            else:
                r_offset = self._read_memory_int(entry_addr, 8)
                r_info = self._read_memory_int(entry_addr + 8, 8)
                r_addend = self._read_memory_int(entry_addr + 16, 8, signed=True) if pltrel_type == DynamicTag.DT_RELA else 0
            
            sym_idx = r_info >> 32 if not self.parser.is_32bit else r_info >> 8
            
            if sym_idx < len(self.parser.dynamic_symbols):
                sym = self.parser.dynamic_symbols[sym_idx]
                got_entry_addr = r_offset + load_offset
                
                plt_entry_addr = plt_addr + (i + 1) * plt_entry_size if plt_addr else 0
                
                entry = PLTEntry(
                    addr=plt_entry_addr,
                    symbol_name=sym.name,
                    symbol_index=sym_idx,
                    got_addr=got_entry_addr
                )
                
                if plt_entry_addr:
                    self.plt_entries[plt_entry_addr] = entry
                    self.plt_by_name[sym.name] = plt_entry_addr
                
                self.got_entries[got_entry_addr] = 0
    
# Apply the Rela, Rel, PLT and section relocations exactly once.
    def _perform_relocations(self, load_offset: int) -> None:
        if self.relocations_done:
            return
        
        rela_addr = self.dynamic_info.get(DynamicTag.DT_RELA, 0)
        rela_size = self.dynamic_info.get(DynamicTag.DT_RELASZ, 0)
        rela_ent = self.dynamic_info.get(DynamicTag.DT_RELAENT, 
                                         24 if not self.parser.is_32bit else 12)
        
        rel_addr = self.dynamic_info.get(DynamicTag.DT_REL, 0)
        rel_size = self.dynamic_info.get(DynamicTag.DT_RELSZ, 0)
        rel_ent = self.dynamic_info.get(DynamicTag.DT_RELENT,
                                        16 if not self.parser.is_32bit else 8)
        
        jmprel_addr = self.dynamic_info.get(DynamicTag.DT_JMPREL, 0)
        jmprel_size = self.dynamic_info.get(DynamicTag.DT_PLTRELSZ, 0)
        plt_rel_type = self.dynamic_info.get(DynamicTag.DT_PLTREL, DynamicTag.DT_RELA)
        
        if rela_addr and rela_size:
            self._process_rela_relocations(rela_addr, rela_size, rela_ent, load_offset)
        
        if rel_addr and rel_size:
            self._process_rel_relocations(rel_addr, rel_size, rel_ent, load_offset)
        
        if jmprel_addr and jmprel_size:
            ent_size = 24 if plt_rel_type == DynamicTag.DT_RELA else 16
            if self.parser.is_32bit:
                ent_size = 12 if plt_rel_type == DynamicTag.DT_RELA else 8
            self._process_rela_relocations(jmprel_addr, jmprel_size, ent_size, load_offset)
        
        for rel in self.parser.relocations:
            self._apply_relocation_from_parsed(rel, load_offset)
        
        self.relocations_done = True
    
# Walk a Rela table and apply every entry in it.
    def _process_rela_relocations(self, addr: int, size: int, ent_size: int, 
                                  load_offset: int) -> None:
        num_entries = size // ent_size
        
        for i in range(num_entries):
            entry_addr = addr + i * ent_size
            
            if self.parser.is_32bit:
                r_offset = self._read_memory_int(entry_addr, 4)
                r_info = self._read_memory_int(entry_addr + 4, 4)
                r_addend = self._read_memory_int(entry_addr + 8, 4, signed=True)
            else:
                r_offset = self._read_memory_int(entry_addr, 8)
                r_info = self._read_memory_int(entry_addr + 8, 8)
                r_addend = self._read_memory_int(entry_addr + 16, 8, signed=True)
            
            rel = ELFRelocationA(
                r_offset=r_offset,
                r_info=r_info,
                r_addend=r_addend
            )
            self._apply_relocation(rel, load_offset)
    
# Walk a Rel table and apply every entry in it.
    def _process_rel_relocations(self, addr: int, size: int, ent_size: int,
                                load_offset: int) -> None:
        num_entries = size // ent_size
        
        for i in range(num_entries):
            entry_addr = addr + i * ent_size
            
            if self.parser.is_32bit:
                r_offset = self._read_memory_int(entry_addr, 4)
                r_info = self._read_memory_int(entry_addr + 4, 4)
            else:
                r_offset = self._read_memory_int(entry_addr, 8)
                r_info = self._read_memory_int(entry_addr + 8, 8)
            
            rel = ELFRelocation(r_offset=r_offset, r_info=r_info)
            self._apply_relocation(rel, load_offset)
    
# Apply a relocation the parser has already decoded.
    def _apply_relocation_from_parsed(self, rel: Union[ELFRelocation, ELFRelocationA],
                                     load_offset: int) -> None:
        self._apply_relocation(rel, load_offset)
    
# Resolve the symbol, compute the new value and write it back.
    def _apply_relocation(self, rel: Union[ELFRelocation, ELFRelocationA],
                         load_offset: int) -> None:
        addr = rel.r_offset
        sym_idx = rel.sym
        rel_type = rel.type
        addend = getattr(rel, 'r_addend', 0)
        
        if self.parser.is_32bit:
            addend = addend & 0xffffffff
        
        sym_value = 0
        sym_name = ""
        sym_size = 0
        
        if sym_idx > 0:
            if sym_idx < len(self.parser.dynamic_symbols):
                sym = self.parser.dynamic_symbols[sym_idx]
                sym_name = sym.name
                
                if not sym.is_undefined:
                    if sym.st_shndx == SpecialSectionIndex.SHN_ABS:
                        sym_value = sym.st_value
                    else:
                        sym_value = sym.st_value + load_offset
                    sym_size = sym.st_size
                else:
                    sym_value = self._resolve_external_symbol(sym_name)
                    if sym_value is None:
                        if sym.bind == SymbolBinding.STB_WEAK:
                            sym_value = 0
                        else:
                            logger.warning(f"Unresolved symbol: {sym_name}")
                            if self.strict_protection:
                                raise SymbolResolutionError(f"Unresolved symbol: {sym_name}")
                            sym_value = 0
        
        if self.parser.is_32bit:
            new_value = self._calc_relocation_i386(rel_type, addr, sym_value, 
                                                   addend, load_offset, sym_name, sym_size)
            size = 4
        else:
            new_value = self._calc_relocation_x86_64(rel_type, addr, sym_value,
                                                     addend, load_offset, sym_name, sym_size)
            size = 8
        
        if new_value is not None:
            try:
                if rel_type in (RelocationTypeX86_64.R_X86_64_32, 
                               RelocationTypeX86_64.R_X86_64_32S,
                               RelocationTypeI386.R_386_32, 
                               RelocationTypeI386.R_386_PC32):
                    size = 4
                elif rel_type in (RelocationTypeX86_64.R_X86_64_16,
                                 RelocationTypeI386.R_386_16):
                    size = 2
                elif rel_type in (RelocationTypeX86_64.R_X86_64_8,
                                 RelocationTypeI386.R_386_8):
                    size = 1
                
                self._write_memory_int(addr, new_value, size)
            except MemoryAccessError as e:
                logger.warning(f"Relocation write failed at 0x{addr:x}: {e}")
    
# Return a symbol's address, asking the external resolver if needed.
    def _resolve_external_symbol(self, name: str) -> Optional[int]:
        if name in self.symbols:
            return self.symbols[name]
        
        if self._external_symbol_resolver:
            return self._external_symbol_resolver(name)
        
        return None
    
# Return the new value for one x86_64 relocation, None meaning write nothing.
    def _calc_relocation_x86_64(self, rel_type: int, addr: int, sym_value: int,
                                addend: int, load_offset: int, sym_name: str,
                                sym_size: int) -> Optional[int]:
        if rel_type == RelocationTypeX86_64.R_X86_64_NONE:
            return None
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_64:
            return sym_value + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_PC32:
            return (sym_value + addend - addr) & 0xffffffff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_GOT32:
            return self._get_got_entry(sym_name, sym_value) + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_PLT32:
            if sym_value != 0:
                return (sym_value + addend - addr) & 0xffffffff
            plt_addr = self.plt_by_name.get(sym_name, 0)
            if plt_addr:
                return (plt_addr + addend - addr) & 0xffffffff
            return 0
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_COPY:
            if sym_value != 0 and sym_size > 0:
                try:
                    data = self._read_memory(sym_value, sym_size)
                    self._write_memory(addr, data)
                except MemoryAccessError:
                    pass
            return None
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_GLOB_DAT:
            return sym_value + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_JUMP_SLOT:
            return sym_value
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_RELATIVE:
            return load_offset + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_GOTPCREL:
            got_addr = self._get_got_entry(sym_name, sym_value)
            return (got_addr + addend - addr) & 0xffffffff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_32:
            return (sym_value + addend) & 0xffffffff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_32S:
            value = sym_value + addend
            if value > 0x7fffffff or value < -0x80000000:
                logger.warning(f"R_X86_64_32S overflow: {value}")
            return value & 0xffffffff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_16:
            return (sym_value + addend) & 0xffff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_PC16:
            return (sym_value + addend - addr) & 0xffff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_8:
            return (sym_value + addend) & 0xff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_PC8:
            return (sym_value + addend - addr) & 0xff
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_DTPMOD64:
            if self.tls_info:
                return self.tls_module_id
            return 0
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_DTPOFF64:
            return sym_value + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_TPOFF64:
            if self.tls_info:
                return sym_value - self.tls_info.offset + addend
            return sym_value + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_GOTTPOFF:
            if self.tls_info:
                got_addr = self._allocate_got_entry()
                self._write_memory_int(got_addr, sym_value - self.tls_info.offset, 8)
                return (got_addr + addend - addr) & 0xffffffff
            return 0
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_SIZE32:
            return sym_size + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_SIZE64:
            return sym_size + addend
        
        elif rel_type == RelocationTypeX86_64.R_X86_64_IRELATIVE:
            resolver_addr = load_offset + addend
# the resolver wants the address of the GOT slot it is filling in
            return self._call_ifunc_resolver(resolver_addr, addr)
        
        else:
            logger.debug(f"Unhandled relocation type: {rel_type}")
            return None
    
# Return the new value for one i386 relocation, None meaning write nothing.
    def _calc_relocation_i386(self, rel_type: int, addr: int, sym_value: int,
                              addend: int, load_offset: int, sym_name: str,
                              sym_size: int) -> Optional[int]:
        if rel_type == RelocationTypeI386.R_386_NONE:
            return None
        
        elif rel_type == RelocationTypeI386.R_386_32:
            return (sym_value + addend) & 0xffffffff
        
        elif rel_type == RelocationTypeI386.R_386_PC32:
            return (sym_value + addend - addr) & 0xffffffff
        
        elif rel_type == RelocationTypeI386.R_386_GOT32:
            return self._get_got_entry(sym_name, sym_value) + addend
        
        elif rel_type == RelocationTypeI386.R_386_PLT32:
            if sym_value != 0:
                return (sym_value + addend - addr) & 0xffffffff
            plt_addr = self.plt_by_name.get(sym_name, 0)
            if plt_addr:
                return (plt_addr + addend - addr) & 0xffffffff
            return 0
        
        elif rel_type == RelocationTypeI386.R_386_COPY:
            if sym_value != 0 and sym_size > 0:
                try:
                    data = self._read_memory(sym_value, sym_size)
                    self._write_memory(addr, data)
                except MemoryAccessError:
                    pass
            return None
        
        elif rel_type == RelocationTypeI386.R_386_GLOB_DAT:
            return sym_value
        
        elif rel_type == RelocationTypeI386.R_386_JUMP_SLOT:
            return sym_value
        
        elif rel_type == RelocationTypeI386.R_386_RELATIVE:
            return (load_offset + addend) & 0xffffffff
        
        elif rel_type == RelocationTypeI386.R_386_GOTOFF:
            return (sym_value - self.got_plt_base + addend) & 0xffffffff
        
        elif rel_type == RelocationTypeI386.R_386_GOTPC:
            return (self.got_plt_base + addend - addr) & 0xffffffff
        
        elif rel_type == RelocationTypeI386.R_386_16:
            return (sym_value + addend) & 0xffff
        
        elif rel_type == RelocationTypeI386.R_386_PC16:
            return (sym_value + addend - addr) & 0xffff
        
        elif rel_type == RelocationTypeI386.R_386_8:
            return (sym_value + addend) & 0xff
        
        elif rel_type == RelocationTypeI386.R_386_PC8:
            return (sym_value + addend - addr) & 0xff
        
        elif rel_type == RelocationTypeI386.R_386_TLS_TPOFF:
            if self.tls_info:
                return sym_value - self.tls_info.offset + addend
            return sym_value + addend
        
        elif rel_type == RelocationTypeI386.R_386_TLS_IE:
            if self.tls_info:
                return sym_value - self.tls_info.offset + addend
            return 0
        
        elif rel_type == RelocationTypeI386.R_386_TLS_GOTIE:
            got_addr = self._allocate_got_entry()
            if self.tls_info:
                self._write_memory_int(got_addr, sym_value - self.tls_info.offset, 4)
            return (got_addr + addend - addr) & 0xffffffff
        
        elif rel_type == RelocationTypeI386.R_386_TLS_LE:
            if self.tls_info:
                return sym_value - self.tls_info.offset + addend
            return 0
        
        elif rel_type == RelocationTypeI386.R_386_IRELATIVE:
            resolver_addr = load_offset + addend
# the resolver wants the address of the GOT slot it is filling in
            return self._call_ifunc_resolver(resolver_addr, addr)
        
        else:
            logger.debug(f"Unhandled i386 relocation type: {rel_type}")
            return None
    
# Return the GOT slot holding sym_value, recycling a free slot when there is one.
    def _get_got_entry(self, sym_name: str, sym_value: int) -> int:
        for got_addr, value in self.got_entries.items():
            if value == sym_value or value == 0:
                self.got_entries[got_addr] = sym_value
                return got_addr
        
        got_addr = self._allocate_got_entry()
        self.got_entries[got_addr] = sym_value
        return got_addr
    
# Hand out an unused GOT slot, skipping the three reserved entries.
    def _allocate_got_entry(self) -> int:
        if self.got_plt_base:
            for i in range(3, 100):
                addr = self.got_plt_base + i * 8
                if addr not in self.got_entries:
                    self.got_entries[addr] = 0
                    return addr
        
        return 0
    
# Return an address in a mapped writable page that guest code never reaches; it is only
# used as the return target of call_function, so nothing is planted at it.
    def scratch_address(self) -> int:
        stack_region = self.memory.get(self.stack_bottom)
        if stack_region and stack_region.writable and stack_region.size > 64:
            return self.stack_bottom + 16
        
        for region in self.memory.values():
            if region.writable and region.size > 64:
                return region.start + 16
        
        return 0
    
# Call a guest function on cpu with args and return RAX, 0 when it could not be run.
    def call_function(self, cpu: Any, func_addr: int, args: List[int],
                      budget: int = 100000) -> int:
        returned, result = self._call_guest_function(cpu, func_addr, args, budget)
        return result
    
# Call a guest function on cpu with args; returns whether it returned, and RAX.
    def _call_guest_function(self, cpu: Any, func_addr: int, args: List[int],
                             budget: int = 100000) -> Tuple[bool, int]:
        if cpu is None or not func_addr:
            return False, 0
        
        sentinel = self.scratch_address()
        if not sentinel:
            logger.warning(f"Cannot call 0x{func_addr:x}: no writable page for a return address")
            return False, 0
        
        is_64bit = not self.parser.is_32bit
        ptr_size = 8 if is_64bit else 4
        fmt = '<Q' if is_64bit else '<I'
        mask = (1 << (ptr_size * 8)) - 1
        
# the SysV integer argument registers; i386 cdecl passes everything on the stack
        arg_regs = [7, 6, 2, 1, 8, 9] if is_64bit else []
        
        saved_regs = dict(cpu.state.regs)
        saved_ip = cpu._get_ip()
        
# Push one machine word below sp and return the new stack pointer.
        def push(value: int) -> int:
            sp = cpu._get_sp() - ptr_size
            cpu.memory.write_bytes(sp, struct.pack(fmt, value & mask))
            cpu._set_sp(sp)
            return sp
        
        try:
            for reg, arg in zip(arg_regs, args):
                cpu._set_reg(reg, arg)
            
            if not arg_regs:
                for arg in reversed(args):
                    push(arg)
            
# the ABI wants the stack pointer 8 mod 16 once the return address is on the stack
            if is_64bit:
                while (cpu._get_sp() - ptr_size) % 16 != 8:
                    push(0)
            
            push(sentinel)
            cpu._set_ip(func_addr)
            
            return self._step_call(cpu, func_addr, sentinel, budget)
            
        finally:
            cpu.state.regs = saved_regs
            cpu._set_ip(saved_ip)
    
# Single step until the helper call returns to its sentinel, servicing any SYSCALL.
    def _step_call(self, cpu: Any, func_addr: int, sentinel: int,
                   budget: int) -> Tuple[bool, int]:
        from .cpu_emulator import SyscallInterrupt
        
        for _ in range(budget):
            if cpu._get_ip() == sentinel:
                return True, cpu._get_reg(0)
            
            try:
                name, length, operands = cpu.decoder.decode(cpu.memory, cpu._get_ip())
                cpu._execute(name, length, operands)
            except SyscallInterrupt as e:
# a helper that reads a file or writes to the console still has to make progress
                if not cpu.syscall_handler:
                    raise
                cpu._set_reg(0, cpu.syscall_handler(e.number, *e.syscall_args))
            except SystemExit:
# a guest exit inside a helper call ends the run, as it would in a real process
                raise
            except Exception as e:
                logger.warning(f"Call to 0x{func_addr:x} stopped at 0x{cpu._get_ip():x}: {e}")
                return False, 0
        
        logger.warning(f"Call to 0x{func_addr:x} did not return within {budget} instructions")
        return False, 0
    
# Resolve an IFUNC target by really running the resolver, which takes the GOT slot
# address in RDI and returns the chosen address in RAX.
    def _call_ifunc_resolver(self, resolver_addr: int, got_slot: int = 0) -> int:
        cpu = self._helper_cpu()
        if cpu is None:
            logger.warning(f"IFUNC resolver at 0x{resolver_addr:x} not run: no CPU available")
            return 0
        
        returned, result = self._call_guest_function(cpu, resolver_addr, [got_slot])
        if not returned or not result:
            logger.warning(f"IFUNC resolver at 0x{resolver_addr:x} produced no address")
        return result
    
# Return a CPU that can run short helper calls, building it on first use.
    def _helper_cpu(self) -> Any:
        if self._helper_cpu_obj is None:
            try:
                from .cpu_emulator import CPUEmulator
            except Exception as e:
                logger.warning(f"No CPU available for helper calls: {e}")
                return None
            self._helper_cpu_obj = CPUEmulator(self)
        return self._helper_cpu_obj
    
# Record the PT_TLS template and give it a module id.
    def _setup_tls(self, load_offset: int) -> None:
        for ph in self.parser.program_headers:
            if ph.p_type == ProgramHeaderType.PT_TLS:
                self.tls_info = TLSInfo(
                    template_addr=ph.p_vaddr + load_offset,
                    template_size=ph.p_filesz,
                    memsz=ph.p_memsz,
                    filesz=ph.p_filesz,
                    align=max(ph.p_align, 1),
                    first_byte=0
                )
                self.tls_module_id = TLSModule().id
                
                self.tls_info.offset = align_up(self.tls_info.memsz, self.tls_info.align)
                break
    
# Gather the preinit, init and fini function addresses.
    def _collect_init_fini(self, load_offset: int) -> None:
        init_addr = self.dynamic_info.get(DynamicTag.DT_INIT, 0)
        fini_addr = self.dynamic_info.get(DynamicTag.DT_FINI, 0)
        
        if init_addr:
            self.init_functions.append(init_addr)
        if fini_addr:
            self.fini_functions.append(fini_addr)
        
        init_array_addr = self.dynamic_info.get(DynamicTag.DT_INIT_ARRAY, 0)
        init_array_size = self.dynamic_info.get(DynamicTag.DT_INIT_ARRAYSZ, 0)
        
        if init_array_addr and init_array_size:
            ptr_size = 8 if not self.parser.is_32bit else 4
            num_entries = init_array_size // ptr_size
            
            for i in range(num_entries):
                try:
                    func_ptr = self._read_memory_int(init_array_addr + i * ptr_size, ptr_size)
                    if func_ptr != 0:
                        self.init_functions.append(func_ptr)
                except MemoryAccessError:
                    break
        
        fini_array_addr = self.dynamic_info.get(DynamicTag.DT_FINI_ARRAY, 0)
        fini_array_size = self.dynamic_info.get(DynamicTag.DT_FINI_ARRAYSZ, 0)
        
        if fini_array_addr and fini_array_size:
            ptr_size = 8 if not self.parser.is_32bit else 4
            num_entries = fini_array_size // ptr_size
            
            for i in range(num_entries):
                try:
                    func_ptr = self._read_memory_int(fini_array_addr + i * ptr_size, ptr_size)
                    if func_ptr != 0:
                        self.fini_functions.append(func_ptr)
                except MemoryAccessError:
                    break
        
        preinit_array_addr = self.dynamic_info.get(DynamicTag.DT_PREINIT_ARRAY, 0)
        preinit_array_size = self.dynamic_info.get(DynamicTag.DT_PREINIT_ARRAYSZ, 0)
        
        if preinit_array_addr and preinit_array_size:
            ptr_size = 8 if not self.parser.is_32bit else 4
            num_entries = preinit_array_size // ptr_size
            
            for i in range(num_entries):
                try:
                    func_ptr = self._read_memory_int(preinit_array_addr + i * ptr_size, ptr_size)
                    if func_ptr != 0:
                        self.preinit_functions.append(func_ptr)
                except MemoryAccessError:
                    break
    
# Place the heap past the highest segment and give it a first extent.
    def _setup_heap(self) -> None:
        max_addr = 0
        for seg in self.segments:
            end = seg.vaddr + seg.memsz
            if end > max_addr:
                max_addr = end
        
        page_aligned_end = align_up(max_addr, PAGE_SIZE)
        
        self.heap_start = page_aligned_end
        self.brk = self.heap_start
        
        initial_heap_size = PAGE_SIZE * 4
        heap_region = MemoryRegion(
            start=self.heap_start,
            size=initial_heap_size,
            data=bytearray(initial_heap_size),
            flags=MemoryProtection.RW,
            name="heap",
            growable=True
        )
        self.memory[self.heap_start] = heap_region
    
# Grow the heap to cover addr; returns the break, or the old one if the request is refused.
    def brk_extend(self, addr: int) -> int:
        if addr < self.heap_start:
            return self.brk
        
        heap_region = self.memory.get(self.heap_start)
        if not heap_region:
            return self.brk
        
        current_end = self.heap_start + heap_region.size
        
        if addr > current_end:
            new_size = align_up(addr - self.heap_start, PAGE_SIZE)
            max_heap_size = 128 * 1024 * 1024
            if new_size > max_heap_size:
                return self.brk
            
            old_data = heap_region.data
            heap_region.data = bytearray(new_size)
            heap_region.data[:len(old_data)] = old_data
            heap_region.size = new_size
        
        self.brk = addr
        return self.brk
    
# Map the stack region and record its bounds.
    def _create_stack(self) -> None:
        if self.parser.is_32bit:
            stack_top = self.STACK_TOP_32
        else:
            stack_top = self.STACK_TOP_64
        
        stack_bottom = stack_top - self.STACK_SIZE
        
        stack_region = MemoryRegion(
            start=stack_bottom,
            size=self.STACK_SIZE,
            data=bytearray(self.STACK_SIZE),
            flags=MemoryProtection.RW,
            name="stack",
            growable=True
        )
        
        self.memory[stack_bottom] = stack_region
        self.stack_top = stack_top
        self.stack_bottom = stack_bottom
    
# Build the auxiliary vector that the guest's _start reads.
    def _build_auxv(self, load_offset: int) -> None:
        self.auxv = []
        
        self.auxv.append(AuxvEntry(AuxvType.AT_PHDR, self.phdr_addr))
        self.auxv.append(AuxvEntry(AuxvType.AT_PHENT, self.phdr_ent_size))
        self.auxv.append(AuxvEntry(AuxvType.AT_PHNUM, self.phdr_count))
        self.auxv.append(AuxvEntry(AuxvType.AT_PAGESZ, PAGE_SIZE))
        # No interpreter image is loaded (PT_INTERP is not mapped), so there
        # is no base address to report; 0 is the true value, not a placeholder.
        self.auxv.append(AuxvEntry(AuxvType.AT_BASE, 0))
        self.auxv.append(AuxvEntry(AuxvType.AT_FLAGS, 0))
        self.auxv.append(AuxvEntry(AuxvType.AT_ENTRY, self.entry_point))
        self.auxv.append(AuxvEntry(AuxvType.AT_UID, 1000))
        self.auxv.append(AuxvEntry(AuxvType.AT_EUID, 1000))
        self.auxv.append(AuxvEntry(AuxvType.AT_GID, 1000))
        self.auxv.append(AuxvEntry(AuxvType.AT_EGID, 1000))
        self.auxv.append(AuxvEntry(AuxvType.AT_CLKTCK, 100))
        self.auxv.append(AuxvEntry(AuxvType.AT_SECURE, 0))
        
        random_bytes = random.randbytes(16)
        random_addr = self._allocate_auxv_storage(random_bytes)
        self.auxv.append(AuxvEntry(AuxvType.AT_RANDOM, random_addr))
        
        self.auxv.append(AuxvEntry(AuxvType.AT_NULL, 0))
    
# Park bytes near the top of the stack and return where they landed.
    def _allocate_auxv_storage(self, data: bytes) -> int:
        stack_region = self.memory.get(self.stack_bottom)
        if stack_region:
            offset = len(stack_region.data) - len(data) - 256
            stack_region.data[offset:offset + len(data)] = data
            return self.stack_bottom + offset
        return 0
    
# Run the preinit and init functions on the CPU; initialized is set only when every
# one of them returned, so a skipped constructor never passes for a completed one.
    def run_init_functions(self, cpu_emulator: Any) -> None:
        self.initialized = False
        
        skipped = [func_addr for func_addr in self.preinit_functions + self.init_functions
                   if not self._run_constructor(func_addr, cpu_emulator)]
        
        if skipped:
            logger.warning(f"Init functions not run: "
                           f"{', '.join(f'0x{a:x}' for a in skipped)}")
            return
        
        self.initialized = True
    
# Run the fini functions in reverse order, as the ABI requires.
    def run_fini_functions(self, cpu_emulator: Any) -> None:
        for func_addr in reversed(self.fini_functions):
            self._run_constructor(func_addr, cpu_emulator)
    
# Call one constructor on the CPU; False means it did not return normally.
    def _run_constructor(self, func_addr: int, cpu_emulator: Any) -> bool:
        if not func_addr or cpu_emulator is None:
            logger.warning(f"Constructor at 0x{func_addr:x} not run: no CPU available")
            return False
        
        logger.debug(f"Running constructor at 0x{func_addr:x}")
        returned, _ = self._call_guest_function(cpu_emulator, func_addr, [],
                                               budget=CONSTRUCTOR_BUDGET)
        if not returned:
            logger.warning(f"Constructor at 0x{func_addr:x} did not return")
        return returned
    
# Read size bytes, walking the regions one byte at a time.
    def read_memory(self, addr: int, size: int) -> bytes:
        result = bytearray()
        for i in range(size):
            cur_addr = addr + i
            region = None
            for start, r in self.memory.items():
                if r.start <= cur_addr < r.start + r.size:
                    region = r
                    break
            if region is None:
                raise MemoryAccessError(cur_addr, False)
            offset = cur_addr - region.start
            result.append(region.data[offset])
        return bytes(result)
    
# Write data, walking the regions one byte at a time. The region's own write path is
# used, so strict_protection applies to the syscall emulator just as it does elsewhere.
    def write_memory(self, addr: int, data: bytes) -> None:
        for i, byte in enumerate(data):
            cur_addr = addr + i
            region = None
            for start, r in self.memory.items():
                if r.start <= cur_addr < r.start + r.size:
                    region = r
                    break
            if region is None:
                raise MemoryAccessError(cur_addr, True)
            region.write(cur_addr, bytes((byte,)))
    
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
        data = struct.pack('<' + fmt, value & (max_val - 1))
        self.write_memory(addr, data)
    
# Lay out argc, argv, envp and the auxiliary vector on the stack; returns (sp, argc).
    def setup_argv_envp(self, argv: List[str], envp: Dict[str, str]) -> Tuple[int, int]:
        ptr_size = 8 if not self.parser.is_32bit else 4
        
        total_size = 0
        for arg in argv:
            total_size += len(arg.encode()) + 1
        for key, val in envp.items():
            total_size += len(f"{key}={val}".encode()) + 1
        
        total_size += (len(argv) + 1) * ptr_size
        total_size += (len(envp) + 1) * ptr_size
        total_size += 8 * ptr_size
        
        total_size = align_up(total_size, 16)
        
        stack_region = self.memory.get(self.stack_bottom)
        if not stack_region:
            return 0, 0
        
        sp = self.stack_top - total_size
        sp = align_down(sp, 16)
        
        data_ptr = sp + (len(argv) + 1 + len(envp) + 1 + 2) * ptr_size
        
        argc = len(argv)
        self._write_memory_int(sp, argc, ptr_size)
        current = sp + ptr_size
        
        for i, arg in enumerate(argv):
            arg_bytes = arg.encode() + b'\x00'
            self._write_memory(current, arg_bytes)
            self._write_memory_int(current, data_ptr, ptr_size)
            self._write_memory_int(sp + (i + 1) * ptr_size, data_ptr, ptr_size)
            data_ptr += len(arg_bytes)
            current += ptr_size
        
        self._write_memory_int(current, 0, ptr_size)
        current += ptr_size
        
        envp_start = current
        for i, (key, val) in enumerate(envp.items()):
            env_str = f"{key}={val}".encode() + b'\x00'
            self._write_memory(current, env_str)
            self._write_memory_int(current, data_ptr, ptr_size)
            self._write_memory_int(envp_start + i * ptr_size, data_ptr, ptr_size)
            data_ptr += len(env_str)
            current += ptr_size
        
        self._write_memory_int(current, 0, ptr_size)
        current += ptr_size
        
        for auxv in self.auxv:
            if self.parser.is_32bit:
                self._write_memory_int(current, auxv.key, 4)
                self._write_memory_int(current + 4, auxv.value, 4)
                current += 8
            else:
                self._write_memory_int(current, auxv.key, 8)
                self._write_memory_int(current + 8, auxv.value, 8)
                current += 16
        
        return sp, argc
    
# Install the callback used for symbols the image does not define.
    def set_external_symbol_resolver(self, resolver: Callable[[str], Optional[int]]) -> None:
        self._external_symbol_resolver = resolver
    
# Read inside the one region that contains addr.
    def _read_memory(self, addr: int, size: int) -> bytes:
        for region in self.memory.values():
            if region.contains(addr):
                return region.read(addr, size)
        raise MemoryAccessError(f"Cannot read memory at 0x{addr:x}")
    
# Write inside the one region that contains addr.
    def _write_memory(self, addr: int, data: bytes) -> None:
        for region in self.memory.values():
            if region.contains(addr):
                region.write(addr, data)
                return
        raise MemoryAccessError(f"Cannot write memory at 0x{addr:x}")
    
# Read an integer inside the one region that contains addr.
    def _read_memory_int(self, addr: int, size: int, signed: bool = False) -> int:
        for region in self.memory.values():
            if region.contains(addr):
                return region.read_int(addr, size, signed)
        raise MemoryAccessError(f"Cannot read memory at 0x{addr:x}")
    
# Write an integer inside the one region that contains addr.
    def _write_memory_int(self, addr: int, value: int, size: int) -> None:
        for region in self.memory.values():
            if region.contains(addr):
                region.write_int(addr, value, size)
                return
        raise MemoryAccessError(f"Cannot write memory at 0x{addr:x}")
    
# Read a NUL-terminated string.
    def _read_string(self, addr: int) -> str:
        result = bytearray()
        while True:
            byte = self._read_memory_int(addr, 1)
            if byte == 0:
                break
            result.append(byte)
            addr += 1
        return result.decode('utf-8', errors='replace')
    
# Return the region containing addr, or None.
    def get_memory_region(self, addr: int) -> Optional[MemoryRegion]:
        for region in self.memory.values():
            if region.contains(addr):
                return region
        return None
    
# Return the name of the symbol at addr, if there is one.
    def get_symbol_at(self, addr: int) -> Optional[str]:
        return self.symbols_by_addr.get(addr)
    
# Return a copy of the name to address map.
    def get_all_symbols(self) -> Dict[str, int]:
        return dict(self.symbols)
    
# Return (start, size, name, flags) per region, sorted by address.
    def get_memory_map(self) -> List[Tuple[int, int, str, int]]:
        result = []
        for start, region in self.memory.items():
            result.append((start, region.size, region.name, region.flags))
        return sorted(result, key=lambda x: x[0])
    
# Resolve a name through the image first, then the external resolver.
    def resolve_symbol(self, name: str) -> Optional[int]:
        if name in self.symbols:
            return self.symbols[name]
        return self._resolve_external_symbol(name)
    
# Return the (address, size) of the TLS template, or None.
    def get_tls_block(self) -> Optional[Tuple[int, int]]:
        if self.tls_info:
            return (self.tls_info.template_addr, self.tls_info.memsz)
        return None
    
# Report whether the image is an ET_DYN.
    def is_position_independent(self) -> bool:
        return self.parser.header.e_type == ELFType.ET_DYN
    
# Return the bias that was added to the file's addresses.
    def get_load_bias(self) -> int:
        if self.parser.header.e_type == ELFType.ET_EXEC:
            return 0
        return self.base_addr
    
# Summarise the loaded image for debugging.
    def __repr__(self) -> str:
        return (f"ELFLoader(entry=0x{self.entry_point:x}, "
                f"base=0x{self.base_addr:x}, "
                f"segments={len(self.segments)}, "
                f"symbols={len(self.symbols)}, "
                f"loaded={self.loaded})")
