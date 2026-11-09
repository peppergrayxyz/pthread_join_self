# libc self-join matrix

According to POSIX, self-joining a thread is undefined behavior:

> The behavior is undefined if the value specified by the thread argument to
> pthread_join() refers to the calling thread.

```c
pthread_join(pthread_self(), NULL);
```

but the rationale recommends detecting it:

> If an implementation detects that the value specified by the thread argument
> to pthread_join() refers to the calling thread, it is recommended that the
> function should fail and report an [EDEADLK] error.

## Behavior of different libcs:

**Explicit userspace check, returns `EDEADLK`**

| Library | Check | Source | Harness |
|---|---|---|---|
| glibc | `pd == self`, skipped if a cancellation is already pending | [nptl/pthread_join_common.c#l50](https://sourceware.org/git/?p=glibc.git;a=blob;f=nptl/pthread_join_common.c;hb=4e465e5c3ed634f71690e1fb40ea91c49a5fbae9#l50) | EDEADLK / EDEADLK |
| uClibc-ng (NPTL) | `pd == self`, or a mutual join; skipped if a cancellation is pending | [nptl/pthread_join.c#L65-L78](https://github.com/wbx-github/uclibc-ng/blob/bbc1470d5d1c0f206cfdc3e9ebf60f6fd9cd3961/libpthread/nptl/pthread_join.c#L65-L78) | EDEADLK / EDEADLK |
| uClibc-ng (LinuxThreads) | `th == self` | [linuxthreads/join.c#L142-L145](https://github.com/wbx-github/uclibc-ng/blob/bbc1470d5d1c0f206cfdc3e9ebf60f6fd9cd3961/libpthread/linuxthreads/join.c#L142-L145) | — (Bootlin toolchain is NPTL) |
| dietlibc ⚠ | `th == this->pid`. **Misses the main thread until the thread library is initialized**: `_main_thread.pid` stays 0 until the first `pthread_create` | [pthread_join.c#L11](https://sources.debian.org/src/dietlibc/0.34~cvs20160606-18/libpthread/pthread_join.c/#L11), [`_main_thread`](https://sources.debian.org/src/dietlibc/0.34~cvs20160606-18/libpthread/pthread_internal.c/#L32), [pid set at init](https://sources.debian.org/src/dietlibc/0.34~cvs20160606-18/libpthread/pthread_internal.c/#L634) | **TIMEOUT** / EDEADLK |
| Android Bionic | `t == pthread_self()` | [pthread_join.cpp#39](https://android.googlesource.com/platform/bionic/+/731631f300090436d7f5df80d50b6275c8c60a93/libc/bionic/pthread_join.cpp#39) | — |
| LLVM libc | Self join, plus mutual join, in `Thread::join()` | [thread.cpp#L282-L301](https://github.com/llvm/llvm-project/blob/857e4563e81d8a81cc17ace40dfece1b575b9d36/libc/src/__support/threads/linux/thread.cpp#L282-L301) | — (not automated) |
| Cosmopolitan | Target's `ctid` futex is the caller's own | [pthread_timedjoin_np.c#L64-L71](https://github.com/jart/cosmopolitan/blob/aefad27c09ffda64c6ac64bd69f758e9f9c7b91d/libc/thread/pthread_timedjoin_np.c#L64-L71) | EDEADLK / EDEADLK |
| relibc | `ptr::eq(thread, current_thread())` | [src/pthread/mod.rs#L260-268](https://gitlab.redox-os.org/redox-os/relibc/-/blob/c3cc8b5fe1c6fbc40d6b5ea87e39daf2e19ddbc4/src/pthread/mod.rs#L260-268) | — (not automated) |
| FreeBSD libthr | `pthread == curthread` | [thr_join.c#L120-L121](https://github.com/freebsd/freebsd-src/blob/52bd0d1812b6c3fb31db9709ff56393fb082046c/lib/libthr/thread/thr_join.c#L120-L121) | — |
| DragonFly BSD | `pthread == curthread` (now in libc) | [lib/libc/thread/thr_join.c#L82-L83](https://github.com/DragonFlyBSD/DragonFlyBSD/blob/94448f622a06cde90ba42d688e9cab2448ad9ab3/lib/libc/thread/thr_join.c#L82-L83) | — |
| OpenBSD librthread | `thread == self` | [rthread.c#L303-L304](https://github.com/openbsd/src/blob/4dfcd9c33635b9250393ede1a49e450e7633b06a/lib/librthread/rthread.c#L303-L304) | — |
| NetBSD libpthread | `thread == self` | [pthread.c#L712-L713](https://github.com/NetBSD/src/blob/bb3360239e319cdd6c32b500d1d4402a3d2f6c98/lib/libpthread/pthread.c#L712-L713) | — |
| Apple libpthread | `thread == self`, or the target is waiting on us | [pthread_cancelable.c#L361-L363](https://github.com/apple-oss-distributions/libpthread/blob/42d026df5b07825070f60134b980a1ec2552dfee/src/pthread_cancelable.c#L361-L363) | — |
| Emscripten | `__pthread_self() == t` (if not detached) | [pthread_join.c#L20](https://github.com/emscripten-core/emscripten/blob/0710e809aa240e993925232711272d631c1445c4/system/lib/libc/musl/src/thread/pthread_join.c#L20) | EDEADLK / EDEADLK |
| Cygwin | `equal (*thread, joiner)` | [thread.cc#l2260](https://sourceware.org/git/?p=newlib-cygwin.git;a=blob;f=winsup/cygwin/thread.cc;hb=b5a71199fc6ad3f19ff40fae6e4935f4ea032222#l2260) | — |
| MinGW-w64 winpthreads | `pthread_equal(pthread_self(), t)` | [thread.c#L1743-L1744](https://github.com/mingw-w64/mingw-w64/blob/ae5227f620699c8d532609ae30dc66432b903dab/mingw-w64-libraries/winpthreads/src/thread.c#L1743-L1744) | — |

**`EDEADLK` from the kernel, or documented only**

| Library | Mechanism | Source | Harness |
|---|---|---|---|
| illumos | No libc check: `pthread_join` → `_thrp_join` → `lwp_wait`. The kernel follows the wait chain and returns `EDEADLK` when it reaches `curthread`, which also catches cycles | [thr.c#L1090-L1092](https://github.com/illumos/illumos-gate/blob/b1c424a261b16b9c81280c0eb6de8b2f9f4ffacb/usr/src/lib/libc/port/threads/thr.c#L1090-L1092), [lwpsys.c#L295-L303](https://github.com/illumos/illumos-gate/blob/b1c424a261b16b9c81280c0eb6de8b2f9f4ffacb/usr/src/uts/common/syscall/lwpsys.c#L295-L303) | — |
| Oracle Solaris 11.4 | Man page: `EDEADLK` "such as when a thread attempts to wait for itself". Closed source, so the implementation isn't verified | [pthread_join(3C), 11.4](https://docs.oracle.com/cd/E88353_01/html/E37843/pthread-join-3c.html) | — |

**No self check: self-join blocks, asserts, or returns 0**

| Library | Behavior | Source | Harness |
|---|---|---|---|
| musl | Futex-waits on its own `detach_state`, so it blocks forever. This is intentional: the maintainer [declined to return an error for UB](https://www.openwall.com/lists/musl/2026/11/07/8) (2026-11-07) and is [open to a deliberate crash](https://www.openwall.com/lists/musl/2026/11/09/1) (2026-11-09). Nothing merged | [pthread_join.c#n16](https://git.musl-libc.org/cgit/musl/tree/src/thread/pthread_join.c?id=7813e9119eb5fe681b6750b8a033a0490bca0941#n16) | TIMEOUT / TIMEOUT |
| wasi-libc, `wasi-threads` | Same musl wait loop, at the revision wasi-sdk 33 ships (`161b319`) | [wasi-threads/pthread_join.c#L18-L20](https://github.com/WebAssembly/wasi-libc/blob/161b3195fc2558d2b1ba3eb9ffae3b2b47407623/libc-top-half/musl/src/thread/wasi-threads/pthread_join.c#L18-L20) | TIMEOUT / TIMEOUT |
| wasi-libc, single-threaded | Stub: always returns `0` | [single-threaded/pthread_join.c#L21-L28](https://github.com/WebAssembly/wasi-libc/blob/161b3195fc2558d2b1ba3eb9ffae3b2b47407623/libc-top-half/musl/src/thread/single-threaded/pthread_join.c#L21-L28) | — |
| wasi-libc, `coop-threads` (new on `main`, not in wasi-sdk 33) | Waits on its own `joiner_futex` | [coop-threads/pthread_join.c#L23-L30](https://github.com/WebAssembly/wasi-libc/blob/ce2ee9fb7e39c20ae266d294dd2d0afd1bf1f8e2/libc-top-half/musl/src/thread/coop-threads/pthread_join.c#L23-L30) | — |
| mlibc | Futex-waits on its own `didExit` | [threads.cpp#L141-L157](https://github.com/managarm/mlibc/blob/28d2b90a418bc611733442b4093cb220c8506737/options/internal/generic/threads.cpp#L141-L157) | — (not automated) |
| CloudABI cloudlibc | `assert(thread != __pthread_self_object)`, so it aborts. With `NDEBUG` it falls through to the blocking wait | [pthread_join.c#L16-L17](https://github.com/NuxiNL/cloudlibc/blob/d361c06c3fab3a7814d05b4630abe6da0cc7d757/src/libc/pthread/pthread_join.c#L16-L17) | — (not automated) |

**Not applicable.** klibc, Linux nolibc, Newlib, Picolibc, AVR-LibC, PDCLib,
SEGGER emRun, the Arm C library, UCRT and MSVCRT have no standalone POSIX
`pthread_join`, or leave threads to an OS/RTOS layer.
