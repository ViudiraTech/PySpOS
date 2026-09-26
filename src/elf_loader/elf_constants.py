'''
 *
 *      elf_constants.py
 *      ELF structure constants and enumerations.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from enum import IntEnum, IntFlag

# ==================== ELF magic and identification ====================
ELFMAG = b'\x7fELF'  # ELF magic number
SELFMAG = 4          # magic number length

# file class
class ELFClass(IntEnum):
    ELFCLASSNONE = 0      # invalid class
    ELFCLASS32 = 1        # 32-bit object
    ELFCLASS64 = 2        # 64-bit object

# data encoding
class ELFData(IntEnum):
    ELFDATANONE = 0       # invalid data encoding
    ELFDATA2LSB = 1       # little-endian
    ELFDATA2MSB = 2       # big-endian

# OS/ABI identification
class ELFOSABI(IntEnum):
    ELFOSABI_NONE = 0         # UNIX System V ABI
    ELFOSABI_HPUX = 1         # HP-UX
    ELFOSABI_NETBSD = 2       # NetBSD
    ELFOSABI_GNU = 3          # GNU/Linux, the Linux that carries the GNU brand
    ELFOSABI_LINUX = 3        # Linux (historic alias, should be ELFOSABI_GNU today)
    ELFOSABI_SOLARIS = 6      # Solaris
    ELFOSABI_AIX = 7          # IBM AIX
    ELFOSABI_IRIX = 8         # IRIX
    ELFOSABI_FREEBSD = 9      # FreeBSD
    ELFOSABI_TRU64 = 10       # Compaq TRU64 UNIX
    ELFOSABI_MODESTO = 11     # Novell Modesto
    ELFOSABI_OPENBSD = 12     # OpenBSD
    ELFOSABI_ARM_AEABI = 64   # ARM EABI
    ELFOSABI_ARM = 97         # ARM
    ELFOSABI_STANDALONE = 255 # Standalone (embedded) application

# ==================== file types ====================
class ELFType(IntEnum):
    ET_NONE = 0        # no file type
    ET_REL = 1         # relocatable file
    ET_EXEC = 2        # executable file (the one that actually runs)
    ET_DYN = 3         # shared object file
    ET_CORE = 4        # core file
    ET_LOOS = 0xfe00   # OS-specific range begin
    ET_HIOS = 0xfeff   # OS-specific range end
    ET_LOPROC = 0xff00 # processor-specific range begin
    ET_HIPROC = 0xffff # processor-specific range end

# ==================== machine architectures ====================
class ELFMachine(IntEnum):
    EM_NONE = 0          # no machine
    EM_M32 = 1           # AT&T WE 32100
    EM_SPARC = 2         # SPARC
    EM_386 = 3           # Intel 80386
    EM_68K = 4           # Motorola 68000
    EM_88K = 5           # Motorola 88000
    EM_IAMCU = 6         # Intel MCU
    EM_860 = 7           # Intel 80860
    EM_MIPS = 8          # MIPS I Architecture
    EM_S370 = 9          # IBM System/370 Processor
    EM_MIPS_RS3_LE = 10  # MIPS RS3000 Little-endian
    EM_PARISC = 15       # Hewlett-Packard PA-RISC
    EM_VPP500 = 17       # Fujitsu VPP500
    EM_SPARC32PLUS = 18  # Enhanced instruction set SPARC
    EM_960 = 19          # Intel 80960
    EM_PPC = 20          # PowerPC
    EM_PPC64 = 21        # 64-bit PowerPC
    EM_S390 = 22         # IBM System/390 Processor
    EM_SPU = 23          # IBM SPU/SPC
    EM_V800 = 36         # NEC V800
    EM_FR20 = 37         # Fujitsu FR20
    EM_RH32 = 38         # TRW RH-32
    EM_RCE = 39          # Motorola RCE
    EM_ARM = 40          # ARM 32-bit architecture (AARCH32)
    EM_ALPHA = 41        # Digital Alpha
    EM_SH = 42           # Hitachi SH
    EM_SPARCV9 = 43      # SPARC Version 9
    EM_TRICORE = 44      # Siemens TriCore embedded processor
    EM_ARC = 45          # Argonaut RISC Core, Argonaut Technologies Inc.
    EM_H8_300 = 46       # Hitachi H8/300
    EM_H8_300H = 47      # Hitachi H8/300H
    EM_H8S = 48          # Hitachi H8S
    EM_H8_500 = 49       # Hitachi H8/500
    EM_IA_64 = 50        # Intel IA-64 processor architecture
    EM_MIPS_X = 51       # Stanford MIPS-X
    EM_COLDFIRE = 52     # Motorola ColdFire
    EM_68HC12 = 53       # Motorola M68HC12
    EM_MMA = 54          # Fujitsu MMA Multimedia Accelerator
    EM_PCP = 55          # Siemens PCP
    EM_NCPU = 56         # Sony nCPU embedded RISC processor
    EM_NDR1 = 57         # Denso NDR1 microprocessor
    EM_STARCORE = 58     # Motorola Star*Core processor
    EM_ME16 = 59         # Toyota ME16 processor
    EM_ST100 = 60        # STMicroelectronics ST100 processor
    EM_TINYJ = 61        # Advanced Logic Corp. TinyJ embedded processor family
    EM_X86_64 = 62       # AMD x86-64 architecture
    EM_PDSP = 63         # Sony DSP Processor
    EM_PDP10 = 64        # Digital Equipment Corp. PDP-10
    EM_PDP11 = 65        # Digital Equipment Corp. PDP-11
    EM_FX66 = 66         # Siemens FX66 microcontroller
    EM_ST9PLUS = 67      # STMicroelectronics ST9+ 8/16 bit microcontroller
    EM_ST7 = 68          # STMicroelectronics ST7 8-bit microcontroller
    EM_68HC16 = 69       # Motorola MC68HC16 Microcontroller
    EM_68HC11 = 70       # Motorola MC68HC11 Microcontroller
    EM_68HC08 = 71       # Motorola MC68HC08 Microcontroller
    EM_68HC05 = 72       # Motorola MC68HC05 Microcontroller
    EM_SVX = 73          # Silicon Graphics SVx
    EM_ST19 = 74         # STMicroelectronics ST19 8-bit microcontroller
    EM_VAX = 75          # Digital VAX
    EM_CRIS = 76         # Axis Communications 32-bit embedded processor
    EM_JAVELIN = 77      # Infineon Technologies 32-bit embedded processor
    EM_FIREPATH = 78     # Element 14 64-bit DSP Processor
    EM_ZSP = 79          # LSI Logic 16-bit DSP Processor
    EM_MMIX = 80         # Donald Knuth's educational 64-bit processor
    EM_HUANY = 81        # Harvard University machine-independent object files
    EM_PRISM = 82        # SiTera Prism
    EM_AVR = 83          # Atmel AVR 8-bit microcontroller
    EM_FR30 = 84         # Fujitsu FR30
    EM_D10V = 85         # Mitsubishi D10V
    EM_D30V = 86         # Mitsubishi D30V
    EM_V850 = 87         # NEC v850
    EM_M32R = 88         # Mitsubishi M32R
    EM_MN10300 = 89      # Matsushita MN10300
    EM_MN10200 = 90      # Matsushita MN10200
    EM_PJ = 91           # picoJava
    EM_OPENRISC = 92     # OpenRISC 32-bit embedded processor
    EM_ARC_COMPACT = 93  # ARC International ARCompact processor
    EM_XTENSA = 94       # Tensilica Xtensa Architecture
    EM_VIDEOCORE = 95    # Alphamosaic VideoCore processor
    EM_TMM_GPP = 96      # Thompson Multimedia General Purpose Processor
    EM_NS32K = 97        # National Semiconductor 32000 series
    EM_TPC = 98          # Tenor Network TPC processor
    EM_SNP1K = 99        # Trebia SNP 1000 processor
    EM_ST200 = 100       # STMicroelectronics ST200 microcontroller
    EM_IP2K = 101        # Ubicom IP2xxx microcontroller family
    EM_MAX = 102         # MAX Processor
    EM_CR = 103          # National Semiconductor CompactRISC microprocessor
    EM_F2MC16 = 104      # Fujitsu F2MC16
    EM_MSP430 = 105      # Texas Instruments embedded microcontroller msp430
    EM_BLACKFIN = 106    # Analog Devices Blackfin (DSP) processor
    EM_SE_C33 = 107      # S1C33 Family of Seiko Epson processors
    EM_SEP = 108         # Sharp embedded microprocessor
    EM_ARCA = 109        # Arca RISC Microprocessor
    EM_UNICORE = 110     # Microprocessor series from PKU-Unity Ltd. and MPRC of Peking University
    EM_EXCESS = 111      # eXcess: 16/32/64-bit configurable embedded CPU
    EM_DXP = 112         # Icera Semiconductor Inc. Deep Execution Processor
    EM_ALTERA_NIOS2 = 113 # Altera Nios II soft-core processor
    EM_CRX = 114         # National Semiconductor CompactRISC CRX microprocessor
    EM_XGATE = 115       # Motorola XGATE embedded processor
    EM_C166 = 116        # Infineon C16x/XC16x processor
    EM_M16C = 117        # Renesas M16C series microprocessors
    EM_DSPIC30F = 118    # Microchip Technology dsPIC30F Digital Signal Controller
    EM_CE = 119          # Freescale Communication Engine RISC core
    EM_M32C = 120        # Renesas M32C series microprocessors
    EM_TSK3000 = 131     # Altium TSK3000 core
    EM_RS08 = 132        # Freescale RS08 embedded processor
    EM_SHARC = 133       # Analog Devices SHARC family of 32-bit DSP processors
    EM_ECOG2 = 134       # Cyan Technology eCOG2 microprocessor
    EM_SCORE7 = 135      # Sunplus S+core7 RISC processor
    EM_DSP24 = 136       # New Japan Radio (NJR) 24-bit DSP Processor
    EM_VIDEOCORE3 = 137  # Broadcom VideoCore III processor
    EM_LATTICEMICO32 = 138 # RISC processor for Lattice FPGA architecture
    EM_SE_C17 = 139      # Seiko Epson C17 family
    EM_TI_C6000 = 140    # The Texas Instruments TMS320C6000 DSP family
    EM_TI_C2000 = 141    # The Texas Instruments TMS320C2000 DSP family
    EM_TI_C5500 = 142    # The Texas Instruments TMS320C55x DSP family
    EM_TI_ARP32 = 143    # Texas Instruments Application Specific RISC Processor, 32bit fetch
    EM_TI_PRU = 144      # Texas Instruments Programmable Realtime Unit
    EM_MMDSP_PLUS = 160  # STMicroelectronics 64bit VLIW Data Signal Processor
    EM_CYPRESS_M8C = 161 # Cypress M8C microprocessor
    EM_R32C = 162        # Renesas R32C series microprocessors
    EM_TRIMEDIA = 163    # NXP Semiconductors TriMedia architecture family
    EM_QDSP6 = 164       # QUALCOMM DSP6 Processor
    EM_8051 = 165        # Intel 8051 and variants
    EM_STXP7X = 166      # STMicroelectronics STxP7x family of configurable and extensible RISC processors
    EM_NDS32 = 167       # Andes Technology compact code size embedded RISC processor family
    EM_ECOG1 = 168       # Cyan Technology eCOG1X family
    EM_ECOG1X = 168      # Cyan Technology eCOG1X family
    EM_MAXQ30 = 169      # Dallas Semiconductor MAXQ30 Core Micro-controllers
    EM_XIMO16 = 170      # New Japan Radio (NJR) 16-bit DSP Processor
    EM_MANIK = 171       # M2000 Reconfigurable RISC Microprocessor
    EM_CRAYNV2 = 172     # Cray Inc. NV2 vector architecture
    EM_RX = 173          # Renesas RX family
    EM_METAG = 174       # Imagination Technologies META processor architecture
    EM_MCST_ELBRUS = 175 # MCST Elbrus general purpose hardware architecture
    EM_ECOG16 = 176      # Cyan Technology eCOG16 family
    EM_CR16 = 177        # National Semiconductor CompactRISC CR16 16-bit microprocessor
    EM_ETPU = 178        # Freescale Extended Time Processing Unit
    EM_SLE9X = 179       # Infineon Technologies SLE9X core
    EM_L10M = 180        # Intel L10M
    EM_K10M = 181        # Intel K10M
    EM_AARCH64 = 183     # ARM 64-bit architecture (AARCH64)
    EM_AVR32 = 185       # Atmel Corporation 32-bit microprocessor family
    EM_STM8 = 186        # STMicroeletronics STM8 8-bit microcontroller
    EM_TILE64 = 187      # Tilera TILE64 multicore architecture family
    EM_TILEPRO = 188     # Tilera TILEPro multicore architecture family
    EM_CUDA = 190        # NVIDIA CUDA architecture
    EM_TILEGX = 191      # Tilera TILE-Gx multicore architecture family
    EM_CLOUDSHIELD = 192 # CloudShield architecture family
    EM_COREA_1ST = 193   # KIPO-KAIST Core-A 1st generation processor family
    EM_COREA_2ND = 194   # KIPO-KAIST Core-A 2nd generation processor family
    EM_ARC_COMPACT2 = 195 # Synopsys ARCompact V2
    EM_OPEN8 = 196       # Open8 8-bit RISC soft processor core
    EM_RL78 = 197        # Renesas RL78 family
    EM_VIDEOCORE5 = 198  # Broadcom VideoCore V processor
    EM_78KOR = 199       # Renesas 78KOR family
    EM_56800EX = 200     # Freescale 56800EX Digital Signal Controller (DSC)
    EM_BA1 = 201         # Beyond BA1 CPU architecture
    EM_BA2 = 202         # Beyond BA2 CPU architecture
    EM_XCORE = 203       # XMOS xCORE processor family
    EM_MCHP_PIC = 204    # Microchip 8-bit PIC(r) family
    EM_INTEL205 = 205    # Reserved by Intel
    EM_INTEL206 = 206    # Reserved by Intel
    EM_INTEL207 = 207    # Reserved by Intel
    EM_INTEL208 = 208    # Reserved by Intel
    EM_INTEL209 = 209    # Reserved by Intel
    EM_KM32 = 210        # KM211 KM32 32-bit processor
    EM_KMX32 = 211       # KM211 KMX32 32-bit processor
    EM_KMX16 = 212       # KM211 KMX16 16-bit processor
    EM_KMX8 = 213        # KM211 KMX8 8-bit processor
    EM_KVARC = 214       # KM211 KVARC processor
    EM_CDP = 215         # Paneve CDP architecture family
    EM_COGE = 216        # Cognitive Smart Memory Processor
    EM_COOL = 217        # Bluechip Systems CoolEngine
    EM_NORC = 218        # Nanoradio Optimized RISC
    EM_CSR_KALIMBA = 219 # CSR Kalimba architecture family
    EM_Z80 = 220         # Zilog Z80
    EM_VISIUM = 221      # Controls and Data Services VISIUMcore processor
    EM_FT32 = 222        # FTDI Chip FT32 high performance 32-bit RISC architecture
    EM_MOXIE = 223       # Moxie processor family
    EM_AMDGPU = 224      # AMD GPU architecture
    EM_RISCV = 243       # RISC-V

# ==================== segment types (p_type) ====================
class ProgramHeaderType(IntEnum):
    PT_NULL = 0          # unused entry
    PT_LOAD = 1          # loadable segment
    PT_DYNAMIC = 2       # dynamic linking information
    PT_INTERP = 3        # interpreter path
    PT_NOTE = 4          # auxiliary information
    PT_SHLIB = 5         # reserved
    PT_PHDR = 6          # program header table offset
    PT_TLS = 7           # thread-local storage segment
    PT_LOOS = 0x60000000 # OS-specific range begin
    PT_HIOS = 0x6fffffff # OS-specific range end
    PT_LOPROC = 0x70000000 # processor-specific range begin
    PT_HIPROC = 0x7fffffff # processor-specific range end

# GNU stack segment types
PT_GNU_STACK = 0x6474e551
PT_GNU_RELRO = 0x6474e552
PT_GNU_PROPERTY = 0x6474e553

# ==================== segment flags (p_flags) ====================
class ProgramHeaderFlags(IntFlag):
    PF_X = 1             # executable
    PF_W = 2             # writable
    PF_R = 4             # readable
    PF_MASKOS = 0x0ff00000  # OS-specific mask
    PF_MASKPROC = 0xf0000000 # processor-specific mask

# ==================== section types (sh_type) ====================
class SectionHeaderType(IntEnum):
    SHT_NULL = 0              # unused section
    SHT_PROGBITS = 1          # program data
    SHT_SYMTAB = 2            # symbol table
    SHT_STRTAB = 3            # string table
    SHT_RELA = 4              # relocation table with addends
    SHT_HASH = 5              # symbol hash table
    SHT_DYNAMIC = 6           # dynamic linking information
    SHT_NOTE = 7              # comment information
    SHT_NOBITS = 8            # space-occuping-free section (BSS)
    SHT_REL = 9               # relocation table
    SHT_SHLIB = 10            # reserved
    SHT_DYNSYM = 11           # dynamic symbol table
    SHT_INIT_ARRAY = 14       # array of init function pointers
    SHT_FINI_ARRAY = 15       # array of fini function pointers
    SHT_PREINIT_ARRAY = 16    # array of preinit function pointers
    SHT_GROUP = 17            # section group
    SHT_SYMTAB_SHNDX = 18     # extended section index
    SHT_LOOS = 0x60000000     # OS-specific range begin
    SHT_HIOS = 0x6fffffff     # OS-specific range end
    SHT_LOPROC = 0x70000000   # processor-specific range begin
    SHT_HIPROC = 0x7fffffff   # processor-specific range end
    SHT_LOUSER = 0x80000000   # application-specific range begin
    SHT_HIUSER = 0xffffffff   # application-specific range end

# GNU attribute sections
SHT_GNU_ATTRIBUTES = 0x6ffffff5
SHT_GNU_HASH = 0x6ffffff6
SHT_GNU_LIBLIST = 0x6ffffff7
SHT_CHECKSUM = 0x6ffffff8
SHT_GNU_VERDEF = 0x6ffffffd
SHT_GNU_VERNEED = 0x6ffffffe
SHT_GNU_VERSYM = 0x6fffffff

# ==================== section flags (sh_flags) ====================
class SectionHeaderFlags(IntFlag):
    SHF_WRITE = 0x1           # writable
    SHF_ALLOC = 0x2           # occupies memory
    SHF_EXECINSTR = 0x4       # executable instructions
    SHF_MERGE = 0x10          # mergeable
    SHF_STRINGS = 0x20        # holds null-terminated strings
    SHF_INFO_LINK = 0x40      # sh_info holds a section index
    SHF_LINK_ORDER = 0x80     # preserve link order
    SHF_OS_NONCONFORMING = 0x100  # non-standard OS-specific handling
    SHF_GROUP = 0x200         # section belongs to a group
    SHF_TLS = 0x400           # thread-local storage
    SHF_COMPRESSED = 0x800    # compressed section
    SHF_MASKOS = 0x0ff00000   # OS-specific mask
    SHF_MASKPROC = 0xf0000000 # processor-specific mask

# ==================== dynamic tags (d_tag) ====================
class DynamicTag(IntEnum):
    DT_NULL = 0              # marks the end of the _DYNAMIC array
    DT_NEEDED = 1            # string table offset of the needed library names
    DT_PLTRELSZ = 2          # size of the PLT relocation table
    DT_PLTGOT = 3            # PLT/GOT address
    DT_HASH = 4              # symbol hash table address
    DT_STRTAB = 5            # string table address
    DT_SYMTAB = 6            # symbol table address
    DT_RELA = 7              # Rela relocation table address
    DT_RELASZ = 8            # size of the Rela relocation table
    DT_RELAENT = 9           # size of one Rela relocation entry
    DT_STRSZ = 10            # size of the string table
    DT_SYMENT = 11           # size of one symbol table entry
    DT_INIT = 12             # init function address
    DT_FINI = 13             # fini function address
    DT_SONAME = 14           # string table offset of the shared object name
    DT_RPATH = 15            # string table offset of the library search path
    DT_SYMBOLIC = 16         # symbolic linking flag
    DT_REL = 17              # Rel relocation table address
    DT_RELSZ = 18            # size of the Rel relocation table
    DT_RELENT = 19           # size of one Rel relocation entry
    DT_PLTREL = 20           # PLT relocation type
    DT_DEBUG = 21            # debug information
    DT_TEXTREL = 22          # text relocation flag
    DT_JMPREL = 23           # PLT relocation table address
    DT_BIND_NOW = 24         # bind-now flag
    DT_INIT_ARRAY = 25       # address of the init function pointer array
    DT_FINI_ARRAY = 26       # address of the fini function pointer array
    DT_INIT_ARRAYSZ = 27     # size of the init function pointer array
    DT_FINI_ARRAYSZ = 28     # size of the fini function pointer array
    DT_RUNPATH = 29          # runtime library search path
    DT_FLAGS = 30            # flags
    DT_ENCODING = 32         # encoded value begin
    DT_PREINIT_ARRAY = 32    # address of the preinit function pointer array
    DT_PREINIT_ARRAYSZ = 33  # size of the preinit function pointer array
    DT_SYMTAB_SHNDX = 34     # section index of the symbol table
    DT_LOOS = 0x6000000d     # OS-specific range begin
    DT_HIOS = 0x6ffff000     # OS-specific range end
    DT_LOPROC = 0x70000000   # processor-specific range begin
    DT_HIPROC = 0x7fffffff   # processor-specific range end

# the DT_FLAGS constant, lifted out of DynamicTag
DT_FLAGS = 30

# GNU-specific dynamic tags
DT_GNU_HASH = 0x6ffffef5
DT_TLSDESC_PLT = 0x6ffffef6
DT_TLSDESC_GOT = 0x6ffffef7
DT_GNU_CONFLICT = 0x6ffffef8
DT_GNU_LIBLIST = 0x6ffffef9
DT_CONFIG = 0x6ffffefa
DT_DEPAUDIT = 0x6ffffefb
DT_AUDIT = 0x6ffffefc
DT_PLTPAD = 0x6ffffefd
DT_MOVETAB = 0x6ffffefe
DT_SYMINFO = 0x6ffffeff
DT_VERSYM = 0x6ffffff0
DT_RELACOUNT = 0x6ffffff9
DT_RELCOUNT = 0x6ffffffa
DT_FLAGS_1 = 0x6ffffffb
DT_VERDEF = 0x6ffffffc
DT_VERDEFNUM = 0x6ffffffd
DT_VERNEED = 0x6ffffffe
DT_VERNEEDNUM = 0x6fffffff

# ==================== symbol bindings (high 4 bits of st_info) ====================
class SymbolBinding(IntEnum):
    STB_LOCAL = 0     # local symbol
    STB_GLOBAL = 1    # global symbol
    STB_WEAK = 2      # weak symbol
    STB_LOOS = 10     # OS-specific range begin
    STB_HIOS = 12     # OS-specific range end
    STB_LOPROC = 13   # processor-specific range begin
    STB_HIPROC = 15   # processor-specific range end

# ==================== symbol types (low 4 bits of st_info) ====================
class SymbolType(IntEnum):
    STT_NOTYPE = 0    # unspecified type
    STT_OBJECT = 1    # data object
    STT_FUNC = 2      # function
    STT_SECTION = 3   # section
    STT_FILE = 4      # file name
    STT_COMMON = 5    # common data
    STT_TLS = 6       # thread-local storage
    STT_LOOS = 10     # OS-specific range begin
    STT_HIOS = 12     # OS-specific range end
    STT_LOPROC = 13   # processor-specific range begin
    STT_HIPROC = 15   # processor-specific range end

# ==================== relocation types (x86_64) ====================
class RelocationTypeX86_64(IntEnum):
    R_X86_64_NONE = 0           # no relocation
    R_X86_64_64 = 1             # direct 64-bit
    R_X86_64_PC32 = 2           # PC-relative 32-bit signed
    R_X86_64_GOT32 = 3          # 32-bit GOT entry
    R_X86_64_PLT32 = 4          # 32-bit PLT address
    R_X86_64_COPY = 5           # copy relocation
    R_X86_64_GLOB_DAT = 6       # create GOT entry
    R_X86_64_JUMP_SLOT = 7      # create PLT entry
    R_X86_64_RELATIVE = 8       # base-relative address
    R_X86_64_GOTPCREL = 9       # 32-bit signed PC-relative offset to the GOT
    R_X86_64_32 = 10            # direct 32-bit zero-extended
    R_X86_64_32S = 11           # direct 32-bit sign-extended
    R_X86_64_16 = 12            # direct 16-bit zero-extended
    R_X86_64_PC16 = 13          # 16-bit signed PC-relative
    R_X86_64_8 = 14             # direct 8-bit zero-extended
    R_X86_64_PC8 = 15           # 8-bit signed PC-relative
    R_X86_64_DTPMOD64 = 16      # ID of module containing symbol
    R_X86_64_DTPOFF64 = 17      # Offset in module's TLS block
    R_X86_64_TPOFF64 = 18       # Offset in initial TLS block
    R_X86_64_TLSGD = 19         # 32-bit signed PC-relative offset to two GOT entries
    R_X86_64_TLSLD = 20         # 32-bit signed PC-relative offset to two GOT entries
    R_X86_64_DTPOFF32 = 21      # Offset in TLS block
    R_X86_64_GOTTPOFF = 22      # 32-bit signed PC-relative offset to a GOT entry
    R_X86_64_TPOFF32 = 23       # Offset in initial TLS block
    R_X86_64_PC64 = 24          # PC-relative 64-bit
    R_X86_64_GOTOFF64 = 25      # 64-bit GOT-relative offset
    R_X86_64_GOTPC32 = 26       # 32-bit signed PC-relative offset to the GOT
    R_X86_64_GOT64 = 27         # 64-bit GOT entry offset
    R_X86_64_GOTPCREL64 = 28    # 64-bit PC-relative offset to a GOT entry
    R_X86_64_GOTPC64 = 29       # 64-bit PC-relative offset to the GOT
    R_X86_64_GOTPLT64 = 30      # 64-bit GOT entry for the PLT
    R_X86_64_PLTOFF64 = 31      # 64-bit GOT-relative offset to a PLT entry
    R_X86_64_SIZE32 = 32        # 32-bit symbol size
    R_X86_64_SIZE64 = 33        # 64-bit symbol size
    R_X86_64_GOTPC32_TLSDESC = 34 # 32-bit signed PC-relative offset to a TLS descriptor
    R_X86_64_TLSDESC_CALL = 35  # TLS descriptor relocation marker
    R_X86_64_TLSDESC = 36       # two 64-bit TLS descriptor words
    R_X86_64_IRELATIVE = 37     # adjust indirect program address

# ==================== relocation types (i386) ====================
class RelocationTypeI386(IntEnum):
    R_386_NONE = 0          # no relocation
    R_386_32 = 1            # direct 32-bit
    R_386_PC32 = 2          # PC-relative 32-bit
    R_386_GOT32 = 3         # 32-bit GOT entry
    R_386_PLT32 = 4         # 32-bit PLT address
    R_386_COPY = 5          # copy relocation
    R_386_GLOB_DAT = 6      # create GOT entry
    R_386_JMP_SLOT = 7      # create PLT entry
    R_386_RELATIVE = 8      # base-relative address
    R_386_GOTOFF = 9        # 32-bit GOT-relative offset
    R_386_GOTPC = 10        # 32-bit PC-relative offset to the GOT
    R_386_32PLT = 11        # 32-bit PLT offset
    R_386_TLS_TPOFF = 14    # thread-local storage offset
    R_386_TLS_IE = 15       # TLS initial-executable address
    R_386_TLS_GOTIE = 16    # TLS GOT entry
    R_386_TLS_LE = 17       # TLS local-executable address
    R_386_TLS_GD = 18       # TLS global-dynamic address
    R_386_TLS_LDM = 19      # TLS local-dynamic address
    R_386_16 = 20           # direct 16-bit
    R_386_PC16 = 21         # PC-relative 16-bit
    R_386_8 = 22            # direct 8-bit
    R_386_PC8 = 23          # PC-relative 8-bit
    R_386_TLS_GD_32 = 24    # 32-bit TLS GD offset
    R_386_TLS_GD_PUSH = 25  # TLS GD push instruction
    R_386_TLS_GD_CALL = 26  # TLS GD call instruction
    R_386_TLS_GD_POP = 27   # TLS GD pop instruction
    R_386_TLS_LDM_32 = 28   # 32-bit TLS LDM offset
    R_386_TLS_LDM_PUSH = 29 # TLS LDM push instruction
    R_386_TLS_LDM_CALL = 30 # TLS LDM call instruction
    R_386_TLS_LDM_POP = 31  # TLS LDM pop instruction
    R_386_TLS_LDO_32 = 32   # 32-bit TLS LDO offset
    R_386_TLS_IE_32 = 33    # 32-bit TLS IE offset
    R_386_TLS_LE_32 = 34    # 32-bit TLS LE offset
    R_386_TLS_DTPMOD32 = 35 # 32-bit TLS DTPMOD offset
    R_386_TLS_DTPOFF32 = 36 # 32-bit TLS DTPOFF offset
    R_386_TLS_TPOFF32 = 37  # 32-bit TLS TPOFF offset
    R_386_SIZE32 = 38       # 32-bit symbol size
    R_386_TLS_GOTDESC = 39  # TLS GOT descriptor
    R_386_TLS_DESC_CALL = 40 # TLS descriptor call
    R_386_TLS_DESC = 41     # TLS descriptor
    R_386_IRELATIVE = 42    # adjust indirect program address
    R_386_GOT32X = 43       # 32-bit GOT entry

# ==================== special section indices ====================
class SpecialSectionIndex(IntEnum):
    SHN_UNDEF = 0           # undefined, missing or irrelevant reference
    SHN_LORESERVE = 0xff00  # reserved index range begin
    SHN_LOPROC = 0xff00     # processor-specific range begin
    SHN_HIPROC = 0xff1f     # processor-specific range end
    SHN_LIVEPATCH = 0xff20  # live-patch section
    SHN_ABS = 0xfff1        # absolute value
    SHN_COMMON = 0xfff2     # common symbol
    SHN_HIRESERVE = 0xffff  # reserved index range end
