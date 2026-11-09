# Experimental WASI Preview 1 threads; Wasmtime is the runtime, not host libc.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
ARG WASI_VERSION=33
ARG WASI_SHA256=0ba8b5bfaeb2adf3f29bab5841d76cf5318ab8e1642ea195f88baba1abd47bce
# Wasmtime removed wasi-threads (`-S threads`) in 47.0.0; 36.x is the LTS line that still has it.
ARG WASMTIME_VERSION=v36.0.19
ARG WASMTIME_SHA256=c6070b3043023f3b8e8dc3473a4c360c0d6784aa4294f5a6fc803580fcb2c875
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 ca-certificates curl tar xz-utils && rm -rf /var/lib/apt/lists/*
RUN curl -fSL --retry 3 \
    "https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-${WASI_VERSION}/wasi-sdk-${WASI_VERSION}.0-x86_64-linux.tar.gz" \
    -o /tmp/wasi-sdk.tar.gz && \
    echo "${WASI_SHA256}  /tmp/wasi-sdk.tar.gz" | sha256sum -c - && \
    mkdir -p /opt/wasi-sdk && tar -xzf /tmp/wasi-sdk.tar.gz -C /opt/wasi-sdk --strip-components=1 && \
    rm /tmp/wasi-sdk.tar.gz && test -x /opt/wasi-sdk/bin/clang
# Pinned Wasmtime release tarball, installed outside /root so a non-root user can run it.
RUN curl -fSL --retry 3 \
    "https://github.com/bytecodealliance/wasmtime/releases/download/${WASMTIME_VERSION}/wasmtime-${WASMTIME_VERSION}-x86_64-linux.tar.xz" \
    -o /tmp/wasmtime.tar.xz && \
    echo "${WASMTIME_SHA256}  /tmp/wasmtime.tar.xz" | sha256sum -c - && \
    mkdir -p /opt/wasmtime && tar -xJf /tmp/wasmtime.tar.xz -C /opt/wasmtime --strip-components=1 && \
    rm /tmp/wasmtime.tar.xz && ln -s /opt/wasmtime/wasmtime /usr/local/bin/wasmtime && wasmtime --version
WORKDIR /workspace
