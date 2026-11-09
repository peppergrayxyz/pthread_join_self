#!/bin/sh
# Portable shell launcher for BSD/Solaris VMs. Find Python 3 without relying
# on a universal 'python3' alias (OpenBSD/NetBSD packages may be versioned).
set -eu
# The VM actions run this over a non-login ssh shell whose PATH can omit the
# package prefixes (NetBSD pkgsrc: /usr/pkg/bin; OpenBSD/FreeBSD: /usr/local/bin).
PATH="$PATH:/usr/pkg/bin:/usr/pkg/sbin:/usr/local/bin:/usr/local/sbin:/opt/local/bin"
export PATH
python=""
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python="$candidate"
        break
    fi
done
if [ -z "$python" ]; then
    echo "Python 3 is missing; install it in the guest prepare step" >&2
    exit 1
fi
exec "$python" scripts/run_case.py --id "$1" --libc "$2" --kind vm --cc "${3:-cc}" --out "results/$1.json"
