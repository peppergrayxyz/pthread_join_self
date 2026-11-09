#!/usr/bin/env python3
"""Compile and run the self-join probe under a process-level watchdog.

Python 3.8+ standard library only. Designed to run inside a guest OS/container.
Always writes a machine-readable result for normal compile and test failures.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import re
import shlex
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def command_output(command, timeout=6):
    try:
        cp = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout)
        return (cp.stdout + cp.stderr).strip()[:6000]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unavailable: " + str(exc)


def run_command(command, timeout):
    start = time.monotonic()
    try:
        cp = subprocess.run(command, capture_output=True, timeout=timeout)
        return {
            "returncode": cp.returncode,
            "timed_out": False,
            "stdout": cp.stdout.decode("utf-8", "replace")[-16000:],
            "stderr": cp.stderr.decode("utf-8", "replace")[-16000:],
            "seconds": round(time.monotonic() - start, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "timed_out": True,
            "stdout": (exc.stdout or b"").decode("utf-8", "replace")[-16000:],
            "stderr": (exc.stderr or b"").decode("utf-8", "replace")[-16000:],
            "seconds": round(time.monotonic() - start, 3),
        }
    except OSError as exc:
        return {
            "returncode": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "failed to execute: " + str(exc),
            "seconds": round(time.monotonic() - start, 3),
            "spawn_error": True,
        }


def marker(output, name, pattern=r"\S*"):
    """Return the value of a ``NAME=value`` line printed by the probe, or None."""
    m = re.search(r"^" + re.escape(name) + r"=(" + pattern + r")[ \t\r]*$", output, re.M)
    return m.group(1) if m else None


def fingerprint(output):
    """Compile-time libc fingerprint the probe printed (see tests/self_join.c)."""
    name = marker(output, "SELFJOIN_LIBC")
    if name is None:
        return None
    return {"name": name, "version": marker(output, "SELFJOIN_LIBC_VERSION") or ""}


def classify(result, expect_libc=""):
    """Map one probe execution to a status.

    Only runs that demonstrably reached pthread_join() are classified as libc
    behavior; anything earlier is a launch/setup failure, never a result.
    """
    if result.get("spawn_error"):
        return "run_error"
    output = result["stdout"]
    if marker(output, "SELFJOIN_EDEADLK", r"-?\d+") is None:
        # The probe never printed its first marker: the binary/runtime did not start.
        if result["returncode"] == 0 and not result["timed_out"]:
            return "no_result"
        return "run_error"
    libc = marker(output, "SELFJOIN_LIBC")
    if expect_libc and libc is not None and libc != expect_libc:
        return "libc_mismatch"
    if marker(output, "SELFJOIN_CREATE_RC", r"-?\d+") is not None:
        return "setup_error"
    is_self = marker(output, "SELFJOIN_IS_SELF", r"-?\d+")
    if is_self is None:
        # Started, but never got to the join (e.g. pthread_create hung or crashed).
        return "setup_error"
    if is_self != "1":
        return "invalid_result"
    rc = marker(output, "SELFJOIN_RC", r"-?\d+")
    edeadlk = marker(output, "SELFJOIN_EDEADLK", r"-?\d+")
    if rc is not None:
        rc = int(rc)
        return "edeadlk" if rc == int(edeadlk) else ("returned_zero" if rc == 0 else "other_error")
    if result["timed_out"]:
        return "timeout"
    if result["returncode"] is not None and result["returncode"] < 0:
        return "signal"
    if result["returncode"] != 0:
        return "abnormal_exit"
    return "no_result"


def expected_libc_for(target_id):
    """The ``expect_libc`` fingerprint declared for this target in configs/targets.json."""
    try:
        cfg = json.loads((ROOT / "configs" / "targets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for t in cfg.get("targets", []):
        if t.get("id") == target_id:
            return t.get("expect_libc", "")
    return ""


def run_cases(base_command, timeout, expect_libc, info):
    """Run the main-thread and created-thread cases and record both in ``info``."""
    for case, prefix in (("main", ""), ("thread", "thread_")):
        cmd = base_command + (["thread"] if case == "thread" else [])
        result = run_command(cmd, timeout=timeout)
        info[prefix + "run_command"] = cmd
        info[prefix + "run"] = result
        info[prefix + "status"] = classify(result, expect_libc)
        if "libc_fingerprint" not in info:
            fp = fingerprint(result["stdout"])
            if fp:
                info["libc_fingerprint"] = fp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--id", required=True)
    p.add_argument("--libc", required=True)
    p.add_argument("--kind", choices=("container", "native", "vm", "manual"), default="manual")
    p.add_argument("--cc", default="cc", help="Compiler command, e.g. 'diet gcc'")
    p.add_argument("--cflags", default="")
    p.add_argument("--ldflags", default="")
    p.add_argument("--timeout", type=float, default=3.0, help="Probe timeout in seconds")
    p.add_argument("--runner", default="", help="Runner prefix for a foreign executable, e.g. 'node' or 'wasmtime --wasi threads'")
    p.add_argument("--suffix", default="", help="Executable suffix, e.g. .js or .wasm")
    p.add_argument("--out", required=True)
    p.add_argument("--build-dir", default=None)
    p.add_argument("--expect-libc", default=None,
                   help="Required SELFJOIN_LIBC fingerprint (default: expect_libc for --id in configs/targets.json)")
    args = p.parse_args()
    expect_libc = expected_libc_for(args.id) if args.expect_libc is None else args.expect_libc

    out = pathlib.Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    build = pathlib.Path(args.build_dir).resolve() if args.build_dir else out.parent / "build" / args.id
    build.mkdir(parents=True, exist_ok=True)
    suffix = args.suffix or (".exe" if (os.name == "nt" or sys.platform.startswith("cygwin")) else "")
    if suffix and (not suffix.startswith(".") or any(c in suffix for c in "/\\")):
        p.error("--suffix must be a simple extension such as .js or .wasm")
    executable = build / ("self_join" + suffix)
    compiler = shlex.split(args.cc)
    compile_command = compiler + ["-std=c11", "-O0", "-Wall", "-Wextra", "-pthread"]
    compile_command += shlex.split(args.cflags)
    compile_command += [str(ROOT / "tests" / "self_join.c"), "-o", str(executable)]
    compile_command += shlex.split(args.ldflags)

    info = {
        "schema_version": 1,
        "id": args.id,
        "libc": args.libc,
        "kind": args.kind,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "os_release": "",
        "compiler": args.cc,
        "runner": args.runner or "native",
        "runner_version": command_output(shlex.split(args.runner)[:1] + ["--version"]) if args.runner else "native",
        "compiler_version": command_output(compiler + ["--version"]).splitlines()[:2],
        "host_utility_libc_hint": "",
        "source": "tests/self_join.c",
        "timeout_seconds": args.timeout,
        "compile_command": compile_command,
        "expected_libc": expect_libc,
        "status": "compile_error",
    }
    if pathlib.Path("/etc/os-release").is_file():
        info["os_release"] = pathlib.Path("/etc/os-release").read_text(errors="replace")[:2000]
    if info["system"] == "Linux":
        # This is the libc used by Python/getconf *in the host container*, NOT
        # necessarily the probe's libc (e.g. uClibc-ng static cross-build).
        info["host_utility_libc_hint"] = command_output(["getconf", "GNU_LIBC_VERSION"]).splitlines()[:1]
    info["source_sha256"] = hashlib.sha256((ROOT / "tests/self_join.c").read_bytes()).hexdigest()
    compile_result = run_command(compile_command, timeout=90)
    info["compile"] = compile_result
    if compile_result["timed_out"]:
        info["status"] = "compile_timeout"
    elif compile_result["returncode"] == 0:
        info["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
        run_cmd = shlex.split(args.runner) + [str(executable)] if args.runner else [str(executable)]
        run_cases(run_cmd, args.timeout, expect_libc, info)
    with out.open("w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("{}: main={} thread={} libc={} ({})".format(
        args.id, info["status"], info.get("thread_status", "-"),
        info.get("libc_fingerprint", {}).get("name", "?"), out), flush=True)
    return 0  # Test outcome is data, not CI success/failure.


if __name__ == "__main__":
    sys.exit(main())
