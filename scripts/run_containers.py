#!/usr/bin/env python3
"""Build and execute all declared Linux Docker/Podman libc targets."""
import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def call(cmd, seconds=900):
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=seconds)
        return p.returncode, p.stdout.decode("utf-8", "replace")[-12000:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def record_failure(target, out, step, message):
    data = {
        "schema_version": 1, "id": target["id"], "libc": target["libc"],
        "kind": "container", "system": "Linux", "status": "infrastructure_error",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "failure_step": step, "failure_log": message,
    }
    (out / (target["id"] + ".json")).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", default="docker", help="docker or podman")
    ap.add_argument("--out", default="results")
    ap.add_argument("--targets", default="", help="Comma-separated subset of container IDs")
    ap.add_argument("--host-user", choices=("auto", "yes", "no"), default="auto",
                    help="Run probes as the invoking UID/GID so results/ is not root-owned "
                         "(auto: yes for docker; rootless podman already maps root to you)")
    args = ap.parse_args()
    host_user = hasattr(os, "getuid") and (
        args.host_user == "yes" or (args.host_user == "auto" and "docker" in pathlib.Path(args.engine).name))
    out = pathlib.Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = [t for t in json.loads((ROOT / "configs" / "targets.json").read_text())["targets"] if t["kind"] == "container"]
    if args.targets:
        ids = set(args.targets.split(","))
        targets = [t for t in targets if t["id"] in ids]
    if not shutil.which(args.engine):
        for target in targets:
            record_failure(target, out, "engine", args.engine + " not found")
        print(args.engine + " not found; recorded infrastructure errors", file=sys.stderr)
        return 0

    for t in targets:
        image = "libc-selfjoin-matrix-" + t["id"].replace("_", "-") + ":local"
        print("Building", t["id"], flush=True)
        build_cmd = [args.engine, "build"]
        if t.get("platform"):
            build_cmd += ["--platform", t["platform"]]
        build_cmd += ["-f", t["dockerfile"], "-t", image, "."]
        rc, log = call(build_cmd)
        if rc:
            record_failure(t, out, "docker build", log)
            print(t["id"], "build failed", flush=True)
            continue
        cmd = [
            args.engine, "run", "--rm", "--network", "none",
            "-v", str(ROOT) + ":/workspace:ro",
            "-v", str(out) + ":/out",
            # HOME must be writable for tools that cache under it (APE loader, wasmtime).
            "-e", "HOME=/tmp",
        ] + (["--user", "{}:{}".format(os.getuid(), os.getgid())] if host_user else []) + [
            "-w", "/workspace", image,
            "python3", "scripts/run_case.py", "--id", t["id"], "--kind", "container",
            "--libc", t["libc"], "--cc", t.get("cc", "cc"),
            "--out", "/out/" + t["id"] + ".json",
            "--build-dir", "/out/build/" + t["id"],
        ]
        for flag in ("cflags", "ldflags", "runner", "suffix"):
            if t.get(flag):
                cmd.append("--" + flag + "=" + t[flag])
        if t.get("platform"):
            cmd[2:2] = ["--platform", t["platform"]]
        rc, log = call(cmd, seconds=240)
        print(log, flush=True)
        if rc or not (out / (t["id"] + ".json")).exists():
            record_failure(t, out, "docker run", log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
