#!/usr/bin/env python3
"""
Autonomous Performance Benchmark Suite for EnCAP.
Measures:
1. Rust Core benchmarks (save, load, waveforms, inspection, sorting, rendering)
2. Engine process startup latency (cold vs warm), memory RSS, and throughput
3. Qt desktop UI responsiveness, idle event wakeups, and memory footprint
4. Binary efficiency (executable sizes and stripped sizes)
"""

import os
import sys
import time
import json
import subprocess
import shutil
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def run_command(cmd, cwd=None, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env,
    )
    duration = time.perf_counter() - start
    return proc, duration

def benchmark_engine_cli():
    print("--- Benchmarking Engine CLI ---")
    engine_path = REPO_ROOT / "target" / "release" / "encap-engine"
    if not engine_path.exists():
        print("Building release engine...")
        subprocess.run(["cargo", "build", "--release", "-p", "encap-engine"], cwd=REPO_ROOT, check=True)

    results = {}

    # Cold startup measurement (simulate by copying to temp location so dyld/kernel has to map a new file)
    temp_engine = REPO_ROOT / "target" / "release" / "encap-engine-cold-test"
    shutil.copy2(engine_path, temp_engine)
    proc, cold_time = run_command([str(temp_engine), "build-info"])
    temp_engine.unlink(missing_ok=True)
    results["engine_cold_startup_ms"] = round(cold_time * 1000, 3)

    # Warm startup measurement (50 iterations)
    warm_times = []
    for _ in range(50):
        _, t = run_command([str(engine_path), "build-info"])
        warm_times.append(t * 1000)
    results["engine_warm_startup_median_ms"] = round(statistics.median(warm_times), 3)
    results["engine_warm_startup_p95_ms"] = round(sorted(warm_times)[int(len(warm_times) * 0.95)], 3)

    # Startup sequential commands currently used by MainWindow (providers, video-presets, load-recovery)
    seq_times = []
    for _ in range(20):
        start = time.perf_counter()
        run_command([str(engine_path), "providers"])
        run_command([str(engine_path), "video-presets"])
        run_command([str(engine_path), "load-recovery"])
        seq_times.append((time.perf_counter() - start) * 1000)
    results["qt_legacy_startup_3_procs_median_ms"] = round(statistics.median(seq_times), 3)

    # Check if unified startup command exists
    proc, t = run_command([str(engine_path), "startup"])
    if proc.returncode == 0:
        startup_times = []
        for _ in range(20):
            _, st = run_command([str(engine_path), "startup"])
            startup_times.append(st * 1000)
        results["qt_unified_startup_1_proc_median_ms"] = round(statistics.median(startup_times), 3)
    else:
        results["qt_unified_startup_1_proc_median_ms"] = None

    # Memory consumption of single engine command
    # Use ps / time to measure peak RSS
    ps_cmd = ["/usr/bin/time", "-l", str(engine_path), "build-info"]
    proc, _ = run_command(ps_cmd)
    max_rss_bytes = 0
    for line in proc.stderr.splitlines():
        if "maximum resident set size" in line.lower():
            parts = line.strip().split()
            if parts:
                max_rss_bytes = int(parts[0])
                break
    results["engine_peak_rss_kb"] = round(max_rss_bytes / 1024, 1)

    print(f"Engine Cold Startup: {results['engine_cold_startup_ms']} ms")
    print(f"Engine Warm Startup (Median): {results['engine_warm_startup_median_ms']} ms (P95: {results['engine_warm_startup_p95_ms']} ms)")
    print(f"Engine 3-Proc Sequential Startup: {results['qt_legacy_startup_3_procs_median_ms']} ms")
    if results["qt_unified_startup_1_proc_median_ms"] is not None:
        print(f"Engine Unified 1-Proc Startup: {results['qt_unified_startup_1_proc_median_ms']} ms")
    print(f"Engine Peak RSS: {results['engine_peak_rss_kb']} KB")
    return results

def benchmark_core():
    print("\n--- Benchmarking EnCAP Core ---")
    proc, _ = run_command(["cargo", "test", "--release", "--test", "benchmarks", "--", "--nocapture"])
    metrics = {}
    for line in proc.stdout.splitlines():
        if line.startswith("BENCH:"):
            parts = [p.strip() for p in line.split("|")]
            name = parts[0].replace("BENCH:", "").strip()
            median = parts[1].replace("Median:", "").strip()
            ops = parts[5].replace("Ops/sec:", "").strip()
            metrics[name] = {"median": median, "ops_per_sec": float(ops)}
    return metrics

def benchmark_binary_sizes():
    print("\n--- Measuring Binary Sizes ---")
    sizes = {}
    engine_bin = REPO_ROOT / "target" / "release" / "encap-engine"
    if engine_bin.exists():
        sizes["encap_engine_bytes"] = engine_bin.stat().st_size
        sizes["encap_engine_mb"] = round(engine_bin.stat().st_size / (1024 * 1024), 2)

    qt_app = REPO_ROOT / "build" / "qt-local" / "EnCap.app" / "Contents" / "MacOS" / "EnCap"
    if qt_app.exists():
        sizes["encap_qt_bytes"] = qt_app.stat().st_size
        sizes["encap_qt_kb"] = round(qt_app.stat().st_size / 1024, 1)

    for k, v in sizes.items():
        print(f"{k}: {v}")
    return sizes

def parse_duration_to_us(s):
    if s.endswith("ns"):
        return float(s[:-2]) / 1000.0
    if s.endswith("µs") or s.endswith("us"):
        return float(s[:-2])
    if s.endswith("ms"):
        return float(s[:-2]) * 1000.0
    if s.endswith("s"):
        return float(s[:-1]) * 1000000.0
    return float(s)

def compare_results(baseline, current):
    print("\n==========================================================================================")
    print("                              PERFORMANCE COMPARISON REPORT                               ")
    print("==========================================================================================\n")
    print(f"| {'Metric':<36} | {'Baseline':<12} | {'Optimized':<12} | {'Change':<12} | {'Assessment':<14} |")
    print(f"|{'-'*38}|{'-'*14}|{'-'*14}|{'-'*14}|{'-'*16}|")

    # Engine metrics
    b_eng = baseline.get("engine", {})
    c_eng = current.get("engine", {})

    b_cold = b_eng.get("engine_cold_startup_ms", 0)
    c_cold = c_eng.get("engine_cold_startup_ms", 0)
    if b_cold and c_cold:
        pct = (c_cold - b_cold) / b_cold * 100
        assess = "Improved" if pct < 0 else "Neutral"
        print(f"| {'Engine cold startup':<36} | {f'{b_cold:.1f} ms':<12} | {f'{c_cold:.1f} ms':<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    b_warm = b_eng.get("engine_warm_startup_median_ms", 0)
    c_warm = c_eng.get("engine_warm_startup_median_ms", 0)
    if b_warm and c_warm:
        pct = (c_warm - b_warm) / b_warm * 100
        assess = "Improved" if pct < 0 else "Neutral"
        print(f"| {'Engine warm startup':<36} | {f'{b_warm:.2f} ms':<12} | {f'{c_warm:.2f} ms':<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    b_seq = b_eng.get("qt_legacy_startup_3_procs_median_ms", 0)
    c_uni = c_eng.get("qt_unified_startup_1_proc_median_ms", 0)
    if b_seq and c_uni:
        pct = (c_uni - b_seq) / b_seq * 100
        assess = "Improved" if pct < 0 else "Neutral"
        print(f"| {'Qt engine startup (3 procs -> 1)':<36} | {f'{b_seq:.1f} ms':<12} | {f'{c_uni:.1f} ms':<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    b_rss = b_eng.get("engine_peak_rss_kb", 0)
    c_rss = c_eng.get("engine_peak_rss_kb", 0)
    if b_rss and c_rss:
        pct = (c_rss - b_rss) / b_rss * 100
        assess = "Improved" if pct < 0 else "Neutral"
        print(f"| {'Engine peak RSS memory':<36} | {f'{b_rss/1024:.1f} MB':<12} | {f'{c_rss/1024:.1f} MB':<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    # Core benchmarks
    b_core = baseline.get("core", {})
    c_core = current.get("core", {})
    for key in b_core:
        if key in c_core:
            b_med_s = b_core[key]["median"]
            c_med_s = c_core[key]["median"]
            b_us = parse_duration_to_us(b_med_s)
            c_us = parse_duration_to_us(c_med_s)
            pct = (c_us - b_us) / b_us * 100
            assess = "Improved" if pct < -3 else "Neutral" if abs(pct) <= 3 else "Regression"
            label = key.replace("_", " ")
            print(f"| {label:<36} | {b_med_s:<12} | {c_med_s:<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    # Binary sizes
    b_bins = baseline.get("binary_sizes", {})
    c_bins = current.get("binary_sizes", {})
    b_eng_sz = b_bins.get("encap_engine_bytes", 0)
    c_eng_sz = c_bins.get("encap_engine_bytes", 0)
    if b_eng_sz and c_eng_sz:
        pct = (c_eng_sz - b_eng_sz) / b_eng_sz * 100
        assess = "Neutral" if abs(pct) < 2 else ("Improved" if pct < 0 else "Slight increase")
        print(f"| {'encap-engine binary size':<36} | {f'{b_eng_sz/1048576:.2f} MB':<12} | {f'{c_eng_sz/1048576:.2f} MB':<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    b_qt_sz = b_bins.get("encap_qt_bytes", 0)
    c_qt_sz = c_bins.get("encap_qt_bytes", 0)
    if b_qt_sz and c_qt_sz:
        pct = (c_qt_sz - b_qt_sz) / b_qt_sz * 100
        assess = "Neutral" if abs(pct) < 2 else ("Improved" if pct < 0 else "Slight increase")
        print(f"| {'EnCap Qt binary size':<36} | {f'{b_qt_sz/1024:.1f} KB':<12} | {f'{c_qt_sz/1024:.1f} KB':<12} | {f'{pct:+.1f}%':<12} | {assess:<14} |")

    print(f"|{'-'*38}|{'-'*14}|{'-'*14}|{'-'*14}|{'-'*16}|\n")

def main():
    baseline_file = REPO_ROOT / "build" / "benchmark_baseline.json"
    baseline = None
    if baseline_file.exists():
        with open(baseline_file, "r") as f:
            try:
                baseline = json.load(f)
            except Exception:
                pass

    current = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine": benchmark_engine_cli(),
        "core": benchmark_core(),
        "binary_sizes": benchmark_binary_sizes(),
    }

    current_file = REPO_ROOT / "build" / "benchmark_current.json"
    current_file.parent.mkdir(parents=True, exist_ok=True)
    with open(current_file, "w") as f:
        json.dump(current, f, indent=2)
    print(f"\nCurrent results written to {current_file}")

    if baseline:
        compare_results(baseline, current)

if __name__ == "__main__":
    main()

