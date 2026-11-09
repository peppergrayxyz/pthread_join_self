#!/usr/bin/env python3
"""Merge per-target JSON artifacts and generate a self-contained GitHub Pages report."""
import argparse
from collections import Counter
import datetime as dt
import html
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

COLORS = {
    "edeadlk": "good", "timeout": "warn", "returned_zero": "bad",
    "other_error": "neutral", "signal": "bad", "abnormal_exit": "bad",
    "compile_error": "neutral", "compile_timeout": "neutral",
    "run_error": "bad", "no_result": "neutral",
    "infrastructure_error": "neutral", "missing": "neutral",
    "invalid_result": "neutral", "libc_mismatch": "neutral", "setup_error": "neutral",
}
DISPLAY = {
    "edeadlk": "EDEADLK", "timeout": "TIMEOUT / HANG", "returned_zero": "RETURNED 0",
    "other_error": "OTHER ERROR", "signal": "TERMINATED BY SIGNAL",
    "abnormal_exit": "ABNORMAL EXIT", "compile_error": "COMPILE FAILED",
    "compile_timeout": "COMPILE TIMEOUT", "run_error": "LAUNCH FAILED",
    "no_result": "NO RESULT MARKER", "infrastructure_error": "INFRASTRUCTURE FAILED",
    "missing": "NO ARTIFACT", "invalid_result": "INVALID RESULT",
    "libc_mismatch": "WRONG LIBC LINKED", "setup_error": "PROBE SETUP FAILED",
}
# Statuses that are a real observation of the libc's self-join behavior.
# Everything not listed here (compile/launch/infra failures, missing or invalid
# artifacts, wrong libc linked) is "no observation" and must never be counted
# alongside them.
OTHER_BEHAVIOR = ("returned_zero", "other_error", "signal", "abnormal_exit")
GROUP_LABELS = {
    "edeadlk": "EDEADLK", "timeout": "Timeout / hang",
    "other_behavior": "Observed: other behavior", "no_observation": "No observation",
}


def group(status):
    if status in ("edeadlk", "timeout"):
        return status
    return "other_behavior" if status in OTHER_BEHAVIOR else "no_observation"


def escape(x):
    return html.escape(str(x), quote=True)


def read_result(path):
    """Parse one result file; raise ValueError unless it is a JSON object."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Result is not a JSON object")
    return data


def load_results(folder, config):
    results = []
    for t in config["targets"]:
        p = folder / (t["id"] + ".json")
        if p.exists():
            try:
                data = read_result(p)
                if data.get("id") != t["id"] or data.get("status") not in COLORS:
                    raise ValueError("Bad ID/status in result")
                if data.get("thread_status") is not None and data["thread_status"] not in COLORS:
                    raise ValueError("Bad thread_status in result")
            except (ValueError, OSError, AttributeError, TypeError) as exc:
                data = {"status": "invalid_result", "failure_log": str(exc)}
        else:
            data = {"status": "missing", "failure_log": "The CI target produced no results artifact. Inspect its Actions job for VM/runner failures."}
        data.update({"id": t["id"], "libc": t["libc"], "os": t["os"], "kind": t["kind"]})
        results.append(data)
    # Also show ad-hoc/local targets. Their IDs are not expected in CI, but
    # hiding them would make local runs appear to have no observations.
    known = {t["id"] for t in config["targets"]}
    if folder.exists():
        for p in sorted(folder.glob("*.json")):
            if p.stem in known:
                continue
            try:
                r = read_result(p)
                if r.get("id") != p.stem or r.get("status") not in COLORS:
                    continue
                if r.get("thread_status") is not None and r["thread_status"] not in COLORS:
                    continue
            except (ValueError, OSError, AttributeError, TypeError):
                continue
            r.setdefault("kind", "manual")
            r.setdefault("libc", p.stem)
            r.setdefault("os", r.get("system", "Unknown"))
            results.append(r)
    return results


def state_badge(status):
    if not status:
        return '<span class="state neutral" title="Not run">—</span>'
    return '<span class="state {}">{}</span>'.format(COLORS.get(status, "neutral"), escape(DISPLAY.get(status, status)))


def linked_libc(r):
    fp = r.get("libc_fingerprint")
    if not isinstance(fp, dict) or not fp.get("name"):
        return ""
    text = "linked: " + " ".join(x for x in (str(fp["name"]), str(fp.get("version", ""))) if x)
    expected = r.get("expected_libc")
    if expected and expected != fp["name"]:
        text += " (expected {})".format(expected)
    return "<small>{}</small>".format(escape(text))


def generate_html(data):
    rows = []
    for r in data["results"]:
        status = r["status"]
        details = json.dumps(r, indent=2, ensure_ascii=False)
        row = """<tr data-group="{group}" data-kind="{kind}">
          <td><strong>{libc}</strong><small>{target}</small>{linked}</td>
          <td>{os}</td><td><span class="type">{kind}</span></td>
          <td>{main}</td><td>{thread}</td>
          <td class="meta">{release} {machine}</td>
          <td><details><summary>Inspect</summary><pre>{details}</pre></details></td>
        </tr>""".format(
            group=group(status), kind=escape(r["kind"]), libc=escape(r["libc"]),
            target=escape(r["id"]), linked=linked_libc(r), os=escape(r["os"]),
            main=state_badge(status), thread=state_badge(r.get("thread_status")),
            release=escape(r.get("release", "")), machine=escape(r.get("machine", "")),
            details=escape(details),
        )
        rows.append(row)
    untouched = "".join("<li><b>{}</b> — {}</li>".format(escape(x["libc"]), escape(x["why"])) for x in data["not_automated"])
    groups = Counter(group(r["status"]) for r in data["results"])
    summary_html = "".join(
        "<div class='stat'><span>{}</span><strong>{}</strong></div>".format(escape(label), count)
        for label, count in [("Targets", len(data["results"]))] + [(GROUP_LABELS[g], groups.get(g, 0)) for g in GROUP_LABELS]
    )
    status_options = "".join('<option value="{}">{}</option>'.format(g, escape(GROUP_LABELS[g])) for g in GROUP_LABELS)
    kind_options = "".join("<option>{}</option>".format(escape(k)) for k in sorted({str(r["kind"]) for r in data["results"]}))
    run_url = data.get("run_url", "")
    # Run URL is constructed by GitHub from known environment variables; validate before linking.
    if run_url.startswith("https://github.com/"):
        run_link = '<a href="{}" rel="noopener noreferrer">View workflow run</a>'.format(escape(run_url))
    else:
        run_link = "Local report"
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Cross-platform pthread self-join behavior matrix">
<title>libc self-join matrix</title>
<style>
:root { color-scheme: light dark; --bg: #f6f7fa; --card: #fff; --text: #172033; --muted: #64748b; --edge: #d9e0e8; --accent: #1763c4; }
@media (prefers-color-scheme: dark) { :root { --bg:#101725; --card:#192337; --text:#e7ebf3; --muted:#a5b4ca; --edge:#324057; --accent:#81b7ff; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text); font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif; }
main { max-width:1280px; margin:0 auto; padding:42px 22px 64px; }
h1 { font-size:clamp(30px,4vw,48px); line-height:1.15; letter-spacing:-.04em; margin:12px 0; }
h2 { margin-top:38px; } p { max-width:850px; color:var(--muted); }
a {color:var(--accent);} .eyebrow { text-transform:uppercase; font-size:12px; font-weight:800; letter-spacing:.16em; color:var(--accent); }
.summary { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin:28px 0; }
.stat { background:var(--card); border:1px solid var(--edge); border-radius:12px; padding:17px; }
.stat span { display:block; color:var(--muted); font-size:12px; text-transform:uppercase; } .stat strong { display:block; font-size:30px; font-variant-numeric:tabular-nums; }
.toolbar { display:flex; flex-wrap:wrap; gap:12px; margin:18px 0; align-items:center; }
input,select { font:inherit; background:var(--card); color:var(--text); padding:10px 12px; border:1px solid var(--edge); border-radius:9px; }
input { flex:1; min-width:210px; } .table-wrap { overflow:auto; background:var(--card); border:1px solid var(--edge); border-radius:12px; }
table { width:100%; border-collapse:collapse; min-width:900px; } th,td { text-align:left; vertical-align:top; padding:14px 12px; border-bottom:1px solid var(--edge); }
th { color:var(--muted); background:var(--card); font-size:11px; text-transform:uppercase; letter-spacing:.07em; }
tr:last-child td { border-bottom:0; } td small { display:block; margin-top:3px; color:var(--muted); font-size:11px; } td.meta { color:var(--muted); font-size:13px; }
.state { display:inline-block; white-space:nowrap; font-size:11px; font-weight:800; letter-spacing:.04em; border:1px solid; border-radius:20px; padding:4px 9px; }
.good { color:#16804e; background:rgba(22,128,78,.09); border-color:rgba(22,128,78,.35); }
.warn { color:#a66b00; background:rgba(202,149,4,.09); border-color:rgba(202,149,4,.35); }
.bad { color:#c43a43; background:rgba(196,58,67,.09); border-color:rgba(196,58,67,.35); }
.neutral { color:var(--muted); background:var(--bg); border-color:var(--edge); }
.type { color:var(--muted); font-size:12px; } details { width:min(400px,40vw); } details summary {cursor:pointer; color:var(--accent);} pre { max-height:300px; max-width:70vw; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font-size:11px; background:var(--bg); padding:12px; border-radius:7px; }
.note { border:1px solid var(--edge); border-radius:10px; padding:14px 17px; background:var(--card); } ul {color:var(--muted);} li {margin:7px 0;} footer {margin-top:32px; color:var(--muted); font-size:12px; }
@media(max-width:650px){.summary{grid-template-columns:repeat(2,minmax(0,1fr));}main{padding:25px 13px;}}
</style></head><body><main>
<div class="eyebrow">C runtime interoperability laboratory</div>
<h1>pthread self-join matrix</h1>
<p>Observed behavior of <code>pthread_join(pthread_self(), NULL)</code> when compiled and executed inside the listed OS or libc environment. Each run is terminated after a watchdog timeout; a timeout is an observation, <b>not</b> a guaranteed deadlock proof. Self-join is undefined behavior under POSIX.</p>
<div class="summary" aria-label="Main-thread results">{stats}</div>
<p><b>Observed: other behavior</b> is a real self-join outcome (returned 0, another error, a signal, or a crash after the probe reached <code>pthread_join</code>). <b>No observation</b> means the target never produced one: build, launch, VM or setup failure, wrong libc linked, or a missing/invalid artifact. Totals count the main-thread case.</p>
<p>Generated <time>{date}</time> · {runlink} · <a href="results.json">Machine-readable JSON</a></p>
<h2>Test results</h2>
<div class="toolbar"><input id="search" aria-label="Search targets" placeholder="Filter by libc, operating system, or target…">
<select id="status" aria-label="Filter by main-thread result"><option value="">All results</option>{status_options}</select>
<select id="kind" aria-label="Filter by environment"><option value="">All environments</option>{kind_options}</select></div>
<div class="table-wrap"><table><thead><tr><th>libc / target</th><th>Operating system</th><th>Environment</th><th>Main thread</th><th>Created thread</th><th>Version / architecture</th><th>Raw evidence</th></tr></thead><tbody id="results">{rows}</tbody></table></div>
<h2>Not yet automated</h2><p>These targets are deliberately shown as untested rather than assigned an assumed result.</p><div class="note"><ul>{untested}</ul></div>
<h2>Methodology</h2><div class="note">The harness builds <code>tests/self_join.c</code> with that target's C compiler, executes it in that target's OS or runtime, and invokes the binary with an external watchdog (normally 3 seconds; Android also uses a 4-second remote timeout), and records its stdout, stderr, return code, compiler command, and OS metadata. Each binary runs twice: self-joining from the initial thread, and from a thread made with <code>pthread_create</code>, because the main thread is special in several runtimes. The probe prints a compile-time libc fingerprint; if it differs from the libc the target is supposed to test, the row is <b>WRONG LIBC LINKED</b>, not a result. Only a run that printed its last marker immediately before <code>pthread_join</code> counts as an observation. A reported <b>EDEADLK</b> means the C program returned the same integer as that target's <code>EDEADLK</code> macro. A build/VM failure is not a pthread behavior result. Inspect raw evidence for each row.</div>
<footer>Portable C experiment · no external analytics or JavaScript dependencies · <a href="https://pubs.opengroup.org/onlinepubs/9799919799/functions/pthread_join.html">POSIX reference</a></footer>
</main><script>
(function(){var search=document.getElementById('search'),status=document.getElementById('status'),kind=document.getElementById('kind');
function filter(){var term=search.value.toLowerCase();document.querySelectorAll('#results tr').forEach(function(tr){var k=tr.dataset.kind;tr.hidden=!(tr.textContent.toLowerCase().includes(term) && (!kind.value || kind.value===k) && (!status.value || status.value===tr.dataset.group));});}
[search,status,kind].forEach(function(e){e.addEventListener('input',filter);});})();
</script></body></html>"""
    return (page.replace("{stats}", summary_html)
                .replace("{date}", escape(data["generated_at"]))
                .replace("{runlink}", run_link)
                .replace("{untested}", untouched)
                .replace("{status_options}", status_options)
                .replace("{kind_options}", kind_options)
                # Last: rows embed raw result text, which must not be scanned for placeholders.
                .replace("{rows}", "\n".join(rows)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default="results")
    p.add_argument("--output", default="site")
    p.add_argument("--only-observed", action="store_true", help="Hide expected CI targets with no artifact (useful locally)")
    args = p.parse_args()
    target_cfg = json.loads((ROOT / "configs" / "targets.json").read_text(encoding="utf-8"))
    results = load_results(pathlib.Path(args.input), target_cfg)
    if args.only_observed:
        results = [r for r in results if r["status"] != "missing"]
    c = Counter(r["status"] for r in results)
    repository = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_url = "https://github.com/{}/actions/runs/{}".format(repository, run_id) if repository and run_id else ""
    data = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "commit": os.getenv("GITHUB_SHA", ""),
        "run_url": run_url,
        "summary": dict(c),
        "results": results,
        "not_automated": target_cfg["not_automated"],
    }
    out = pathlib.Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "index.html").write_text(generate_html(data), encoding="utf-8")
    print("Wrote {}/index.html ({} targets)".format(out, len(results)))
    print("Statuses:", json.dumps(c, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
