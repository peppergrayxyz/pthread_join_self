"""Offline smoke tests: python -m unittest discover -s unit_tests -v"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OBSERVED = ("edeadlk", "timeout", "other_error", "returned_zero", "signal", "abnormal_exit")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RunnerTests(unittest.TestCase):
    def test_classify_edeadlk(self):
        m = load_module("run_case", "scripts/run_case.py")
        started = "SELFJOIN_LIBC=glibc\nSELFJOIN_EDEADLK=35\nSELFJOIN_IS_SELF=1\n"
        self.assertEqual(m.classify({"stdout": started + "SELFJOIN_RC=35\n", "returncode": 0, "timed_out": False}), "edeadlk")
        self.assertEqual(m.classify({"stdout": started, "returncode": None, "timed_out": True}), "timeout")
        self.assertEqual(m.classify({"stdout": started, "returncode": -6, "timed_out": False}), "signal")
        self.assertEqual(m.classify({"stdout": started, "returncode": 3221225477, "timed_out": False}), "abnormal_exit")
        self.assertEqual(m.classify({"stdout": started + "SELFJOIN_RC=1\n", "returncode": 0, "timed_out": False}), "other_error")
        self.assertEqual(m.classify({"stdout": started + "SELFJOIN_RC=0\n", "returncode": 0, "timed_out": False}), "returned_zero")

    def test_classify_never_reached_join_is_not_behavior(self):
        m = load_module("run_case", "scripts/run_case.py")
        # Crashed/hung/failed before printing anything: a launch failure, not a libc result.
        self.assertEqual(m.classify({"stdout": "", "returncode": -6, "timed_out": False}), "run_error")
        self.assertEqual(m.classify({"stdout": "", "returncode": None, "timed_out": True}), "run_error")
        self.assertEqual(m.classify({"stdout": "", "returncode": None, "timed_out": False, "spawn_error": True}), "run_error")
        # Started, but pthread_create failed or the worker never reached the join.
        pre = "SELFJOIN_LIBC=glibc\nSELFJOIN_EDEADLK=35\n"
        self.assertEqual(m.classify({"stdout": pre + "SELFJOIN_CREATE_RC=11\n", "returncode": 2, "timed_out": False}), "setup_error")
        self.assertEqual(m.classify({"stdout": pre, "returncode": None, "timed_out": True}), "setup_error")

    def test_classify_wrong_libc_and_bad_self(self):
        m = load_module("run_case", "scripts/run_case.py")
        out = "SELFJOIN_LIBC=glibc\nSELFJOIN_EDEADLK=35\nSELFJOIN_IS_SELF=1\nSELFJOIN_RC=35\n"
        self.assertEqual(m.classify({"stdout": out, "returncode": 0, "timed_out": False}, "uclibc-ng"), "libc_mismatch")
        self.assertEqual(m.classify({"stdout": out, "returncode": 0, "timed_out": False}, "glibc"), "edeadlk")
        bad = out.replace("SELFJOIN_IS_SELF=1", "SELFJOIN_IS_SELF=0")
        self.assertEqual(m.classify({"stdout": bad, "returncode": 0, "timed_out": False}), "invalid_result")
        self.assertEqual(m.fingerprint("SELFJOIN_LIBC=glibc\r\nSELFJOIN_LIBC_VERSION=2.41\r\n"), {"name": "glibc", "version": "2.41"})

    def test_every_target_declares_expected_libc(self):
        cfg = json.loads((ROOT / "configs/targets.json").read_text())
        probe = (ROOT / "tests/self_join.c").read_text()
        for t in cfg["targets"]:
            self.assertTrue(t.get("expect_libc"), t["id"])
            self.assertIn('"{}"'.format(t["expect_libc"]), probe, t["id"])

    def test_report_without_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            input_dir = pathlib.Path(d, "empty")
            output_dir = pathlib.Path(d, "site")
            p = subprocess.run([sys.executable, str(ROOT / "scripts/report.py"), "--input", str(input_dir), "--output", str(output_dir)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads((output_dir / "results.json").read_text())
            self.assertEqual(len(data["results"]), len(json.loads((ROOT / "configs/targets.json").read_text())["targets"]))
            self.assertTrue(all(r["status"] == "missing" for r in data["results"]))
            self.assertIn("NO ARTIFACT", (output_dir / "index.html").read_text())

    def test_extra_local_result(self):
        with tempfile.TemporaryDirectory() as d:
            inp = pathlib.Path(d, "results")
            inp.mkdir()
            (inp / "local-test.json").write_text(json.dumps({"id": "local-test", "status": "edeadlk", "libc": "local glibc", "system": "Linux"}))
            out = pathlib.Path(d, "site")
            p = subprocess.run([sys.executable, str(ROOT / "scripts/report.py"), "--input", str(inp), "--output", str(out), "--only-observed"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads((out / "results.json").read_text())
            self.assertEqual(len(data["results"]), 1)
            self.assertEqual(data["results"][0]["status"], "edeadlk")

    def run_report(self, results):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        inp = pathlib.Path(d, "results")
        inp.mkdir()
        for name, content in results.items():
            (inp / (name + ".json")).write_text(content if isinstance(content, str) else json.dumps(content))
        out = pathlib.Path(d, "site")
        p = subprocess.run([sys.executable, str(ROOT / "scripts/report.py"), "--input", str(inp), "--output", str(out)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads((out / "results.json").read_text()), (out / "index.html").read_text()

    def test_report_separates_behavior_from_no_observation(self):
        data, page = self.run_report({
            "linux-glibc": {"id": "linux-glibc", "status": "returned_zero"},
            "linux-musl": {"id": "linux-musl", "status": "signal"},
        })
        report = load_module("report", "scripts/report.py")
        groups = __import__("collections").Counter(report.group(r["status"]) for r in data["results"])
        self.assertEqual(groups["other_behavior"], 2)
        self.assertEqual(groups["no_observation"], len(data["results"]) - 2)
        self.assertIn("<span>Observed: other behavior</span><strong>2</strong>", page)
        self.assertEqual(page.count('data-group="other_behavior"'), 2)

    def test_report_survives_non_object_json(self):
        data, _ = self.run_report({"linux-glibc": "[1]", "linux-musl": "null", "local-extra": "[1]"})
        by_id = {r["id"]: r for r in data["results"]}
        self.assertEqual(by_id["linux-glibc"]["status"], "invalid_result")
        self.assertEqual(by_id["linux-musl"]["status"], "invalid_result")
        self.assertNotIn("local-extra", by_id)

    def test_target_config_has_no_duplicate_ids_and_container_files_exist(self):
        cfg = json.loads((ROOT / "configs/targets.json").read_text())
        ids = [x["id"] for x in cfg["targets"]]
        self.assertEqual(len(ids), len(set(ids)))
        for target in cfg["targets"]:
            if target["kind"] == "container":
                self.assertTrue((ROOT / target["dockerfile"]).is_file(), target["id"])
        # Every declared non-container target is wired to the Actions workflow.
        workflow = (ROOT / ".github/workflows/selfjoin.yml").read_text()
        for target in cfg["targets"]:
            if target["kind"] != "container":
                self.assertIn(target["id"], workflow, target["id"])

    def test_runner_and_suffix_if_compiler_available(self):
        import shutil
        if not shutil.which("cc") or not shutil.which("env") or sys.platform == "win32":
            self.skipTest("No POSIX C compiler and env runner")
        with tempfile.TemporaryDirectory() as d:
            outfile = str(pathlib.Path(d, "runner.json"))
            p = subprocess.run([sys.executable, str(ROOT / "scripts/run_case.py"),
                                "--id", "runner-test", "--libc", "local",
                                "--runner=env", "--suffix=.test", "--out", outfile],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(pathlib.Path(outfile).read_text())
            self.assertEqual(data["compile"]["returncode"], 0)
            # Any genuine observation is fine: the host's libc decides which one.
            self.assertIn(data["status"], OBSERVED)
            self.assertIn(data["thread_status"], OBSERVED)
            self.assertEqual(data["run_command"][0], "env")
            self.assertTrue(data["run_command"][1].endswith(".test"))
            self.assertEqual(data["thread_run_command"][-1], "thread")

    def test_android_no_ndk_writes_infrastructure_error(self):
        # Never claim a Bionic result when no Android NDK/emulator is available.
        with tempfile.TemporaryDirectory() as d:
            outfile = str(pathlib.Path(d, "android-bionic.json"))
            env = {k: v for k, v in __import__("os").environ.items()
                   if k not in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_NDK_HOME", "ANDROID_NDK_ROOT")}
            p = subprocess.run([sys.executable, str(ROOT / "scripts/run_android.py"),
                                "--out", outfile], env=env,
                               capture_output=True, text=True, timeout=15)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            data = json.loads(pathlib.Path(outfile).read_text())
            self.assertEqual(data["status"], "infrastructure_error")

    def test_real_compiler_if_available(self):
        import shutil
        if not shutil.which("cc"):
            self.skipTest("No C compiler installed")
        with tempfile.TemporaryDirectory() as d:
            outfile = str(pathlib.Path(d, "probe.json"))
            p = subprocess.run([sys.executable, str(ROOT / "scripts/run_case.py"), "--id", "smoke", "--libc", "local", "--timeout", "1", "--out", outfile], capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            data = json.loads(pathlib.Path(outfile).read_text())
            self.assertIn(data["status"], OBSERVED)
            self.assertEqual(data["compile"]["returncode"], 0, data["compile"])


if __name__ == "__main__":
    unittest.main()
