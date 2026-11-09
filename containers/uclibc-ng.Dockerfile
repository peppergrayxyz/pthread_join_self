# Genuine uClibc-ng toolchain: Debian is ONLY the host of the compiler/watchdog.
# A static binary prevents accidental execution against glibc via a host loader.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
ARG BOOTLIN_VERSION=x86-64--uclibc--stable-2025.08-1
ARG BOOTLIN_SHA256=39499bcca6c50e39ed61c2afbf0b4005fc676df72b9b68fff75347439061eb2c
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 ca-certificates curl xz-utils libstdc++6 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/bootlin && \
    curl -fSL --retry 3 "https://toolchains.bootlin.com/downloads/releases/toolchains/x86-64/tarballs/${BOOTLIN_VERSION}.tar.xz" -o /tmp/bootlin.tar.xz && \
    echo "${BOOTLIN_SHA256}  /tmp/bootlin.tar.xz" | sha256sum -c - && \
    tar -xf /tmp/bootlin.tar.xz -C /opt/bootlin && rm /tmp/bootlin.tar.xz && \
    sdk_relocate="$(find /opt/bootlin -name relocate-sdk.sh -print -quit)" && \
    if [ -n "$sdk_relocate" ]; then (cd "$(dirname "$sdk_relocate")" && sh ./relocate-sdk.sh); fi
COPY containers/uclibc-cc /usr/local/bin/uclibc-cc
RUN chmod +x /usr/local/bin/uclibc-cc && uclibc-cc --version
WORKDIR /workspace
