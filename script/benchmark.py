#!/usr/bin/env python3
"""Local diagnostic benchmarks. No UI/idle CPU, cold-cache, or release qualification claims.

Use --repo and --target-dir for isolated revisions. Both builds use release profile
and cached dependencies. --compare reads two existing results without running work.
Failures and missing metrics are errors, never successful empty measurements.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_CORE = {
    "natural_sort_200_files", "inspect_wav_10s_audio", "inspect_aiff_10s_audio",
    "waveform_preview_2min_wav", "project_first_save_11mb",
    "project_incremental_metadata_save", "project_load_and_extract",
    "audio_edit_triage_cut", "render_transcript_text_1000_segments",
    "render_srt_1000_segments", "natural_sort_200_mixed_unicode", "inspect_wav_odd_metadata",
    "waveform_preview_pcm24_stereo", "waveform_preview_float32_stereo",
    "render_transcript_unicode_variable", "render_srt_unicode_variable",
}


def run_command(cmd, cwd=REPO_ROOT, env=None, check=True):
    start = time.perf_counter()
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=1800)
    duration = (time.perf_counter() - start) * 1000
    if check and proc.returncode:
        raise RuntimeError(f"{cmd} exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc, duration


def stats(values):
    ordered = sorted(values)
    if not ordered or not all(math.isfinite(x) and x >= 0 for x in ordered):
        raise ValueError("Invalid timing samples")
    return {"n": len(values), "median_ms": statistics.median(values),
            "p95_ms": ordered[math.ceil(len(values) * .95) - 1],
            "min_ms": ordered[0], "max_ms": ordered[-1], "samples_ms": values}


def parse_duration_to_us(value):
    match = re.fullmatch(r"([0-9.]+)(ns|µs|us|ms|s)", value)
    if not match:
        raise ValueError(f"Invalid duration: {value}")
    return float(match[1]) * {"ns": .001, "µs": 1, "us": 1, "ms": 1000, "s": 1e6}[match[2]]


def parse_core(output):
    metrics = {}
    for line in output.splitlines():
        if not line.startswith("BENCH:"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 6:
            raise ValueError(f"Malformed benchmark: {line}")
        name = parts[0].removeprefix("BENCH:").strip()
        if name in metrics:
            raise ValueError(f"Duplicate benchmark: {name}")
        metrics[name] = {
            key: parse_duration_to_us(parts[index].split(":", 1)[1].strip())
            for key, index in [("median_us", 1), ("p95_us", 2), ("min_us", 3), ("max_us", 4)]
        }
        metrics[name]["ops_per_sec"] = float(parts[5].split(":", 1)[1])
        if not all(math.isfinite(v) and v >= 0 for v in metrics[name].values()):
            raise ValueError(f"Invalid benchmark: {line}")
    if set(metrics) != EXPECTED_CORE:
        raise ValueError(f"Missing/unexpected core metrics: {set(metrics) ^ EXPECTED_CORE}")
    return metrics


def unknown_startup(proc):
    return proc.returncode == 2 and proc.stderr.startswith("error: unrecognized subcommand 'startup'\n")


def benchmark_engine(engine, repo, env, repetitions):
    def probe(command):
        proc, elapsed = run_command([engine, command], repo, env)
        value = json.loads(proc.stdout)
        if not isinstance(value, (dict, list)) or (isinstance(value, dict) and "error" in value):
            raise ValueError(f"Invalid response for {command}: {value}")
        return value, elapsed
    identity, first = probe("build-info")
    if not identity.get("encap_version") or not identity.get("avid_core"):
        raise ValueError("Missing engine identity")
    result = {"first_invocation_ms": first, "identity": identity}
    legacy = {}
    for key, command in [("providers", "providers"), ("presets", "video-presets"), ("recovery", "load-recovery")]:
        legacy[key], _ = probe(command)
    if not isinstance(legacy["providers"], list) or not isinstance(legacy["presets"], list) or not isinstance(legacy["recovery"], dict) or "project" not in legacy["recovery"]:
        raise ValueError("Invalid legacy startup payload")
    proc, _ = run_command([engine, "startup"], repo, env, check=False)
    unified = not unknown_startup(proc)
    if unified:
        if proc.returncode:
            raise RuntimeError(f"Startup failed: {proc.stdout} {proc.stderr}")
        if json.loads(proc.stdout) != legacy:
            raise ValueError("Unified/legacy startup mismatch")
    timings = {"build_info": [], "legacy_three_processes": []}
    if unified:
        timings["unified_one_process"] = []
    # Interleave legacy/unified within a run. Every response is consumed and checked.
    for _ in range(repetitions):
        value, duration = probe("build-info")
        if value != identity:
            raise ValueError("Build identity changed")
        timings["build_info"].append(duration)
        start = time.perf_counter()
        for key, command in [("providers", "providers"), ("presets", "video-presets"), ("recovery", "load-recovery")]:
            value, _ = probe(command)
            if value != legacy[key]:
                raise ValueError(f"Legacy response changed: {command}")
        timings["legacy_three_processes"].append((time.perf_counter() - start) * 1000)
        if unified:
            value, duration = probe("startup")
            if value != legacy:
                raise ValueError("Startup payload changed")
            timings["unified_one_process"].append(duration)
    result.update({name: stats(values) for name, values in timings.items()})
    # Darwin time -l reports bytes. Linux/GNU time requires a different interface.
    result["build_info_peak_rss_bytes"] = None
    if platform.system() == "Darwin":
        rss = []
        for _ in range(5):
            proc, _ = run_command(["/usr/bin/time", "-l", engine, "build-info"], repo, env)
            if json.loads(proc.stdout) != identity:
                raise ValueError("RSS probe output mismatch")
            match = re.search(r"^\s*(\d+)\s+maximum resident set size\s*$", proc.stderr, re.M)
            if not match:
                raise ValueError("Missing peak RSS")
            rss.append(int(match[1]))
        result["build_info_peak_rss_bytes"] = {"samples": rss, "median": statistics.median(rss)}
    return result


def compare_results(baseline, current):
    if baseline.get("schema") != 2 or current.get("schema") != 2:
        raise ValueError("Historical schema lacks workload/build provenance; do not compare as reproduced evidence")
    for key in ["host", "machine", "rustc", "profile", "benchmark_source_sha256"]:
        if baseline[key] != current[key]:
            raise ValueError(f"Incomparable benchmark provenance: {key}")
    if baseline["workload"] != current["workload"]:
        raise ValueError("Different workloads cannot be compared")
    print("New local measurements (no significance or pass/fail threshold implied):")
    print("| Metric | Before | After | Change |")
    print("|---|---:|---:|---:|")
    pairs = []
    for key in baseline["core"]:
        pairs.append((key + " (µs)", baseline["core"][key]["median_us"], current["core"][key]["median_us"]))
    for key in ["build_info", "legacy_three_processes"]:
        pairs.append((key + " (ms)", baseline["engine"][key]["median_ms"], current["engine"][key]["median_ms"]))
    if "unified_one_process" in current["engine"]:
        pairs.append(("startup legacy → unified (ms)", baseline["engine"]["legacy_three_processes"]["median_ms"], current["engine"]["unified_one_process"]["median_ms"]))
    for name, before, after in pairs:
        print(f"| {name} | {before:.3f} | {after:.3f} | {(after / before - 1) * 100:+.1f}% |")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "build/benchmark_current.json")
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("--repetitions", type=int, default=30)
    args = parser.parse_args()
    if args.compare:
        compare_results(*(json.loads(p.read_text()) for p in args.compare))
        return
    if args.repetitions < 2:
        parser.error("--repetitions must be at least 2")
    repo = args.repo.resolve()
    target = (args.target_dir or repo / "target").resolve()
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_NET_OFFLINE="true")
    workload = {"project_seconds_per_source": env.get("ENCAP_BENCH_PROJECT_SECONDS", "15"),
                "fixture": "pcm16-stereo-48k-pattern-v2", "cache": "warm OS/filesystem; no eviction",
                "waveform": "64 bins x at most 256 first-channel frames; 65536 sample bytes for this fixture",
                "core_scope": "see benchmarks.rs: includes assertions and output destruction; archives include cleanup"}
    # Always rebuild; binary existence is not freshness evidence.
    run_command(["cargo", "build", "--release", "--locked", "--offline", "-p", "encap-engine"], repo, env)
    engine = target / "release" / ("encap-engine.exe" if os.name == "nt" else "encap-engine")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="encap-benchmark-") as scratch:
        env.update(ENCAP_RECOVERY_PATH=str(Path(scratch) / "recovery.json"), ENCAP_SAVE_CACHE_DIR=str(Path(scratch) / "save-cache"))
        engine_results = benchmark_engine(engine, repo, env, args.repetitions)
        proc, _ = run_command(["cargo", "test", "--release", "--locked", "--offline", "-p", "encap-core", "--test", "benchmarks", "--", "--ignored", "--nocapture"], repo, env)
        args.output.with_suffix(".core.log").write_text(proc.stdout + proc.stderr)
        core = parse_core(proc.stdout)
    def command_output(command):
        return run_command(command, repo, env)[0].stdout.strip()
    results = {"schema": 2, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "revision": command_output(["git", "rev-parse", "HEAD"]),
               "dirty_diff_sha256": hashlib.sha256(command_output(["git", "diff", "HEAD"]).encode()).hexdigest(),
               "host": platform.platform(), "machine": platform.machine(),
               "rustc": command_output(["rustc", "-Vv"]), "profile": "workspace release; RUSTFLAGS=" + env.get("RUSTFLAGS", ""),
               "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(), "engine_bytes": engine.stat().st_size,
               "benchmark_source_sha256": hashlib.sha256((repo / "crates/encap-core/tests/benchmarks.rs").read_bytes()).hexdigest(),
               "cpu": command_output(["sysctl", "-n", "machdep.cpu.brand_string"]) if platform.system() == "Darwin" else platform.processor(),
               "logical_cpus": os.cpu_count(),
               "workload": workload, "engine": engine_results, "core": core}
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Validated benchmark results: {args.output}")


if __name__ == "__main__":
    main()
