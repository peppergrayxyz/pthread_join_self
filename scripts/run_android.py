#!/usr/bin/env python3
"""Compile with Android NDK, execute using adb inside a real Bionic emulator.

The watchdog is both remote (Android toybox timeout) and local (Python). A
remote timeout of 124/137 with the probe's marker counts as a timeout.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import shutil
import sys

from run_case import ROOT, classify, command_output, expected_libc_for, fingerprint, run_command


def find_ndk_clang():
    candidates = []
    for name in ("ANDROID_NDK_HOME", "ANDROID_NDK_ROOT"):
        if os.environ.get(name):
            candidates.append(pathlib.Path(os.environ[name]))
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(name):
            parent = pathlib.Path(os.environ[name]) / "ndk"
            if parent.exists():
                candidates += sorted((p for p in parent.iterdir() if p.is_dir()), reverse=True)
    for root in candidates:
        tool = root / "toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android24-clang"
        if tool.is_file():
            return str(tool)
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--id", default="android-bionic")
    p.add_argument("--out", default="results/android-bionic.json")
    p.add_argument("--timeout", type=float, default=8.0)
    args = p.parse_args()
    out = pathlib.Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    build = out.parent / "build" / args.id
    build.mkdir(parents=True, exist_ok=True)
    binary = build / "self_join_android"
    compiler = find_ndk_clang()
    remote = "/data/local/tmp/libc-selfjoin-" + args.id
    info = {
        "schema_version": 1, "id": args.id, "libc": "Android Bionic",
        "kind": "emulator", "system": "Android", "release": "",
        "machine": "x86_64", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "host": platform.platform(), "compiler": compiler or "NDK compiler not found",
        "source": "tests/self_join.c", "timeout_seconds": args.timeout,
        "expected_libc": expected_libc_for(args.id) or "bionic",
        "status": "infrastructure_error",
    }
    try:
        if not compiler:
            info["failure_log"] = "Cannot locate x86_64-linux-android24-clang under ANDROID_NDK_HOME or ANDROID_HOME/ndk"
            return 0
        info["compiler_version"] = command_output([compiler, "--version"])
        cmd = [compiler, "-std=c11", "-O0", "-Wall", "-Wextra", "-pthread", str(ROOT / "tests/self_join.c"), "-o", str(binary)]
        info["compile_command"] = cmd
        info["compile"] = run_command(cmd, timeout=120)
        if info["compile"]["returncode"] != 0:
            info["status"] = "compile_error"
            return 0
        if not shutil.which("adb"):
            info["failure_log"] = "adb is not in PATH; emulator did not initialize"
            return 0
        info["device_properties"] = {
            "sdk": command_output(["adb", "shell", "getprop", "ro.build.version.sdk"]),
            "abi": command_output(["adb", "shell", "getprop", "ro.product.cpu.abi"]),
            "fingerprint": command_output(["adb", "shell", "getprop", "ro.build.fingerprint"]),
        }
        if "x86_64" not in info["device_properties"]["abi"]:
            info["failure_log"] = "Emulator ABI is not x86_64; refusing to mislabel the target"
            return 0
        pushed = run_command(["adb", "push", str(binary), remote], timeout=45)
        info["adb_push"] = pushed
        if pushed["returncode"] != 0:
            info["failure_log"] = "adb push failed"
            return 0
        chmod = run_command(["adb", "shell", "chmod", "755", remote], timeout=10)
        if chmod["returncode"] != 0:
            info["failure_log"] = "adb chmod failed: " + chmod["stderr"]
            return 0
        # toybox timeout kills the *remote* test, not just the adb client.
        # The Python watchdog protects CI even if toybox timeout is unavailable.
        for case, prefix in (("main", ""), ("thread", "thread_")):
            cmd = ["adb", "shell", "toybox", "timeout", "-s", "KILL", "4", remote]
            if case == "thread":
                cmd.append("thread")
            info[prefix + "run_command"] = cmd
            result = run_command(cmd, timeout=args.timeout)
            if result["returncode"] in (124, 137, -9) and "SELFJOIN_EDEADLK=" in result["stdout"]:
                result["timed_out"] = True
                result["remote_timeout"] = True
            info[prefix + "run"] = result
            info[prefix + "status"] = classify(result, info["expected_libc"])
            if "libc_fingerprint" not in info and fingerprint(result["stdout"]):
                info["libc_fingerprint"] = fingerprint(result["stdout"])
    finally:
        if shutil.which("adb"):
            run_command(["adb", "shell", "rm", "-f", remote], timeout=5)
        out.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("{}: main={} thread={} ({})".format(args.id, info["status"], info.get("thread_status", "-"), out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
