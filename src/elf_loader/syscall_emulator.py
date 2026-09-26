'''
 *
 *      syscall_emulator.py
 *      Linux syscall emulation for loaded ELF programs.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys
import time
import errno
import struct
import random
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


# Linux syscall numbers (x86_64)
# The x86_64 Linux syscall numbers, as far as this emulator implements them.
class SyscallX86_64(IntEnum):
    READ = 0
    WRITE = 1
    OPEN = 2
    CLOSE = 3
    STAT = 4
    FSTAT = 5
    LSTAT = 6
    POLL = 7
    LSEEK = 8
    MMAP = 9
    MPROTECT = 10
    MUNMAP = 11
    BRK = 12
    RT_SIGACTION = 13
    RT_SIGPROCMASK = 14
    IOCTL = 16
    PREAD64 = 17
    PWRITE64 = 18
    READV = 19
    WRITEV = 20
    ACCESS = 21
    PIPE = 22
    SELECT = 23
    SCHED_YIELD = 24
    MREMAP = 25
    MSYNC = 26
    MINCORE = 27
    MADVISE = 28
    SHMGET = 29
    SHMAT = 30
    SHMCTL = 31
    DUP = 32
    DUP2 = 33
    PAUSE = 34
    NANOSLEEP = 35
    GETITIMER = 36
    ALARM = 37
    SETITIMER = 38
    GETPID = 39
    SENDFILE = 40
    SOCKET = 41
    CONNECT = 42
    ACCEPT = 43
    SENDTO = 44
    RECVFROM = 45
    SENDMSG = 46
    RECVMSG = 47
    SHUTDOWN = 48
    BIND = 49
    LISTEN = 50
    GETSOCKNAME = 51
    GETPEERNAME = 52
    SOCKETPAIR = 53
    SETSOCKOPT = 54
    GETSOCKOPT = 55
    CLONE = 56
    FORK = 57
    VFORK = 58
    EXECVE = 59
    EXIT = 60
    WAIT4 = 61
    KILL = 62
    UNAME = 63
    SEMGET = 64
    SEMOP = 65
    SEMCTL = 66
    SHMDT = 67
    MSGGET = 68
    MSGSND = 69
    MSGRCV = 70
    MSGCTL = 71
    FCNTL = 72
    FLOCK = 73
    FSYNC = 74
    FDATASYNC = 75
    TRUNCATE = 76
    FTRUNCATE = 77
    GETDENTS = 78
    GETCWD = 79
    CHDIR = 80
    FCHDIR = 81
    RENAME = 82
    MKDIR = 83
    RMDIR = 84
    CREAT = 85
    LINK = 86
    UNLINK = 87
    SYMLINK = 88
    READLINK = 89
    CHMOD = 90
    FCHMOD = 91
    CHOWN = 92
    FCHOWN = 93
    LCHOWN = 94
    UMASK = 95
    GETTIMEOFDAY = 96
    GETRLIMIT = 97
    GETRUSAGE = 98
    SYSINFO = 99
    TIMES = 100
    PTRACE = 101
    GETUID = 102
    SYSLOG = 103
    GETGID = 104
    SETUID = 105
    SETGID = 106
    GETEUID = 107
    GETEGID = 108
    SETPGID = 109
    GETPPID = 110
    GETPGRP = 111
    SETSID = 112
    SETREUID = 113
    SETREGID = 114
    GETGROUPS = 115
    SETGROUPS = 116
    SETRESUID = 117
    GETRESUID = 118
    SETRESGID = 119
    GETRESGID = 120
    GETPGID = 121
    SETFSUID = 122
    SETFSGID = 123
    GETSID = 124
    CAPGET = 125
    CAPSET = 126
    RT_SIGPENDING = 127
    RT_SIGTIMEDWAIT = 128
    RT_SIGQUEUEINFO = 129
    RT_SIGSUSPEND = 130
    SIGALTSTACK = 131
    UTIME = 132
    MKNOD = 133
    USELIB = 134
    PERSONALITY = 135
    USTAT = 136
    STATFS = 137
    FSTATFS = 138
    SYSFS = 139
    GETPRIORITY = 140
    SETPRIORITY = 141
    SCHED_SETPARAM = 142
    SCHED_GETPARAM = 143
    SCHED_SETSCHEDULER = 144
    SCHED_GETSCHEDULER = 145
    SCHED_GET_PRIORITY_MAX = 146
    SCHED_GET_PRIORITY_MIN = 147
    SCHED_RR_GET_INTERVAL = 148
    MLOCK = 149
    MUNLOCK = 150
    MLOCKALL = 151
    MUNLOCKALL = 152
    VHANGUP = 153
    MODIFY_LDT = 154
    PIVOT_ROOT = 155
    _sysctl = 156
    PRCTL = 157
    ARCH_PRCTL = 158
    ADJTIMEX = 159
    SETRLIMIT = 160
    CHROOT = 161
    SYNC = 162
    ACCT = 163
    SETTIMEOFDAY = 164
    MOUNT = 165
    UMOUNT2 = 166
    SWAPON = 167
    SWAPOFF = 168
    REBOOT = 169
    SETHOSTNAME = 170
    SETDOMAINNAME = 171
    IOPL = 172
    IOPERM = 173
    CREATE_MODULE = 174
    INIT_MODULE = 175
    DELETE_MODULE = 176
    GET_KERNEL_SYMS = 177
    QUERY_MODULE = 178
    QUOTACTL = 179
    NFSSERVCTL = 180
    GETPMSG = 181
    PUTPMSG = 182
    AFS_SYSCALL = 183
    TUXCALL = 184
    SECURITY = 185
    GETTID = 186
    READAHEAD = 187
    SETXATTR = 188
    LSETXATTR = 189
    FSETXATTR = 190
    GETXATTR = 191
    LGETXATTR = 192
    FGETXATTR = 193
    LISTXATTR = 194
    LLISTXATTR = 195
    FLISTXATTR = 196
    REMOVEXATTR = 197
    LREMOVEXATTR = 198
    FREMOVEXATTR = 199
    TKILL = 200
    TIME = 201
    FUTEX = 202
    SCHED_SETAFFINITY = 203
    SCHED_GETAFFINITY = 204
    SET_THREAD_AREA = 205
    IO_SETUP = 206
    IO_DESTROY = 207
    IO_GETEVENTS = 208
    IO_SUBMIT = 209
    IO_CANCEL = 210
    GET_THREAD_AREA = 211
    LOOKUP_DCOOKIE = 212
    EPOLL_CREATE = 213
    EPOLL_CTL_OLD = 214
    EPOLL_WAIT_OLD = 215
    REMAP_FILE_PAGES = 216
    GETDENTS64 = 217
    SET_TID_ADDRESS = 218
    RESTART_SYSCALL = 219
    SEMTIMEDOP = 220
    FADVISE64 = 221
    TIMER_CREATE = 222
    TIMER_SETTIME = 223
    TIMER_GETTIME = 224
    TIMER_GETOVERRUN = 225
    TIMER_DELETE = 226
    CLOCK_SETTIME = 227
    CLOCK_GETTIME = 228
    CLOCK_GETRES = 229
    CLOCK_NANOSLEEP = 230
    EXIT_GROUP = 231
    EPOLL_WAIT = 232
    EPOLL_CTL = 233
    TGKILL = 234
    UTIMES = 235
    VSERVER = 236
    MBIND = 237
    SET_MEMPOLICY = 238
    GET_MEMPOLICY = 239
    MQ_OPEN = 240
    MQ_UNLINK = 241
    MQ_TIMEDSEND = 242
    MQ_TIMEDRECEIVE = 243
    MQ_NOTIFY = 244
    MQ_GETSETATTR = 245
    KEXEC_LOAD = 246
    WAITID = 247
    ADD_KEY = 248
    REQUEST_KEY = 249
    KEYCTL = 250
    IOPRIO_SET = 251
    IOPRIO_GET = 252
    INOTIFY_INIT = 253
    INOTIFY_ADD_WATCH = 254
    INOTIFY_RM_WATCH = 255
    MIGRATE_PAGES = 256
    OPENAT = 257
    MKDIRAT = 258
    MKNODAT = 259
    FCHOWNAT = 260
    FUTIMESAT = 261
    NEWFSTATAT = 262
    UNLINKAT = 263
    RENAMEAT = 264
    LINKAT = 265
    SYMLINKAT = 266
    READLINKAT = 267
    FCHMODAT = 268
    FACCESSAT = 269
    PSELECT6 = 270
    PPOLL = 271
    UNSHARE = 272
    SET_ROBUST_LIST = 273
    GET_ROBUST_LIST = 274
    SPLICE = 275
    TEE = 276
    SYNC_FILE_RANGE = 277
    VMSPLICE = 278
    MOVE_PAGES = 279
    UTIMENSAT = 280
    EPOLL_PWAIT = 281
    SIGNALFD = 282
    TIMERFD_CREATE = 283
    EVENTFD = 284
    FALLOCATE = 285
    TIMERFD_SETTIME = 286
    TIMERFD_GETTIME = 287
    ACCEPT4 = 288
    SIGNALFD4 = 289
    EVENTFD2 = 290
    EPOLL_CREATE1 = 291
    DUP3 = 292
    PIPE2 = 293
    INOTIFY_INIT1 = 294
    PREADV = 295
    PWRITEV = 296
    RT_TGSIGQUEUEINFO = 297
    PERF_EVENT_OPEN = 298
    RECVMMSG = 299
    FANOTIFY_INIT = 300
    FANOTIFY_MARK = 301
    PRLIMIT64 = 302
    NAME_TO_HANDLE_AT = 303
    OPEN_BY_HANDLE_AT = 304
    CLOCK_ADJTIME = 305
    SYNCFS = 306
    SENDMMSG = 307
    SETNS = 308
    GETCPU = 309
    PROCESS_VM_READV = 310
    PROCESS_VM_WRITEV = 311
    KCMP = 312
    FINIT_MODULE = 313
    SCHED_SETATTR = 314
    SCHED_GETATTR = 315
    RENAMEAT2 = 316
    SECCOMP = 317
    GETRANDOM = 318
    MEMFD_CREATE = 319
    KEXEC_FILE_LOAD = 320
    BPF = 321
    EXECVEAT = 322
    USERFAULTFD = 323
    MEMBARRIER = 324
    MLOCK2 = 325
    COPY_FILE_RANGE = 326
    PREADV2 = 327
    PWRITEV2 = 328
    _pkey_mprotect = 329
    _pkey_alloc = 330
    _pkey_free = 331
    statx = 332
    io_pgetevents = 333
    rseq = 334


# Linux syscall numbers (i386)
# The i386 Linux syscall numbers, as far as this emulator implements them.
class SyscallI386(IntEnum):
    RESTART_SYSCALL = 0
    EXIT = 1
    FORK = 2
    READ = 3
    WRITE = 4
    OPEN = 5
    CLOSE = 6
    WAITPID = 7
    CREAT = 8
    LINK = 9
    UNLINK = 10
    EXECVE = 11
    CHDIR = 12
    TIME = 13
    MKNOD = 14
    CHMOD = 15
    LCHOWN = 16
    BREAK = 17
    OLDSTAT = 18
    LSEEK = 19
    GETPID = 20
    MOUNT = 21
    UMOUNT = 22
    SETUID = 23
    GETUID = 24
    STIME = 25
    PTRACE = 26
    ALARM = 27
    OLDFSTAT = 28
    PAUSE = 29
    UTIME = 30
    STTY = 31
    GTTY = 32
    ACCESS = 33
    NICE = 34
    FTIME = 35
    SYNC = 36
    KILL = 37
    RENAME = 38
    MKDIR = 39
    RMDIR = 40
    DUP = 41
    PIPE = 42
    TIMES = 43
    PROF = 44
    BRK = 45
    SETGID = 46
    GETGID = 47
    SIGNAL = 48
    GETEUID = 49
    GETEGID = 50
    ACCT = 51
    UMOUNT2 = 52
    LOCK = 53
    IOCTL = 54
    FCNTL = 55
    MPX = 56
    SETPGID = 57
    ULIMIT = 58
    OLDOLDUNAME = 59
    UMASK = 60
    CHROOT = 61
    USTAT = 62
    DUP2 = 63
    GETPPID = 64
    GETPGRP = 65
    SETSID = 66
    SIGACTION = 67
    SGETMASK = 68
    SSETMASK = 69
    SETREUID = 70
    SETREGID = 71
    SIGSUSPEND = 72
    SIGPENDING = 73
    SETHOSTNAME = 74
    SETRLIMIT = 75
    GETRLIMIT = 76
    GETRUSAGE = 77
    GETTIMEOFDAY = 78
    SETTIMEOFDAY = 79
    GETGROUPS = 80
    SETGROUPS = 81
    SELECT = 82
    SYMLINK = 83
    OLDLSTAT = 84
    READLINK = 85
    USELIB = 86
    SWAPON = 87
    REBOOT = 88
    READDIR = 89
    MMAP = 90
    MUNMAP = 91
    TRUNCATE = 92
    FTRUNCATE = 93
    FCHMOD = 94
    FCHOWN = 95
    GETPRIORITY = 96
    SETPRIORITY = 97
    PROFIL = 98
    STATFS = 99
    FSTATFS = 100
    IOPERM = 101
    SOCKETCALL = 102
    SYSLOG = 103
    SETITIMER = 104
    GETITIMER = 105
    STAT = 106
    LSTAT = 107
    FSTAT = 108
    OLDUNAME = 109
    IOPL = 110
    VHANGUP = 111
    IDLE = 112
    VM86OLD = 113
    WAIT4 = 114
    SWAPOFF = 115
    SYSINFO = 116
    IPC = 117
    FSYNC = 118
    SIGRETURN = 119
    CLONE = 120
    SETDOMAINNAME = 121
    UNAME = 122
    MODIFY_LDT = 123
    ADJTIMEX = 124
    MPROTECT = 125
    SIGPROCMASK = 126
    CREATE_MODULE = 127
    INIT_MODULE = 128
    DELETE_MODULE = 129
    GET_KERNEL_SYMS = 130
    QUOTACTL = 131
    GETPGID = 132
    FCHDIR = 133
    BDFLUSH = 134
    SYSFS = 135
    PERSONALITY = 136
    AFS_SYSCALL = 137
    SETFSUID = 138
    SETFSGID = 139
    _LLSEEK = 140
    GETDENTS = 141
    _NEWSELECT = 142
    FLOCK = 143
    MSYNC = 144
    READV = 145
    WRITEV = 146
    GETSID = 147
    FDATASYNC = 148
    _SYSCTL = 149
    MLOCK = 150
    MUNLOCK = 151
    MLOCKALL = 152
    MUNLOCKALL = 153
    SCHED_SETPARAM = 154
    SCHED_GETPARAM = 155
    SCHED_SETSCHEDULER = 156
    SCHED_GETSCHEDULER = 157
    SCHED_YIELD = 158
    SCHED_GET_PRIORITY_MAX = 159
    SCHED_GET_PRIORITY_MIN = 160
    SCHED_RR_GET_INTERVAL = 161
    NANOSLEEP = 162
    MREMAP = 163
    SETRESUID = 164
    GETRESUID = 165
    VM86 = 166
    QUERY_MODULE = 167
    POLL = 168
    NFSSERVCTL = 169
    SETRESGID = 170
    GETRESGID = 171
    PRCTL = 172
    RT_SIGRETURN = 173
    RT_SIGACTION = 174
    RT_SIGPROCMASK = 175
    RT_SIGPENDING = 176
    RT_SIGTIMEDWAIT = 177
    RT_SIGQUEUEINFO = 178
    RT_SIGSUSPEND = 179
    PREAD64 = 180
    PWRITE64 = 181
    CHOWN = 182
    GETCWD = 183
    CAPGET = 184
    CAPSET = 185
    SIGALTSTACK = 186
    SENDFILE = 187
    GETPMSG = 188
    PUTPMSG = 189
    VFORK = 190
    UGETRLIMIT = 191
    MMAP2 = 192
    TRUNCATE64 = 193
    FTRUNCATE64 = 194
    STAT64 = 195
    LSTAT64 = 196
    FSTAT64 = 197
    LCHOWN32 = 198
    GETUID32 = 199
    GETGID32 = 200
    GETEUID32 = 201
    GETEGID32 = 202
    SETREUID32 = 203
    SETREGID32 = 204
    GETGROUPS32 = 205
    SETGROUPS32 = 206
    FCHOWN32 = 207
    SETRESUID32 = 208
    GETRESUID32 = 209
    SETRESGID32 = 210
    GETRESGID32 = 211
    CHOWN32 = 212
    SETUID32 = 213
    SETGID32 = 214
    SETFSUID32 = 215
    SETFSGID32 = 216
    PIVOT_ROOT = 217
    MINCORE = 218
    MADVISE = 219
    GETDENTS64 = 220
    FCNTL64 = 221
    TUXCALL = 222
    SECURITY = 223
    GETTID = 224
    READAHEAD = 225
    SETXATTR = 226
    LSETXATTR = 227
    FSETXATTR = 228
    GETXATTR = 229
    LGETXATTR = 230
    FGETXATTR = 231
    LISTXATTR = 232
    LLISTXATTR = 233
    FLISTXATTR = 234
    REMOVEXATTR = 235
    LREMOVEXATTR = 236
    FREMOVEXATTR = 237
    TKILL = 238
    SENDFILE64 = 239
    FUTEX = 240
    SCHED_SETAFFINITY = 241
    SCHED_GETAFFINITY = 242
    SET_THREAD_AREA = 243
    GET_THREAD_AREA = 244
    IO_SETUP = 245
    IO_DESTROY = 246
    IO_GETEVENTS = 247
    IO_SUBMIT = 248
    IO_CANCEL = 249
    FADVISE64 = 250
    EXIT_GROUP = 252
    LOOKUP_DCOOKIE = 253
    EPOLL_CREATE = 254
    EPOLL_CTL = 255
    EPOLL_WAIT = 256
    REMAP_FILE_PAGES = 257
    SET_TID_ADDRESS = 258
    TIMER_CREATE = 259
    TIMER_SETTIME = 260
    TIMER_GETTIME = 261
    TIMER_GETOVERRUN = 262
    TIMER_DELETE = 263
    CLOCK_SETTIME = 264
    CLOCK_GETTIME = 265
    CLOCK_GETRES = 266
    CLOCK_NANOSLEEP = 267
    STATFS64 = 268
    FSTATFS64 = 269
    TGKILL = 270
    UTIMES = 271
    VSERVER = 273
    MBIND = 274
    SET_MEMPOLICY = 275
    GET_MEMPOLICY = 276
    MQ_OPEN = 277
    MQ_UNLINK = 278
    MQ_TIMEDSEND = 279
    MQ_TIMEDRECEIVE = 280
    MQ_NOTIFY = 281
    MQ_GETSETATTR = 282
    KEXEC_LOAD = 283
    WAITID = 284
    ADD_KEY = 286
    REQUEST_KEY = 287
    KEYCTL = 288
    IOPRIO_SET = 289
    IOPRIO_GET = 290
    INOTIFY_INIT = 291
    INOTIFY_ADD_WATCH = 292
    INOTIFY_RM_WATCH = 293
    MIGRATE_PAGES = 294
    OPENAT = 295
    MKDIRAT = 296
    MKNODAT = 297
    FCHOWNAT = 298
    FUTIMESAT = 299
    FSTATAT64 = 300
    UNLINKAT = 301
    RENAMEAT = 302
    LINKAT = 303
    SYMLINKAT = 304
    READLINKAT = 305
    FCHMODAT = 306
    FACCESSAT = 307
    PSELECT6 = 308
    PPOLL = 309
    UNSHARE = 310
    SET_ROBUST_LIST = 311
    GET_ROBUST_LIST = 312
    SPLICE = 313
    TEE = 314
    SYNC_FILE_RANGE = 315
    VMSPLICE = 316
    MOVE_PAGES = 317
    GETCPU = 318
    EPOLL_PWAIT = 319
    UTIMENSAT = 320
    SIGNALFD = 321
    TIMERFD_CREATE = 322
    EVENTFD = 323
    FALLOCATE = 324
    TIMERFD_SETTIME = 325
    TIMERFD_GETTIME = 326
    ACCEPT4 = 327
    SIGNALFD4 = 328
    EVENTFD2 = 329
    EPOLL_CREATE1 = 330
    DUP3 = 331
    PIPE2 = 332
    INOTIFY_INIT1 = 333
    PREADV = 333
    PWRITEV = 334
    RT_TGSIGQUEUEINFO = 335
    PERF_EVENT_OPEN = 336
    RECVMMSG = 337
    FANOTIFY_INIT = 338
    FANOTIFY_MARK = 339
    PRLIMIT64 = 340
    NAME_TO_HANDLE_AT = 341
    OPEN_BY_HANDLE_AT = 342
    CLOCK_ADJTIME = 343
    SYNCFS = 344
    SENDMMSG = 345
    SETNS = 346
    KCMP = 347
    FINIT_MODULE = 348
    SCHED_SETATTR = 349
    SCHED_GETATTR = 350
    RENAMEAT2 = 351
    SECCOMP = 354
    GETRANDOM = 355
    MEMFD_CREATE = 356
    BPF = 357
    EXECVEAT = 358
    SOCKET = 359
    SOCKETPAIR = 360
    BIND = 361
    CONNECT = 362
    LISTEN = 363
    ACCEPT = 364
    GETSOCKNAME = 365
    GETPEERNAME = 366


# file open flags
# The O_* flags the guest passes to open.
class OpenFlags(IntEnum):
    O_RDONLY = 0o0
    O_WRONLY = 0o1
    O_RDWR = 0o2
    O_CREAT = 0o100
    O_EXCL = 0o200
    O_NOCTTY = 0o400
    O_TRUNC = 0o1000
    O_APPEND = 0o2000
    O_NONBLOCK = 0o4000
    O_DSYNC = 0o10000
    FASYNC = 0o20000
    O_DIRECT = 0o40000
    O_LARGEFILE = 0o100000
    O_DIRECTORY = 0o200000
    O_NOFOLLOW = 0o400000
    O_NOATIME = 0o1000000
    O_CLOEXEC = 0o2000000
    O_SYNC = 0o4010000
    O_PATH = 0o10000000


# Translate a PROT_* value into MemoryProtection bits.
# PROT_NONE=0x0, PROT_READ=0x1, PROT_WRITE=0x2, PROT_EXEC=0x4 are the kernel's
# bit assignment; MemoryProtection numbers them like x86 PF_* flags instead,
# so a mechanical passthrough transposes read and exec.
def _mmap_prot_to_region(prot: int) -> int:
    from .elf_loader import MemoryProtection
    flags = 0
    if prot & int(MmapProt.PROT_READ):
        flags |= int(MemoryProtection.READ)
    if prot & int(MmapProt.PROT_WRITE):
        flags |= int(MemoryProtection.WRITE)
    if prot & int(MmapProt.PROT_EXEC):
        flags |= int(MemoryProtection.EXEC)
    return flags


# mmap protection flags
# The PROT_* protection bits mmap and mprotect take.
class MmapProt(IntEnum):
    PROT_NONE = 0x0
    PROT_READ = 0x1
    PROT_WRITE = 0x2
    PROT_EXEC = 0x4
    PROT_GROWSDOWN = 0x01000000
    PROT_GROWSUP = 0x02000000


# mmap flags
# The MAP_* flags mmap takes.
class MmapFlags(IntEnum):
    MAP_SHARED = 0x01
    MAP_PRIVATE = 0x02
    MAP_SHARED_VALIDATE = 0x03
    MAP_TYPE = 0x0f
    MAP_FIXED = 0x10
    MAP_ANONYMOUS = 0x20
    MAP_32BIT = 0x40
    MAP_GROWSDOWN = 0x00100
    MAP_DENYWRITE = 0x00800
    MAP_EXECUTABLE = 0x01000
    MAP_LOCKED = 0x02000
    MAP_NORESERVE = 0x04000
    MAP_POPULATE = 0x08000
    MAP_NONBLOCK = 0x10000
    MAP_STACK = 0x20000
    MAP_HUGETLB = 0x40000
    MAP_SYNC = 0x80000
    MAP_FIXED_NOREPLACE = 0x100000


# One guest file descriptor and the host file behind it.
@dataclass
class FileDescriptor:
    fd: int
    path: str
    flags: int
    position: int = 0
    is_open: bool = True


# Answer guest syscalls by calling the host on the program's behalf.
class SyscallEmulator:
    
# Bind to a loaded image, open the standard descriptors, install the handlers.
    def __init__(self, loader):
        self.loader = loader
        self.is_64bit = not loader.parser.is_32bit
        
# file descriptor table
        self.fd_table: Dict[int, FileDescriptor] = {}
        self.next_fd = 3  # 0, 1 and 2 are reserved for stdin, stdout and stderr
        
# standard file descriptors stay open
        self._init_stdio()
        
# process information
        self.pid = random.randint(1000, 65535)
        self.ppid = random.randint(1000, 65535)
        self.uid = 1000
        self.gid = 1000
        self.euid = 1000
        self.egid = 1000
        
# working directory
        self.cwd = os.getcwd()
        
# syscall number to handler
        self._setup_syscall_handlers()
        
# memory mappings
        self.mmaps: Dict[int, Tuple[int, int]] = {}  # address to (size, flags)
        self.mmap_base = 0x7f0000000000 if self.is_64bit else 0x40000000
    
# Reserve fds 0 to 2 and create the output capture buffers.
    def _init_stdio(self):
        self.fd_table[0] = FileDescriptor(0, "<stdin>", OpenFlags.O_RDONLY)
        self.fd_table[1] = FileDescriptor(1, "<stdout>", OpenFlags.O_WRONLY)
        self.fd_table[2] = FileDescriptor(2, "<stderr>", OpenFlags.O_WRONLY)
        
# output buffers that capture stdout and stderr
        self.stdout_buffer: List[bytes] = []
        self.stderr_buffer: List[bytes] = []
        
# stdout and stderr properties, kept for compatibility
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        
# the guest's fd 0: None means it reads the host's own stdin
        self.stdin: Optional[str] = None
        self.stdin_pos: int = 0
    
# Feed the guest a fixed input string, replacing the host's stdin for fd 0.
    def set_stdin(self, data: str) -> None:
        self.stdin = data
        self.stdin_pos = 0
    
# Map numbers to handlers, using the i386 table in 32-bit mode.
    def _setup_syscall_handlers(self):
        self.handlers: Dict[int, Callable] = {
# file operations
            SyscallX86_64.READ: self.sys_read,
            SyscallX86_64.WRITE: self.sys_write,
            SyscallX86_64.OPEN: self.sys_open,
            SyscallX86_64.CLOSE: self.sys_close,
            SyscallX86_64.LSEEK: self.sys_lseek,
            SyscallX86_64.ACCESS: self.sys_access,
            SyscallX86_64.STAT: self.sys_stat,
            SyscallX86_64.FSTAT: self.sys_fstat,
            SyscallX86_64.LSTAT: self.sys_lstat,
            
# memory management
            SyscallX86_64.MMAP: self.sys_mmap,
            SyscallX86_64.MUNMAP: self.sys_munmap,
            SyscallX86_64.MPROTECT: self.sys_mprotect,
            SyscallX86_64.BRK: self.sys_brk,
            
# process management
            SyscallX86_64.EXIT: self.sys_exit,
            SyscallX86_64.EXIT_GROUP: self.sys_exit_group,
            SyscallX86_64.GETPID: self.sys_getpid,
            SyscallX86_64.GETPPID: self.sys_getppid,
            SyscallX86_64.GETUID: self.sys_getuid,
            SyscallX86_64.GETGID: self.sys_getgid,
            SyscallX86_64.GETEUID: self.sys_geteuid,
            SyscallX86_64.GETEGID: self.sys_getegid,
            
# time
            SyscallX86_64.GETTIMEOFDAY: self.sys_gettimeofday,
            SyscallX86_64.CLOCK_GETTIME: self.sys_clock_gettime,
            SyscallX86_64.NANOSLEEP: self.sys_nanosleep,
            
# system information
            SyscallX86_64.UNAME: self.sys_uname,
            SyscallX86_64.SYSINFO: self.sys_sysinfo,
            
# file system
            SyscallX86_64.GETCWD: self.sys_getcwd,
            SyscallX86_64.CHDIR: self.sys_chdir,
            SyscallX86_64.MKDIR: self.sys_mkdir,
            SyscallX86_64.RMDIR: self.sys_rmdir,
            SyscallX86_64.UNLINK: self.sys_unlink,
            SyscallX86_64.RENAME: self.sys_rename,
            
            # I/O
            SyscallX86_64.IOCTL: self.sys_ioctl,
            SyscallX86_64.FCNTL: self.sys_fcntl,
            SyscallX86_64.READV: self.sys_readv,
            SyscallX86_64.WRITEV: self.sys_writev,
            
# directories
            SyscallX86_64.GETDENTS64: self.sys_getdents64,
            
# everything else
            SyscallX86_64.ARCH_PRCTL: self.sys_arch_prctl,
            SyscallX86_64.PREAD64: self.sys_pread64,
            SyscallX86_64.PWRITE64: self.sys_pwrite64,
        }
        
# i386 syscall number mapping
        if not self.is_64bit:
            self.handlers = {
                SyscallI386.READ: self.sys_read,
                SyscallI386.WRITE: self.sys_write,
                SyscallI386.OPEN: self.sys_open,
                SyscallI386.CLOSE: self.sys_close,
                SyscallI386.LSEEK: self.sys_lseek,
                SyscallI386.ACCESS: self.sys_access,
                SyscallI386.STAT: self.sys_stat,
                SyscallI386.FSTAT: self.sys_fstat,
                SyscallI386.LSTAT: self.sys_lstat,
                SyscallI386.MMAP: self.sys_mmap,
                SyscallI386.MUNMAP: self.sys_munmap,
                SyscallI386.MPROTECT: self.sys_mprotect,
                SyscallI386.BRK: self.sys_brk,
                SyscallI386.EXIT: self.sys_exit,
                SyscallI386.GETPID: self.sys_getpid,
                SyscallI386.GETPPID: self.sys_getppid,
                SyscallI386.GETUID: self.sys_getuid,
                SyscallI386.GETGID: self.sys_getgid,
                SyscallI386.GETEUID: self.sys_geteuid,
                SyscallI386.GETEGID: self.sys_getegid,
                SyscallI386.GETTIMEOFDAY: self.sys_gettimeofday,
                SyscallI386.UNAME: self.sys_uname,
                SyscallI386.SYSINFO: self.sys_sysinfo,
                SyscallI386.GETCWD: self.sys_getcwd,
                SyscallI386.CHDIR: self.sys_chdir,
                SyscallI386.MKDIR: self.sys_mkdir,
                SyscallI386.RMDIR: self.sys_rmdir,
                SyscallI386.UNLINK: self.sys_unlink,
                SyscallI386.RENAME: self.sys_rename,
                SyscallI386.IOCTL: self.sys_ioctl,
                SyscallI386.FCNTL: self.sys_fcntl,
                SyscallI386.GETDENTS: self.sys_getdents64,
            }
    
# Dispatch one syscall, turning a host exception into a negative errno.
    def handle_syscall(self, num: int, *args) -> int:
        handler = self.handlers.get(num)
        if handler:
            try:
                result = handler(*args)
                if num == 12:  # BRK
                    logger.debug(f"BRK({args[0]:#x}) -> {result:#x}")
                return result
            except SystemExit:
                raise
            except Exception as e:
                logger.error(f"Syscall {num} error: {e}")
                return -self._get_errno(e)
        else:
            logger.warning(f"Unimplemented syscall: {num}")
            return -errno.ENOSYS
    
# Map a host exception onto the errno the guest expects.
    def _get_errno(self, e: Exception) -> int:
        from .elf_loader import MemoryAccessError, MemoryProtectionError
        
        if isinstance(e, MemoryAccessError):
            return errno.EFAULT
        elif isinstance(e, MemoryProtectionError):
            return errno.EFAULT
        elif isinstance(e, FileNotFoundError):
            return errno.ENOENT
        elif isinstance(e, PermissionError):
            return errno.EACCES
        elif isinstance(e, IsADirectoryError):
            return errno.EISDIR
        elif isinstance(e, NotADirectoryError):
            return errno.ENOTDIR
        elif isinstance(e, OSError):
            return e.errno if e.errno else errno.EIO
        else:
            return errno.EIO
    
# Read a NUL-terminated string out of guest memory.
    def _read_string(self, addr: int) -> str:
        from .elf_loader import MemoryAccessError
        
        result = bytearray()
        offset = 0
        while True:
            try:
                byte = self.loader.read_memory(addr + offset, 1)
                if byte == b'\x00':
                    break
                result.extend(byte)
                offset += 1
                if offset > 4096:  # cap the length
                    break
            except MemoryAccessError:
# the loader raises this, not MemoryError, for an address outside every region
# a pointer that is not mapped at all is the guest's fault and has to become EFAULT,
# while a path that simply runs off the end of a mapping stays truncated
                if not result:
                    raise
                break
        return result.decode('utf-8', errors='replace')
    
# Read size bytes out of guest memory.
    def _read_buffer(self, addr: int, size: int) -> bytes:
        return self.loader.read_memory(addr, size)
    
# Write data into guest memory.
    def _write_buffer(self, addr: int, data: bytes):
        self.loader.write_memory(addr, data)
    
# ==================== syscall implementations ====================
    
# Read from a descriptor into guest memory.
    def sys_read(self, fd: int, buf: int, count: int) -> int:
        if fd in (0, 1, 2):  # standard I/O
            if fd == 0 and self.stdin is not None:
# a supplied input string replaces the host's stdin, and its end reads as EOF
                chunk = self.stdin[self.stdin_pos:self.stdin_pos + count]
                self.stdin_pos += len(chunk)
                data = chunk.encode()
                self._write_buffer(buf, data)
                return len(data)
            try:
                data = os.read(fd, count)
                self._write_buffer(buf, data)
                return len(data)
            except OSError as e:
                return -e.errno
        
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            with open(fd_obj.path, 'rb') as f:
                f.seek(fd_obj.position)
                data = f.read(count)
                self._write_buffer(buf, data)
                fd_obj.position += len(data)
                return len(data)
        except OSError as e:
            return -e.errno
    
# Write from guest memory to a descriptor or to the capture buffer.
    def sys_write(self, fd: int, buf: int, count: int, *args) -> int:
        try:
            data = self._read_buffer(buf, count)
        except Exception as e:
            return -errno.EIO
        
        if fd == 1:  # stdout
            self.stdout_buffer.append(data)
            return count
        elif fd == 2:  # stderr
            self.stderr_buffer.append(data)
            return count
        elif fd == 0:  # stdin is an error
            return -errno.EBADF
        
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            mode = 'ab' if fd_obj.flags & OpenFlags.O_APPEND else 'r+b'
            with open(fd_obj.path, mode) as f:
                if not (fd_obj.flags & OpenFlags.O_APPEND):
                    f.seek(fd_obj.position)
                f.write(data)
                fd_obj.position += len(data)
            return count
        except OSError as e:
            return -e.errno
    
# Open a host file and hand the guest a new descriptor.
    def sys_open(self, pathname: int, flags: int, mode: int = 0o666) -> int:
        path = self._read_string(pathname)
        
# resolve a relative path
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
# see whether the file exists
        exists = os.path.exists(path)
        
# decode the flags
        read_write = flags & 0o3
        create = bool(flags & OpenFlags.O_CREAT)
        truncate = bool(flags & OpenFlags.O_TRUNC)
        exclusive = bool(flags & OpenFlags.O_EXCL)
        
        if exclusive and create and exists:
# Linux defines EEXIST only for O_EXCL together with O_CREAT; a bare O_EXCL must not fail
            return -errno.EEXIST
        
        if create:
            try:
                if not exists:
                    open(path, 'w').close()
            except OSError as e:
                return -e.errno
        
        if not os.path.exists(path):
            return -errno.ENOENT
        
# take a free descriptor
        fd_num = self.next_fd
        self.next_fd += 1
        
        fd_obj = FileDescriptor(fd_num, path, flags)
        self.fd_table[fd_num] = fd_obj
        
        if truncate and read_write != OpenFlags.O_RDONLY:
            open(path, 'w').close()
        
        return fd_num
    
# Close a descriptor; the standard three always succeed.
    def sys_close(self, fd: int) -> int:
        if fd in (0, 1, 2):
            return 0  # the standard descriptors cannot be closed
        
        fd_obj = self.fd_table.get(fd)
        if not fd_obj:
            return -errno.EBADF
        
        fd_obj.is_open = False
        del self.fd_table[fd]
        return 0
    
# Move the file position and return the new one.
    def sys_lseek(self, fd: int, offset: int, whence: int) -> int:
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            if whence == 0:  # SEEK_SET
                fd_obj.position = offset
            elif whence == 1:  # SEEK_CUR
                fd_obj.position += offset
            elif whence == 2:  # SEEK_END
                size = os.path.getsize(fd_obj.path)
                fd_obj.position = size + offset
            else:
                return -errno.EINVAL
            return fd_obj.position
        except OSError as e:
            return -e.errno
    
# Check that a path exists; the access mode is not enforced.
    def sys_access(self, pathname: int, mode: int) -> int:
        path = self._read_string(pathname)
        
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
        try:
            if not os.path.exists(path):
                return -errno.ENOENT
# simplified: everything is assumed accessible
            return 0
        except OSError as e:
            return -e.errno
    
# Fill a guest struct stat from the host's os.stat.
    def sys_stat(self, pathname: int, statbuf: int) -> int:
        path = self._read_string(pathname)
        
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
        try:
            st = os.stat(path)
            self._write_stat(statbuf, st)
            return 0
        except OSError as e:
            return -e.errno
    
# Fill a guest struct stat for an already open descriptor.
    def sys_fstat(self, fd: int, statbuf: int) -> int:
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            st = os.stat(fd_obj.path)
            self._write_stat(statbuf, st)
            return 0
        except OSError as e:
            return -e.errno
    
# Fill a guest struct stat for the link itself, so lstat does not follow the target.
    def sys_lstat(self, pathname: int, statbuf: int) -> int:
        path = self._read_string(pathname)
        
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
        try:
            st = os.lstat(path)
            self._write_stat(statbuf, st)
            return 0
        except OSError as e:
            return -e.errno
    
# Write this architecture's struct stat layout into guest memory.
    def _split_timespec(self, stamp):
        """Split a float timestamp into whole seconds and nanoseconds."""
        whole = int(stamp)
        return whole, int((stamp - whole) * 1000000000)

    def _write_stat(self, addr: int, st: os.stat_result):
        atime, atime_nsec = self._split_timespec(st.st_atime)
        mtime, mtime_nsec = self._split_timespec(st.st_mtime)
        ctime, ctime_nsec = self._split_timespec(st.st_ctime)
        if self.is_64bit:
# x86_64 struct stat is 144 bytes: dev/ino/nlink 8 each, mode/uid/gid/pad
# 4 each, rdev/size/blksize/blocks 8 each, three 16-byte timespecs,
# then three reserved words. Fields before this patch were shifted.
            data = struct.pack('<QQQLLLlQQQQqqqqqqQQQ',
                st.st_dev,      # dev
                st.st_ino,      # ino
                st.st_nlink,    # nlink
                st.st_mode,     # mode
                st.st_uid,      # uid
                st.st_gid,      # gid
                0,              # __pad0
                st.st_rdev,     # rdev
                st.st_size,     # size
                st.st_blksize,  # blksize
                st.st_blocks,   # blocks
                atime,          # atime
                atime_nsec,
                mtime,          # mtime
                mtime_nsec,
                ctime,          # ctime
                ctime_nsec,
                0, 0, 0         # __glibc_reserved
            )
        else:
# i386 struct stat64 is 96 bytes: the second ino carries the full value.
            data = struct.pack('<QIIIIIIQIQIQQQQQ',
                st.st_dev,      # dev
                0,              # __pad1
                st.st_ino & 0xffffffff,  # __st_ino
                st.st_mode,     # mode
                st.st_nlink,    # nlink
                st.st_uid,      # uid
                st.st_gid,      # gid
                st.st_rdev,     # rdev
                0,              # __pad2
                st.st_size,     # size
                st.st_blksize,  # blksize
                st.st_blocks,   # blocks
                atime,
                mtime,
                ctime,
                st.st_ino,      # st_ino
            )
        self._write_buffer(addr, data)
    
# Return a free page-aligned range of size, preferring hint.
    def _find_free_memory(self, size: int, hint: int = 0) -> int:
        size = (size + 0xfff) & ~0xfff
        
        if hint != 0:
            if self._is_region_free(hint, size):
                return hint
        
        addr = self.mmap_base
        max_iterations = 10000
        for _ in range(max_iterations):
            if self._is_region_free(addr, size):
                self.mmap_base = addr + size
                return addr
            addr += 0x10000
        
        return 0
    
# Report whether the range overlaps nothing the loader has mapped.
    def _is_region_free(self, addr: int, size: int) -> bool:
        for region in self.loader.memory.values():
            if addr < region.end and addr + size > region.start:
                return False
        return True
    
# Map a fresh region into the loader, anonymous or file backed.
    def sys_mmap(self, addr: int, length: int, prot: int, flags: int, fd: int, offset: int) -> int:
        if length <= 0:
            return -errno.EINVAL
        
        length_aligned = (length + 0xfff) & ~0xfff
        map_fixed = bool(flags & MmapFlags.MAP_FIXED)
        map_anonymous = bool(flags & MmapFlags.MAP_ANONYMOUS)
        
        if map_fixed and addr != 0:
            if not self._is_region_free(addr, length_aligned):
                return -errno.ENOMEM
        elif addr == 0 or not self._is_region_free(addr, length_aligned):
            addr = self._find_free_memory(length_aligned, addr)
            if addr == 0:
                return -errno.ENOMEM
        
        if map_anonymous:
            from .elf_loader import MemoryRegion
            region = MemoryRegion(
                start=addr,
                size=length_aligned,
                data=bytearray(length_aligned),
                flags=_mmap_prot_to_region(prot),
                name="mmap"
            )
            self.loader.memory[addr] = region
            self.mmaps[addr] = (length_aligned, prot)
            return addr
        
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            with open(fd_obj.path, 'rb') as f:
                f.seek(offset)
                data = f.read(length)
            
            from .elf_loader import MemoryRegion
            region_data = bytearray(length_aligned)
            region_data[:len(data)] = data
            
            region = MemoryRegion(
                start=addr,
                size=length_aligned,
                data=region_data,
                flags=_mmap_prot_to_region(prot),
                name="mmap_file"
            )
            self.loader.memory[addr] = region
            self.mmaps[addr] = (length_aligned, prot)
            return addr
        except OSError as e:
            return -e.errno
    
# Drop a mapping this emulator made.
    def sys_munmap(self, addr: int, length: int) -> int:
        if addr in self.mmaps:
            del self.mmaps[addr]
            if addr in self.loader.memory:
                del self.loader.memory[addr]
            return 0
        return -errno.EINVAL
    
# Change protection; accepted and ignored, so the old bits stay.
    def sys_mprotect(self, addr: int, length: int, prot: int) -> int:
# Change the protection of every mapped region the range touches.
        region_flags = _mmap_prot_to_region(prot)
        end = addr + length
        touched = False
        for region in self.loader.memory.values():
            if region.end <= addr or region.start >= end:
                continue
            region.flags = region_flags
            touched = True
        if not touched:
            return -errno.ENOMEM
        self.mmaps[addr] = (length, prot)
        return 0
    
# Report the break when addr is zero, otherwise grow the heap.
    def sys_brk(self, addr: int, *args) -> int:
        if addr == 0:
            return self.loader.brk
        return self.loader.brk_extend(addr)
    
# End the run by raising SystemExit with the guest's status.
    def sys_exit(self, status: int, *args) -> int:
        raise SystemExit(status)
    
# End the run; there is only one thread, so this is sys_exit again.
    def sys_exit_group(self, status: int, *args) -> int:
        raise SystemExit(status)
    
# Return the invented pid.
    def sys_getpid(self) -> int:
        return self.pid
    
# Return the invented parent pid.
    def sys_getppid(self) -> int:
        return self.ppid
    
# Return the invented real uid.
    def sys_getuid(self) -> int:
        return self.uid
    
# Return the invented real gid.
    def sys_getgid(self) -> int:
        return self.gid
    
# Return the invented effective uid.
    def sys_geteuid(self) -> int:
        return self.euid
    
# Return the invented effective gid.
    def sys_getegid(self) -> int:
        return self.egid
    
# Fill a guest timeval from the host clock.
    def sys_gettimeofday(self, tv: int, tz: int) -> int:
        now = time.time()
        sec = int(now)
        usec = int((now - sec) * 1000000)
        
        if self.is_64bit:
            data = struct.pack('<QQ', sec, usec)
        else:
            data = struct.pack('<II', sec, usec)
        
        self._write_buffer(tv, data)
        return 0
    
# Fill a guest timespec; the clock id is ignored.
    def sys_clock_gettime(self, clk_id: int, tp: int) -> int:
        now = time.time()
        sec = int(now)
        nsec = int((now - sec) * 1000000000)
        
        data = struct.pack('<QQ', sec, nsec)
        self._write_buffer(tp, data)
        return 0
    
# Sleep the host for the requested time, so the guest really waits.
    def sys_nanosleep(self, req: int, rem: int) -> int:
        if self.is_64bit:
            data = self._read_buffer(req, 16)
            sec, nsec = struct.unpack('<QQ', data)
        else:
            data = self._read_buffer(req, 8)
            sec, nsec = struct.unpack('<II', data)
        
        time.sleep(sec + nsec / 1000000000)
        return 0
    
# Fill a guest struct utsname with fixed PySpOS strings.
    def sys_uname(self, buf: int) -> int:
# utsname layout
        sysname = b"PySPK\x00"
        nodename = b"pyspos\x00"
        release = b"3.0.0\x00"
        version = b"#1 SMP\x00"
        machine = b"x86_64\x00" if self.is_64bit else b"i686\x00"
        domainname = b"(none)\x00"
        
# Linux uses _UTSNAME_LENGTH = 65 per field and the same six fields (sysname, nodename,
# release, version, machine, domainname) on i386 and x86_64, so the word size does not
# change the layout and the struct is 390 bytes on both
        field_size = 65
        
        data = (
            sysname.ljust(field_size, b'\x00') +
            nodename.ljust(field_size, b'\x00') +
            release.ljust(field_size, b'\x00') +
            version.ljust(field_size, b'\x00') +
            machine.ljust(field_size, b'\x00') +
            domainname.ljust(field_size, b'\x00')
        )
        
        self._write_buffer(buf, data)
        return 0
    
# Fill a guest struct sysinfo from the host's memory statistics.
    def sys_sysinfo(self, info: int) -> int:
        import psutil
        
        mem = psutil.virtual_memory()
        
        if self.is_64bit:
# x86_64 layout, 112 bytes: uptime, loads[3], six memory words, procs and pad as u16,
# four bytes of alignment padding, totalhigh, freehigh, mem_unit, then the struct's own tail
            data = struct.pack('<QQQQQQQQQQHH4xQQI4x',
                int(time.time()),  # uptime
                1,  # loads[0]
                1,  # loads[1]
                1,  # loads[2]
                mem.total // 1024,  # totalram
                mem.free // 1024,   # freeram
                mem.shared // 1024 if hasattr(mem, 'shared') else 0,  # sharedram
                0,  # bufferram
                0,  # totalswap
                0,  # freeswap
                1,  # procs
                0,  # pad
                0,  # totalhigh
                0,  # freehigh
                1   # mem_unit
            )
        else:
# i386 layout, 64 bytes: the same field order with 4 byte words, no alignment padding,
# and the libc5 _f tail
            data = struct.pack('<IIIIIIIIIIHHIII8x',
                int(time.time()),  # uptime
                1,  # loads[0]
                1,  # loads[1]
                1,  # loads[2]
                mem.total // 1024,  # totalram
                mem.free // 1024,   # freeram
                mem.shared // 1024 if hasattr(mem, 'shared') else 0,  # sharedram
                0,  # bufferram
                0,  # totalswap
                0,  # freeswap
                1,  # procs
                0,  # pad
                0,  # totalhigh
                0,  # freehigh
                1   # mem_unit
            )
        
        self._write_buffer(info, data)
        return 0
    
# Copy the working directory into the guest's buffer.
    def sys_getcwd(self, buf: int, size: int) -> int:
        cwd = self.cwd.encode('utf-8')
        if len(cwd) >= size:
            return -errno.ERANGE
        self._write_buffer(buf, cwd + b'\x00')
        return len(cwd) + 1
    
# Change the directory that relative guest paths resolve against.
    def sys_chdir(self, path: int) -> int:
        new_path = self._read_string(path)
        
        if not os.path.isabs(new_path):
            new_path = os.path.join(self.cwd, new_path)
        new_path = os.path.normpath(new_path)
        
        if not os.path.isdir(new_path):
            return -errno.ENOENT
        
        self.cwd = new_path
        return 0
    
# Create a host directory for the guest.
    def sys_mkdir(self, pathname: int, mode: int) -> int:
        path = self._read_string(pathname)
        
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
        try:
            os.mkdir(path, mode)
            return 0
        except OSError as e:
            return -e.errno
    
# Remove a host directory for the guest.
    def sys_rmdir(self, pathname: int) -> int:
        path = self._read_string(pathname)
        
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
        try:
            os.rmdir(path)
            return 0
        except OSError as e:
            return -e.errno
    
# Delete a host file for the guest.
    def sys_unlink(self, pathname: int) -> int:
        path = self._read_string(pathname)
        
        if not os.path.isabs(path):
            path = os.path.join(self.cwd, path)
        path = os.path.normpath(path)
        
        try:
            os.unlink(path)
            return 0
        except OSError as e:
            return -e.errno
    
# Rename a host file for the guest.
    def sys_rename(self, oldpath: int, newpath: int) -> int:
        old = self._read_string(oldpath)
        new = self._read_string(newpath)
        
        if not os.path.isabs(old):
            old = os.path.join(self.cwd, old)
        if not os.path.isabs(new):
            new = os.path.join(self.cwd, new)
        
        old = os.path.normpath(old)
        new = os.path.normpath(new)
        
        try:
            os.rename(old, new)
            return 0
        except OSError as e:
            return -e.errno
    
# Accept the request and report success; no device is emulated.
    def sys_ioctl(self, fd: int, request: int, arg: int) -> int:
# simplified: report success
        return 0
    
# Validate the descriptor, then ignore the command.
    def sys_fcntl(self, fd: int, cmd: int, arg: int = 0) -> int:
        fd_obj = self.fd_table.get(fd)
        if not fd_obj:
            return -errno.EBADF
        
# simplified
        return 0
    
# Write host directory entries as guest struct linux_dirent64 records.
    def sys_getdents64(self, fd: int, dirp: int, count: int) -> int:
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        if not os.path.isdir(fd_obj.path):
            return -errno.ENOTDIR
        
        try:
            entries = os.listdir(fd_obj.path)
            result = bytearray()
            
            for entry in entries:
                entry_bytes = entry.encode('utf-8')
                entry_len = 24 + len(entry_bytes) + 1  # round up to a multiple of 8
                entry_len = (entry_len + 7) & ~7
                
                if len(result) + entry_len > count:
                    break
                
# linux_dirent64 layout
                d_ino = 0  # inode number
                d_off = 0  # offset
                d_reclen = entry_len
                d_type = 4 if os.path.isdir(os.path.join(fd_obj.path, entry)) else 8  # DT_DIR or DT_REG
                
                dirent = struct.pack('<QHHH', d_ino, d_off, d_reclen, d_type)
                dirent += entry_bytes + b'\x00'
                dirent += b'\x00' * (entry_len - len(dirent))
                
                result.extend(dirent)
            
            self._write_buffer(dirp, bytes(result))
            return len(result)
        except OSError as e:
            return -e.errno
    
# Accept the request and report success; TLS is not set up.
    def sys_arch_prctl(self, code: int, addr: int) -> int:
# simplified
        return 0
    
# Run sys_read once per iovec and add the counts up.
    def sys_readv(self, fd: int, iov: int, iovcnt: int) -> int:
        total = 0
        for i in range(iovcnt):
            if self.is_64bit:
                iov_base = self.loader.read_int(iov + i * 16, 8)
                iov_len = self.loader.read_int(iov + i * 16 + 8, 8)
            else:
                iov_base = self.loader.read_int(iov + i * 8, 4)
                iov_len = self.loader.read_int(iov + i * 8 + 4, 4)
            
            n = self.sys_read(fd, iov_base, iov_len)
            if n < 0:
                return n
            total += n
        return total
    
# Run sys_write once per iovec and add the counts up.
    def sys_writev(self, fd: int, iov: int, iovcnt: int) -> int:
        total = 0
        for i in range(iovcnt):
            if self.is_64bit:
                iov_base = self.loader.read_int(iov + i * 16, 8)
                iov_len = self.loader.read_int(iov + i * 16 + 8, 8)
            else:
                iov_base = self.loader.read_int(iov + i * 8, 4)
                iov_len = self.loader.read_int(iov + i * 8 + 4, 4)
            
            n = self.sys_write(fd, iov_base, iov_len)
            if n < 0:
                return n
            total += n
        return total
    
# Read at an explicit offset without moving the file position.
    def sys_pread64(self, fd: int, buf: int, count: int, offset: int) -> int:
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            with open(fd_obj.path, 'rb') as f:
                f.seek(offset)
                data = f.read(count)
                self._write_buffer(buf, data)
                return len(data)
        except OSError as e:
            return -e.errno
    
# Write at an explicit offset without moving the file position.
    def sys_pwrite64(self, fd: int, buf: int, count: int, offset: int) -> int:
        data = self._read_buffer(buf, count)
        
        fd_obj = self.fd_table.get(fd)
        if not fd_obj or not fd_obj.is_open:
            return -errno.EBADF
        
        try:
            with open(fd_obj.path, 'r+b') as f:
                f.seek(offset)
                f.write(data)
            return count
        except OSError as e:
            return -e.errno
