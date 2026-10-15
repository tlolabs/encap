# Performance evidence

The October 14 performance report in commit
`cd973d9c6016741129c78e875aa6e47bccbf4a87` contained useful optimizations, several
correctness defects, and unsupported measurement claims. Its percentages are
historical observations, not verified application-wide guarantees.

The [independent remediation audit](audits/performance-remediation.md) tracks every
original item, implemented fixes, exact checks, new measurements, uncertainty,
and deferred work. [Retained evidence](audits/performance-evidence/) includes
validated before/after JSON and core timing logs.

On the local Apple M5 Max, three paired Release runs against the actual
pre-optimization revision measured these medians of run-medians:

| Workload | Before | After |
|---|---:|---:|
| Equivalent startup data: three legacy processes → one | 17.96 ms | 8.56 ms |
| Bounded first-channel PCM16 thumbnail from a two-minute file | 75.04 µs | 51.46 µs |
| Full save, four sources totaling 10.99 MiB | 17.95 ms | 13.03 ms |
| Load, extract, verify bytes and clean scratch, same project | 9.84 ms | 5.20 ms |
| SRT, 1,000 segments | 175.71 µs | 108.08 µs |

These are **new local measurements**, with warm filesystem caches and synthetic
fixtures. They do not confirm the original percentages or isolate each optimization
from subsequent correctness fixes. The audit provides repetition counts, P95,
min/max, run variability, supported-format variants and small/large archive results.
Small archive saves and incremental saves do not show a universal improvement.

Waveform generation samples at most 64 windows of 256 frames, not every sample
in the file; it computes normalized peaks, not RMS. Build-info process timing,
aggregated startup IPC, app readiness, process RSS, app RSS, idle CPU, wakeups,
and paints are separate metrics. Only the first two and build-info RSS were
measured here. Timer intervals imply a nominal 10 Hz → 1 Hz reduction for the
clock timer; CPU/power/paint reductions were not measured. The earlier conflicting
Qt suite durations (0.21 and 0.40 seconds) lack run evidence and are withdrawn as
application-performance evidence. Test duration is validation cost.

The benchmark is opt-in and diagnostic:

```sh
python3 script/benchmark.py --target-dir build/performance-remediation/after-target --output build/performance-remediation/current.json
python3 script/benchmark.py --compare build/performance-remediation/before-1.json build/performance-remediation/after-1.json
```

See the audit for isolated baseline setup. The harness rebuilds with cached,
locked Release dependencies, validates command status/JSON and benchmark output,
and rejects incomparable provenance. It does not impose timing thresholds or
new CI/release gates. Rayon, SIMD, dirty-rectangle painting and memory mapping
remain deferred because current evidence does not justify implementing them.
