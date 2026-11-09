# Gaps in the automated libc coverage

Do not list a libc as tested merely because its headers compile against a
*different* C runtime. To establish behavior, the program must link to the
intended implementation and execute in an environment where its pthread model
actually operates.

| Library | Practical next step | Blocker |
|---|---|---|
| **LLVM libc** | Build an LLVM-libc **full host build** and a standalone sysroot (see https://libc.llvm.org/full_host_build.html), then use that library for startup, linkage and pthreads. | Using `clang` against glibc would be a false result; bootstrapping a complete LLVM libc is relatively large. |
| **relibc** | Boot a Redox OS VM (`vmactions/redox-vm@v1`) and install an appropriate native C compiler/toolchain, then compile in the guest. | A generic Linux container does not exercise the Redox-specific relibc pthread implementation. |
| **mlibc** | Provision a Managarm OS VM or another supported OS image and its native C toolchain. | No broadly available turnkey runner/runtime. |
| **legacy uClibc** | Add a pinned older Buildroot Linux image with pthreads enabled and use its matching cross compiler. | Legacy toolchains and kernel compatibility. Current `linux-uclibc-ng` is a distinct maintained fork. |
| **klibc, nolibc** | Do not run a pthread test. | No generic POSIX `pthread_join` API. |
| **Newlib, Picolibc, AVR-LibC, emRun, Arm C library** | Choose a specific RTOS that supplies real pthreads, and label the result as that RTOS's pthread implementation, not libc-only behavior. | Different RTOS ports give different results. |
| **MSVCRT, UCRT** | Test an actual pthread provider instead; `windows-winpthreads` and `windows-cygwin` cover two. | Neither Microsoft CRT implements POSIX `pthread_join` itself. |
| **CloudABI** | Reconstruct historical userspace/runtime/toolchain as a separate historical experiment. | Unmaintained target. |

The new WASI target uses an experimental threaded sysroot and Wasmtime. If its
linker/loader cannot use that specific wasi-sdk release, report that as a
compile or run failure. Do **not** silently swap to WASI's stub pthread API.

All infrastructure errors and missing artifacts are intentionally presented
separately from `EDEADLK`, error returns and timeouts.
