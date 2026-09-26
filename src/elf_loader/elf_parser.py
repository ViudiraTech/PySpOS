'''
 *
 *      elf_parser.py
 *      ELF32/ELF64 header, section, symbol and relocation parsing.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import struct
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple, BinaryIO, Union
from io import BytesIO

from .elf_constants import (
    ELFMAG, SELFMAG,
    ELFClass, ELFData, ELFOSABI, ELFType, ELFMachine,
    ProgramHeaderType, ProgramHeaderFlags,
    SectionHeaderType, SectionHeaderFlags,
    DynamicTag, SymbolBinding, SymbolType,
    RelocationTypeX86_64, RelocationTypeI386,
    SpecialSectionIndex,
    PT_GNU_STACK, PT_GNU_RELRO, PT_GNU_PROPERTY,
    SHT_GNU_HASH, SHT_GNU_ATTRIBUTES, SHT_GNU_LIBLIST,
    SHT_CHECKSUM, SHT_GNU_VERDEF, SHT_GNU_VERNEED, SHT_GNU_VERSYM,
    DT_GNU_HASH, DT_VERSYM, DT_VERDEF, DT_VERNEED,
    DT_TLSDESC_PLT, DT_TLSDESC_GOT, DT_GNU_CONFLICT, DT_GNU_LIBLIST,
    DT_CONFIG, DT_DEPAUDIT, DT_AUDIT, DT_PLTPAD, DT_MOVETAB, DT_SYMINFO
)


# The e_ident block that opens every ELF file.
@dataclass
class ELFIdent:
    ei_mag: bytes           # magic number
    ei_class: int           # file class (32/64-bit)
    ei_data: int            # data encoding
    ei_version: int         # ELF version
    ei_osabi: int           # OS/ABI
    ei_abiversion: int      # ABI version
    ei_pad: bytes           # padding
    
# Report whether the file is a 32-bit object.
    @property
    def is_32bit(self) -> bool:
        return self.ei_class == ELFClass.ELFCLASS32
    
# Report whether the file is a 64-bit object.
    @property
    def is_64bit(self) -> bool:
        return self.ei_class == ELFClass.ELFCLASS64
    
# Report whether the file is little-endian.
    @property
    def is_little_endian(self) -> bool:
        return self.ei_data == ELFData.ELFDATA2LSB
    
# Report whether the file is big-endian.
    @property
    def is_big_endian(self) -> bool:
        return self.ei_data == ELFData.ELFDATA2MSB


# The file header: entry point plus the locations of both tables.
@dataclass
class ELFHeader:
    e_ident: ELFIdent       # ELF identification
    e_type: int             # file type
    e_machine: int          # target architecture
    e_version: int          # file version
    e_entry: int            # entry point address
    e_phoff: int            # program header table offset
    e_shoff: int            # section header table offset
    e_flags: int            # processor-specific flags
    e_ehsize: int           # ELF header size
    e_phentsize: int        # program header entry size
    e_phnum: int            # program header entry count
    e_shentsize: int        # section header entry size
    e_shnum: int            # section header entry count
    e_shstrndx: int         # index of the section-name string table


# One program header, that is one segment of the load image.
@dataclass
class ProgramHeader:
    p_type: int             # segment type
    p_flags: int            # segment flags (64-bit)
    p_offset: int           # file offset
    p_vaddr: int            # virtual address
    p_paddr: int            # physical address
    p_filesz: int           # size in file
    p_memsz: int            # size in memory
    p_align: int            # alignment
    
# 32-bit puts this field elsewhere in the record
    p_flags_32: int = 0     # 32-bit segment flags
    
# Report whether this segment is mapped into memory.
    @property
    def is_loadable(self) -> bool:
        return self.p_type == ProgramHeaderType.PT_LOAD
    
# Report whether this segment names the dynamic linker.
    @property
    def is_interpreter(self) -> bool:
        return self.p_type == ProgramHeaderType.PT_INTERP
    
# Report whether this segment holds the _DYNAMIC array.
    @property
    def is_dynamic(self) -> bool:
        return self.p_type == ProgramHeaderType.PT_DYNAMIC
    
# Report whether this is the GNU stack-execution segment.
    @property
    def is_stack(self) -> bool:
        return self.p_type == PT_GNU_STACK
    
# Report readable permission, honouring the 32-bit flag field.
    @property
    def is_readable(self) -> bool:
        flags = self.p_flags if self.p_flags else self.p_flags_32
        return bool(flags & ProgramHeaderFlags.PF_R)
    
# Report writable permission, honouring the 32-bit flag field.
    @property
    def is_writable(self) -> bool:
        flags = self.p_flags if self.p_flags else self.p_flags_32
        return bool(flags & ProgramHeaderFlags.PF_W)
    
# Report executable permission, honouring the 32-bit flag field.
    @property
    def is_executable(self) -> bool:
        flags = self.p_flags if self.p_flags else self.p_flags_32
        return bool(flags & ProgramHeaderFlags.PF_X)


# One section header, describing the file through the linker's eyes.
@dataclass
class SectionHeader:
    sh_name: int            # section-name string table offset
    sh_type: int            # section type
    sh_flags: int           # section flags
    sh_addr: int            # virtual address
    sh_offset: int          # file offset
    sh_size: int            # section size
    sh_link: int            # index of the linked section
    sh_info: int            # extra information
    sh_addralign: int       # address alignment
    sh_entsize: int         # entry size
    
# filled in while parsing
    name: str = ""          # section name
    
# Report whether the section occupies memory at run time.
    @property
    def is_allocatable(self) -> bool:
        return bool(self.sh_flags & SectionHeaderFlags.SHF_ALLOC)
    
# Report whether the section is writable.
    @property
    def is_writable(self) -> bool:
        return bool(self.sh_flags & SectionHeaderFlags.SHF_WRITE)
    
# Report whether the section holds instructions.
    @property
    def is_executable(self) -> bool:
        return bool(self.sh_flags & SectionHeaderFlags.SHF_EXECINSTR)
    
# Report whether the section is BSS and takes no file space.
    @property
    def is_nobits(self) -> bool:
        return self.sh_type == SectionHeaderType.SHT_NOBITS


# One symbol table entry.
@dataclass
class ELFSymbol:
    st_name: int            # symbol-name string table offset
    st_info: int            # symbol type and binding
    st_other: int           # visibility
    st_shndx: int           # related section index
    st_value: int           # symbol value or address
    st_size: int            # symbol size
    
# filled in while parsing
    name: str = ""          # symbol name
    
# Return the binding, the high nibble of st_info.
    @property
    def bind(self) -> int:
        return self.st_info >> 4
    
# Return the symbol type, the low nibble of st_info.
    @property
    def type(self) -> int:
        return self.st_info & 0xf
    
# Return the visibility, the low two bits of st_other.
    @property
    def visibility(self) -> int:
        return self.st_other & 0x3
    
# Report whether the symbol is file-local.
    @property
    def is_local(self) -> bool:
        return self.bind == SymbolBinding.STB_LOCAL
    
# Report whether the symbol is globally visible.
    @property
    def is_global(self) -> bool:
        return self.bind == SymbolBinding.STB_GLOBAL
    
# Report whether the symbol is weak.
    @property
    def is_weak(self) -> bool:
        return self.bind == SymbolBinding.STB_WEAK
    
# Report whether the symbol names a function.
    @property
    def is_function(self) -> bool:
        return self.type == SymbolType.STT_FUNC
    
# Report whether the symbol names a data object.
    @property
    def is_object(self) -> bool:
        return self.type == SymbolType.STT_OBJECT
    
# Report whether the symbol is undefined, missing or irrelevant.
    @property
    def is_undefined(self) -> bool:
        return self.st_shndx == SpecialSectionIndex.SHN_UNDEF


# One Rel relocation; the addend lives in the section contents.
@dataclass
class ELFRelocation:
    r_offset: int           # relocation offset or address
    r_info: int             # symbol index and relocation type
    
# Return the symbol index encoded in r_info.
    @property
    def sym(self) -> int:
        return self.r_info >> 32
    
# Return the relocation type encoded in r_info.
    @property
    def type(self) -> int:
        return self.r_info & 0xffffffff


# One Rela relocation, that is a Rel entry carrying an explicit addend.
@dataclass
class ELFRelocationA:
    r_offset: int           # relocation offset or address
    r_info: int             # symbol index and relocation type
    r_addend: int           # addend
    
# Return the symbol index encoded in r_info.
    @property
    def sym(self) -> int:
        return self.r_info >> 32
    
# Return the relocation type encoded in r_info.
    @property
    def type(self) -> int:
        return self.r_info & 0xffffffff


# One entry of the _DYNAMIC array.
@dataclass
class ELFDynamic:
    d_tag: int              # tag type
    d_val: int              # integer value or address
    
# Report whether d_val is an address rather than a plain number.
    @property
    def is_pointer(self) -> bool:
# the GNU and version tags are module level constants in elf_constants, not DynamicTag members;
# every one of them still holds an address that has to take the load bias
        pointer_tags = {
            DynamicTag.DT_PLTGOT, DynamicTag.DT_HASH, DynamicTag.DT_STRTAB,
            DynamicTag.DT_SYMTAB, DynamicTag.DT_RELA, DynamicTag.DT_INIT,
            DynamicTag.DT_FINI, DynamicTag.DT_REL, DynamicTag.DT_DEBUG,
            DynamicTag.DT_JMPREL, DynamicTag.DT_INIT_ARRAY, DynamicTag.DT_FINI_ARRAY,
            DynamicTag.DT_PREINIT_ARRAY, DT_GNU_HASH,
            DT_TLSDESC_PLT, DT_TLSDESC_GOT,
            DT_GNU_CONFLICT, DT_GNU_LIBLIST,
            DT_CONFIG, DT_DEPAUDIT, DT_AUDIT,
            DT_PLTPAD, DT_MOVETAB, DT_SYMINFO,
            DT_VERSYM, DT_VERDEF, DT_VERNEED,
        }
        return self.d_tag in pointer_tags


# Parse an ELF image that is already in memory.
class ELFParser:
    
# Keep the image and a read cursor over it; nothing is parsed yet.
    def __init__(self, data: bytes):
        self.data = data
        self.stream = BytesIO(data)
        
# parse results
        self.header: Optional[ELFHeader] = None
        self.program_headers: List[ProgramHeader] = []
        self.section_headers: List[SectionHeader] = []
        self.symbols: List[ELFSymbol] = []
        self.dynamic_symbols: List[ELFSymbol] = []
        self.dynamics: List[ELFDynamic] = []
        self.relocations: List[Union[ELFRelocation, ELFRelocationA]] = []
        
# outcome of the last parse() call
        self.parse_ok = False
        self.parse_error = ""
        
# string table
        self.shstrtab: bytes = b""
        self.strtab: bytes = b""
        self.dynstr: bytes = b""
        
# section name lookup
        self.section_by_name: Dict[str, SectionHeader] = {}
        
# architecture information
        self.is_32bit = False
        self.is_little_endian = True
        
# struct format strings
        self._fmt_half = "<H"  # 16-bit
        self._fmt_word = "<I"  # 32-bit
        self._fmt_addr = "<I"  # address
        self._fmt_off = "<I"   # offset
        self._fmt_xword = "<Q" # 64-bit
        self._fmt_sword = "<i" # signed 32-bit
    
# Rebuild every struct format string for the file's byte order.
    def _set_endian(self, little_endian: bool):
        prefix = "<" if little_endian else ">"
        self._fmt_half = prefix + "H"
        self._fmt_word = prefix + "I"
        self._fmt_addr = prefix + "I"
        self._fmt_off = prefix + "I"
        self._fmt_xword = prefix + "Q"
        self._fmt_sword = prefix + "i"
    
# Read size bytes from the current cursor.
    def _read(self, size: int) -> bytes:
        return self.stream.read(size)
    
# Move the read cursor to a file offset.
    def _seek(self, offset: int):
        self.stream.seek(offset)
    
# Read an unsigned 16-bit integer.
    def _read_half(self) -> int:
        return struct.unpack(self._fmt_half, self._read(2))[0]
    
# Read an unsigned 32-bit integer.
    def _read_word(self) -> int:
        return struct.unpack(self._fmt_word, self._read(4))[0]
    
# Read a signed 32-bit integer.
    def _read_sword(self) -> int:
        return struct.unpack(self._fmt_sword, self._read(4))[0]
    
# Read a 32-bit address.
    def _read_addr(self) -> int:
        return struct.unpack(self._fmt_addr, self._read(4))[0]
    
# Read a 64-bit address.
    def _read_addr64(self) -> int:
        return struct.unpack(self._fmt_xword, self._read(8))[0]
    
# Read a 32-bit file offset.
    def _read_off(self) -> int:
        return struct.unpack(self._fmt_off, self._read(4))[0]
    
# Read a 64-bit file offset.
    def _read_off64(self) -> int:
        return struct.unpack(self._fmt_xword, self._read(8))[0]
    
# Read an unsigned 64-bit integer.
    def _read_xword(self) -> int:
        return struct.unpack(self._fmt_xword, self._read(8))[0]
    
# Read a signed 64-bit integer.
    def _read_sxword(self) -> int:
        fmt = "<q" if self._fmt_xword.startswith("<") else ">q"
        return struct.unpack(fmt, self._read(8))[0]
    
# Parse the whole image. Returns self on success so the calls can be chained, and None
# when the image is not a usable ELF, with the reason left in parse_error.
    def parse(self) -> Optional['ELFParser']:
        self.parse_ok = False
        self.parse_error = ""
        
        try:
            self._parse_ident()
            self._parse_header()
            self._parse_program_headers()
            self._parse_section_headers()
            self._parse_string_tables()
            self._resolve_section_names()
            self._parse_symbols()
            self._parse_dynamic()
            self._parse_relocations()
        except Exception as e:
            self.parse_error = str(e)
            self.header = None
            return None
        
        self.parse_ok = True
        return self
    
# Parse e_ident, rejecting anything that is not ELF.
    def _parse_ident(self):
        self._seek(0)
        
# magic number
        ei_mag = self._read(SELFMAG)
        if ei_mag != ELFMAG:
            raise ValueError(f"无效的 ELF 魔数: {ei_mag!r}")
        
# file class
        ei_class = self._read(1)[0]
        if ei_class not in (ELFClass.ELFCLASS32, ELFClass.ELFCLASS64):
            raise ValueError(f"不支持的 ELF 类别: {ei_class}")
        
        self.is_32bit = (ei_class == ELFClass.ELFCLASS32)
        
# data encoding
        ei_data = self._read(1)[0]
        if ei_data not in (ELFData.ELFDATA2LSB, ELFData.ELFDATA2MSB):
            raise ValueError(f"不支持的 ELF 数据编码: {ei_data}")
        
        self.is_little_endian = (ei_data == ELFData.ELFDATA2LSB)
        self._set_endian(self.is_little_endian)
        
# version
        ei_version = self._read(1)[0]
        
        # OS/ABI
        ei_osabi = self._read(1)[0]
        
# ABI version
        ei_abiversion = self._read(1)[0]
        
# padding
        ei_pad = self._read(7)
        
        self.ident = ELFIdent(
            ei_mag=ei_mag,
            ei_class=ei_class,
            ei_data=ei_data,
            ei_version=ei_version,
            ei_osabi=ei_osabi,
            ei_abiversion=ei_abiversion,
            ei_pad=ei_pad
        )
    
# Parse the file header that follows e_ident.
    def _parse_header(self):
        e_type = self._read_half()
        e_machine = self._read_half()
        e_version = self._read_word()
        
        if self.is_32bit:
            e_entry = self._read_addr()
            e_phoff = self._read_off()
            e_shoff = self._read_off()
        else:
            e_entry = self._read_addr64()
            e_phoff = self._read_off64()
            e_shoff = self._read_off64()
        
        e_flags = self._read_word()
        e_ehsize = self._read_half()
        e_phentsize = self._read_half()
        e_phnum = self._read_half()
        e_shentsize = self._read_half()
        e_shnum = self._read_half()
        e_shstrndx = self._read_half()
        
        self.header = ELFHeader(
            e_ident=self.ident,
            e_type=e_type,
            e_machine=e_machine,
            e_version=e_version,
            e_entry=e_entry,
            e_phoff=e_phoff,
            e_shoff=e_shoff,
            e_flags=e_flags,
            e_ehsize=e_ehsize,
            e_phentsize=e_phentsize,
            e_phnum=e_phnum,
            e_shentsize=e_shentsize,
            e_shnum=e_shnum,
            e_shstrndx=e_shstrndx
        )
    
# Parse every entry of the program header table.
    def _parse_program_headers(self):
        if self.header.e_phoff == 0 or self.header.e_phnum == 0:
            return
        
        self._seek(self.header.e_phoff)
        
        for _ in range(self.header.e_phnum):
            if self.is_32bit:
                ph = self._parse_program_header_32()
            else:
                ph = self._parse_program_header_64()
            self.program_headers.append(ph)
    
# Parse one 32-bit program header.
    def _parse_program_header_32(self) -> ProgramHeader:
        p_type = self._read_word()
        p_offset = self._read_off()
        p_vaddr = self._read_addr()
        p_paddr = self._read_addr()
        p_filesz = self._read_word()
        p_memsz = self._read_word()
        p_flags_32 = self._read_word()
        p_align = self._read_word()
        
        return ProgramHeader(
            p_type=p_type,
            p_flags=0,
            p_offset=p_offset,
            p_vaddr=p_vaddr,
            p_paddr=p_paddr,
            p_filesz=p_filesz,
            p_memsz=p_memsz,
            p_align=p_align,
            p_flags_32=p_flags_32
        )
    
# Parse one 64-bit program header.
    def _parse_program_header_64(self) -> ProgramHeader:
        p_type = self._read_word()
        p_flags = self._read_word()
        p_offset = self._read_off64()
        p_vaddr = self._read_addr64()
        p_paddr = self._read_addr64()
        p_filesz = self._read_xword()
        p_memsz = self._read_xword()
        p_align = self._read_xword()
        
        return ProgramHeader(
            p_type=p_type,
            p_flags=p_flags,
            p_offset=p_offset,
            p_vaddr=p_vaddr,
            p_paddr=p_paddr,
            p_filesz=p_filesz,
            p_memsz=p_memsz,
            p_align=p_align,
            p_flags_32=0
        )
    
# Parse every entry of the section header table.
    def _parse_section_headers(self):
        if self.header.e_shoff == 0 or self.header.e_shnum == 0:
            return
        
        self._seek(self.header.e_shoff)
        
        for _ in range(self.header.e_shnum):
            if self.is_32bit:
                sh = self._parse_section_header_32()
            else:
                sh = self._parse_section_header_64()
            self.section_headers.append(sh)
    
# Parse one 32-bit section header.
    def _parse_section_header_32(self) -> SectionHeader:
        sh_name = self._read_word()
        sh_type = self._read_word()
        sh_flags = self._read_word()
        sh_addr = self._read_addr()
        sh_offset = self._read_off()
        sh_size = self._read_word()
        sh_link = self._read_word()
        sh_info = self._read_word()
        sh_addralign = self._read_word()
        sh_entsize = self._read_word()
        
        return SectionHeader(
            sh_name=sh_name,
            sh_type=sh_type,
            sh_flags=sh_flags,
            sh_addr=sh_addr,
            sh_offset=sh_offset,
            sh_size=sh_size,
            sh_link=sh_link,
            sh_info=sh_info,
            sh_addralign=sh_addralign,
            sh_entsize=sh_entsize
        )
    
# Parse one 64-bit section header.
    def _parse_section_header_64(self) -> SectionHeader:
        sh_name = self._read_word()
        sh_type = self._read_word()
        sh_flags = self._read_xword()
        sh_addr = self._read_addr64()
        sh_offset = self._read_off64()
        sh_size = self._read_xword()
        sh_link = self._read_word()
        sh_info = self._read_word()
        sh_addralign = self._read_xword()
        sh_entsize = self._read_xword()
        
        return SectionHeader(
            sh_name=sh_name,
            sh_type=sh_type,
            sh_flags=sh_flags,
            sh_addr=sh_addr,
            sh_offset=sh_offset,
            sh_size=sh_size,
            sh_link=sh_link,
            sh_info=sh_info,
            sh_addralign=sh_addralign,
            sh_entsize=sh_entsize
        )
    
# Cache the section name string table.
    def _parse_string_tables(self):
# section name string table
        if self.header.e_shstrndx != SpecialSectionIndex.SHN_UNDEF:
            shstrtab_hdr = self.section_headers[self.header.e_shstrndx]
            self.shstrtab = self.data[shstrtab_hdr.sh_offset:
                                      shstrtab_hdr.sh_offset + shstrtab_hdr.sh_size]
    
# Resolve every section name and index the sections by it.
    def _resolve_section_names(self):
        for sh in self.section_headers:
            sh.name = self._get_string(self.shstrtab, sh.sh_name)
            self.section_by_name[sh.name] = sh
    
# Return the string at offset in a string table, or empty if out of range.
    def _get_string(self, strtab: bytes, offset: int) -> str:
        if offset >= len(strtab):
            return ""
        end = strtab.find(b'\x00', offset)
        if end == -1:
            end = len(strtab)
        return strtab[offset:end].decode('utf-8', errors='replace')
    
# Parse the static symbol table and the dynamic one.
    def _parse_symbols(self):
# look for the symbol table sections
        for sh in self.section_headers:
            if sh.sh_type == SectionHeaderType.SHT_SYMTAB:
                self._parse_symbol_section(sh, False)
            elif sh.sh_type == SectionHeaderType.SHT_DYNSYM:
                self._parse_symbol_section(sh, True)
    
# Parse one symbol table section together with its string table.
    def _parse_symbol_section(self, sh: SectionHeader, is_dynamic: bool):
# fetch the associated string table
        if sh.sh_link < len(self.section_headers):
            strtab_sh = self.section_headers[sh.sh_link]
            strtab = self.data[strtab_sh.sh_offset:
                              strtab_sh.sh_offset + strtab_sh.sh_size]
            if is_dynamic:
                self.dynstr = strtab
            else:
                self.strtab = strtab
        else:
            strtab = b""
        
# read the symbol entries
        offset = sh.sh_offset
        entry_size = 16 if self.is_32bit else 24
        
        for i in range(sh.sh_size // entry_size):
            self._seek(offset + i * entry_size)
            
            if self.is_32bit:
                sym = self._parse_symbol_32(strtab)
            else:
                sym = self._parse_symbol_64(strtab)
            
            if is_dynamic:
                self.dynamic_symbols.append(sym)
            else:
                self.symbols.append(sym)
    
# Parse one 32-bit symbol table entry.
    def _parse_symbol_32(self, strtab: bytes) -> ELFSymbol:
        st_name = self._read_word()
        st_value = self._read_addr()
        st_size = self._read_word()
        st_info = self._read(1)[0]
        st_other = self._read(1)[0]
        st_shndx = self._read_half()
        
        name = self._get_string(strtab, st_name)
        
        return ELFSymbol(
            st_name=st_name,
            st_info=st_info,
            st_other=st_other,
            st_shndx=st_shndx,
            st_value=st_value,
            st_size=st_size,
            name=name
        )
    
# Parse one 64-bit symbol table entry.
    def _parse_symbol_64(self, strtab: bytes) -> ELFSymbol:
        st_name = self._read_word()
        st_info = self._read(1)[0]
        st_other = self._read(1)[0]
        st_shndx = self._read_half()
        st_value = self._read_addr64()
        st_size = self._read_xword()
        
        name = self._get_string(strtab, st_name)
        
        return ELFSymbol(
            st_name=st_name,
            st_info=st_info,
            st_other=st_other,
            st_shndx=st_shndx,
            st_value=st_value,
            st_size=st_size,
            name=name
        )
    
# Parse the _DYNAMIC array from sections, else from the PT_DYNAMIC segment.
    def _parse_dynamic(self):
        for sh in self.section_headers:
            if sh.sh_type == SectionHeaderType.SHT_DYNAMIC:
                self._parse_dynamic_section(sh)
        
# the same array can also come from the PT_DYNAMIC segment
        for ph in self.program_headers:
            if ph.p_type == ProgramHeaderType.PT_DYNAMIC:
# only used when the sections produced nothing
                if not self.dynamics:
                    self._parse_dynamic_segment(ph)
    
# Parse the _DYNAMIC array out of a section.
    def _parse_dynamic_section(self, sh: SectionHeader):
        offset = sh.sh_offset
        entry_size = 8 if self.is_32bit else 16
        
        for i in range(sh.sh_size // entry_size):
            self._seek(offset + i * entry_size)
            
            if self.is_32bit:
                d_tag = self._read_sword()
                d_val = self._read_word()
            else:
                d_tag = self._read_sxword()
                d_val = self._read_xword()
            
            self.dynamics.append(ELFDynamic(d_tag=d_tag, d_val=d_val))
            
            if d_tag == DynamicTag.DT_NULL:
                break
    
# Parse the _DYNAMIC array out of the PT_DYNAMIC segment.
    def _parse_dynamic_segment(self, ph: ProgramHeader):
        offset = ph.p_offset
        entry_size = 8 if self.is_32bit else 16
        num_entries = ph.p_filesz // entry_size
        
        self._seek(offset)
        
        for _ in range(num_entries):
            if self.is_32bit:
                d_tag = self._read_sword()
                d_val = self._read_word()
            else:
                d_tag = self._read_sxword()
                d_val = self._read_xword()
            
            self.dynamics.append(ELFDynamic(d_tag=d_tag, d_val=d_val))
            
            if d_tag == DynamicTag.DT_NULL:
                break
    
# Parse every Rel and Rela section.
    def _parse_relocations(self):
        for sh in self.section_headers:
            if sh.sh_type == SectionHeaderType.SHT_REL:
                self._parse_rel_section(sh)
            elif sh.sh_type == SectionHeaderType.SHT_RELA:
                self._parse_rela_section(sh)
    
# Parse one Rel relocation section.
    def _parse_rel_section(self, sh: SectionHeader):
        offset = sh.sh_offset
        entry_size = 8 if self.is_32bit else 16
        
        for i in range(sh.sh_size // entry_size):
            self._seek(offset + i * entry_size)
            
            if self.is_32bit:
                r_offset = self._read_word()
                r_info = self._read_word()
            else:
                r_offset = self._read_addr64()
                r_info = self._read_xword()
            
            self.relocations.append(ELFRelocation(
                r_offset=r_offset,
                r_info=r_info
            ))
    
# Parse one Rela relocation section.
    def _parse_rela_section(self, sh: SectionHeader):
        offset = sh.sh_offset
        entry_size = 12 if self.is_32bit else 24
        
        for i in range(sh.sh_size // entry_size):
            self._seek(offset + i * entry_size)
            
            if self.is_32bit:
                r_offset = self._read_word()
                r_info = self._read_word()
                r_addend = self._read_sword()
            else:
                r_offset = self._read_addr64()
                r_info = self._read_xword()
                r_addend = self._read_sxword()
            
            self.relocations.append(ELFRelocationA(
                r_offset=r_offset,
                r_info=r_info,
                r_addend=r_addend
            ))
    
# Return a section's bytes, zero filled when it is BSS.
    def get_section_data(self, sh: SectionHeader) -> bytes:
        if sh.is_nobits:
            return b'\x00' * sh.sh_size
        return self.data[sh.sh_offset:sh.sh_offset + sh.sh_size]
    
# Return the PT_INTERP path, that is the dynamic linker, or None.
    def get_interpreter(self) -> Optional[str]:
        for ph in self.program_headers:
            if ph.is_interpreter:
                data = self.data[ph.p_offset:ph.p_offset + ph.p_filesz]
                return data.rstrip(b'\x00').decode('utf-8', errors='replace')
        return None
    
# Return the shared library names listed by DT_NEEDED.
    def get_needed_libraries(self) -> List[str]:
        libraries = []
        for dyn in self.dynamics:
            if dyn.d_tag == DynamicTag.DT_NEEDED:
                lib_name = self._get_string(self.dynstr, dyn.d_val)
                libraries.append(lib_name)
        return libraries
    
# Look a name up in the static symbols first, then the dynamic ones.
    def get_symbol_by_name(self, name: str) -> Optional[ELFSymbol]:
        for sym in self.symbols:
            if sym.name == name:
                return sym
        for sym in self.dynamic_symbols:
            if sym.name == name:
                return sym
        return None
    
# Return the PT_LOAD program headers.
    def get_loadable_segments(self) -> List[ProgramHeader]:
        return [ph for ph in self.program_headers if ph.is_loadable]
    
# Summarise the parsed image for debugging.
    def __repr__(self) -> str:
        return (f"ELFParser(arch={'32' if self.is_32bit else '64'}bit, "
                f"endian={'little' if self.is_little_endian else 'big'}, "
                f"type={self.header.e_type if self.header else 'unknown'}, "
                f"machine={self.header.e_machine if self.header else 'unknown'})")
