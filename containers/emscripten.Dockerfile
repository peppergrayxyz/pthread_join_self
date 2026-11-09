# Emscripten pthreads require WebAssembly/Node worker threads, not host pthreads.
FROM emscripten/emsdk:6.0.13@sha256:fb7864e398acfda863dfcea78b8bc8adad359fa60c6a0bbeb845931de64aa68a
RUN command -v python3 && command -v emcc && command -v node
# Build the multithreaded libc variants into the image's cache now. Otherwise
# the first -pthread link compiles them inside the probe's 90 s compile
# timeout. emcc takes lock files inside the cache even on a hit, so it must
# also be writable by the non-root UID that run_containers.py uses with Docker.
RUN printf 'int main(void){return 0;}\n' > /tmp/warm.c && \
    emcc -pthread -O0 /tmp/warm.c -o /tmp/warm.js -sPTHREAD_POOL_SIZE=1 -sENVIRONMENT=node -sEXIT_RUNTIME=1 && \
    rm -f /tmp/warm.* && chmod -R a+rwX "$(em-config CACHE)"
WORKDIR /workspace
