# Official prebuilt cosmocc toolchain (not the host glibc compiler), pinned by version and hash.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
ARG COSMOCC_VERSION=4.0.2
ARG COSMOCC_SHA256=85b8c37a406d862e656ad4ec14be9f6ce474c1b436b9615e91a55208aced3f44
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 ca-certificates curl unzip && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/cosmocc && \
    curl -fSL --retry 3 "https://github.com/jart/cosmopolitan/releases/download/${COSMOCC_VERSION}/cosmocc-${COSMOCC_VERSION}.zip" -o /tmp/cosmocc.zip && \
    echo "${COSMOCC_SHA256}  /tmp/cosmocc.zip" | sha256sum -c - && \
    unzip -q /tmp/cosmocc.zip -d /opt/cosmocc && rm /tmp/cosmocc.zip && \
    test -x /opt/cosmocc/bin/x86_64-unknown-cosmo-cc
# cosmocc's own tools (gcc, cc1, as, ld, ...) are APE files that start with an
# "MZ" header. Running them depends on the HOST kernel: a binfmt_misc handler
# for MZ (e.g. Wine) makes every compile fail with "not found", and without one
# a non-shell parent gets ENOEXEC. Convert them to native x86-64 ELF with the
# bundled ELF loader so the toolchain behaves the same on every host. (The
# probe built by x86_64-unknown-cosmo-cc is already a plain ELF.)
RUN cd /opt/cosmocc && \
    for f in $(find bin libexec -type f -perm -u+x); do \
        [ "$(head -c 6 "$f")" = "MZqFpD" ] && [ "$f" != bin/assimilate ] || continue; \
        bin/ape-x86_64.elf bin/assimilate -ecx "$f" >/dev/null || exit 1; \
    done && \
    bin/ape-x86_64.elf bin/assimilate -ecx -o /tmp/assimilate bin/assimilate && \
    mv /tmp/assimilate bin/assimilate && chmod 755 bin/assimilate && \
    ! find bin libexec -type f -perm -u+x -exec sh -c '[ "$(head -c 6 "$1")" = MZqFpD ]' _ {} \; -print | grep -q . && \
    bin/x86_64-unknown-cosmo-cc --version >/dev/null
WORKDIR /workspace
