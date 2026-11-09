/* Intentionally undefined behavior: pthread_join(pthread_self()).
 * The caller MUST enforce a wall-clock timeout from another process.
 *
 * Usage:  self_join          self-join from the initial (main) thread
 *         self_join thread   self-join from a pthread_create()d thread
 *
 * Every marker is printed and flushed BEFORE the call that may hang, so a
 * watchdog kill still leaves evidence that the probe started.
 */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L /* -std=c11 is strict ANSI; keep POSIX decls visible */
#endif
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

/* Compile-time fingerprint of the C library actually linked. Order matters:
 * uClibc-ng also defines __GLIBC__, and Emscripten/Cosmopolitan sit on top of
 * other libcs' sources. musl deliberately defines no identifying macro, so a
 * Linux build with none of the known markers is reported as "linux-unmarked". */
#define SJ_STR2(x) #x
#define SJ_STR(x) SJ_STR2(x)
#if defined(__COSMOPOLITAN__)
#define SJ_LIBC "cosmopolitan"
#elif defined(__EMSCRIPTEN__)
#define SJ_LIBC "emscripten"
#elif defined(__wasi__)
#define SJ_LIBC "wasi-libc"
#elif defined(__BIONIC__)
#define SJ_LIBC "bionic"
#define SJ_LIBC_VERSION "api-" SJ_STR(__ANDROID_API__)
#elif defined(__UCLIBC__)
#define SJ_LIBC "uclibc-ng"
#define SJ_LIBC_VERSION SJ_STR(__UCLIBC_MAJOR__) "." SJ_STR(__UCLIBC_MINOR__) "." SJ_STR(__UCLIBC_SUBLEVEL__)
#elif defined(__dietlibc__)
#define SJ_LIBC "dietlibc"
#elif defined(__GLIBC__)
#define SJ_LIBC "glibc"
#define SJ_LIBC_VERSION SJ_STR(__GLIBC__) "." SJ_STR(__GLIBC_MINOR__)
#elif defined(__CYGWIN__)
#define SJ_LIBC "cygwin"
#elif defined(__MINGW32__)
#define SJ_LIBC "mingw-w64"
#elif defined(__APPLE__)
#define SJ_LIBC "apple"
#elif defined(__FreeBSD__)
#define SJ_LIBC "freebsd"
#elif defined(__OpenBSD__)
#define SJ_LIBC "openbsd"
#elif defined(__NetBSD__)
#define SJ_LIBC "netbsd"
#elif defined(__DragonFly__)
#define SJ_LIBC "dragonfly"
#elif defined(__illumos__)
#define SJ_LIBC "illumos"
#elif defined(__sun)
#define SJ_LIBC "solaris"
#elif defined(__linux__)
#define SJ_LIBC "linux-unmarked"
#else
#define SJ_LIBC "unknown"
#endif
#ifndef SJ_LIBC_VERSION
#define SJ_LIBC_VERSION ""
#endif

static int self_join(void) {
    pthread_t me = pthread_self();
    printf("SELFJOIN_IS_SELF=%d\n", pthread_equal(me, pthread_self()) ? 1 : 0);
    fflush(stdout);

    int rc = pthread_join(me, NULL);
    printf("SELFJOIN_RC=%d\n", rc);
    fflush(stdout);
    return rc;
}

static void *thread_main(void *arg) {
    (void)arg;
    self_join();
    return NULL;
}

int main(int argc, char **argv) {
    int in_thread = argc > 1 && strcmp(argv[1], "thread") == 0;

    /* Emit the platform-specific errno value BEFORE the call can hang. */
    printf("SELFJOIN_LIBC=%s\n", SJ_LIBC);
    printf("SELFJOIN_LIBC_VERSION=%s\n", SJ_LIBC_VERSION);
    printf("SELFJOIN_CASE=%s\n", in_thread ? "thread" : "main");
    printf("SELFJOIN_EDEADLK=%d\n", EDEADLK);
    fflush(stdout);

    if (!in_thread) {
        self_join();
        return 0;
    }

    pthread_t worker;
    int create_rc = pthread_create(&worker, NULL, thread_main, NULL);
    if (create_rc != 0) {
        printf("SELFJOIN_CREATE_RC=%d\n", create_rc);
        fflush(stdout);
        return 2;
    }
    /* If the worker's self-join hangs, this hangs too; the watchdog decides. */
    printf("SELFJOIN_OUTER_JOIN_RC=%d\n", pthread_join(worker, NULL));
    fflush(stdout);
    return 0;
}
