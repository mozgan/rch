# Linux Performance Counters

RCH uses Linux `perf stat` only for optional cache measurements around the
deterministic block-read probe. Ordering and correctness tests do not require
hardware counters.

## Preflight

Check that `perf` exists and that the selected generic events are available:

```bash
perf --version
perf stat -x, -e cache-references,cache-misses true
```

Successful command execution is not enough: inspect the output for
`<not supported>`, `<not counted>`, and zero-time multiplexed events.

## Kernel Policy

```bash
cat /proc/sys/kernel/perf_event_paranoid
```

The meaning and accepted values are kernel-version dependent. Consult the
kernel's current perf security documentation before changing the setting.
Prefer the least-permissive configuration that grants the required unprivileged
events. Do not make a permanent system-wide change merely to collect optional
counters.

Container execution may additionally need host capabilities or security-policy
changes. Such changes affect the host and are outside the repository's build
contract.

## Fail-Closed Behavior

The experiment runners parse `perf stat -x,` output and require both
`cache-references` and `cache-misses`. Missing tools, denied permission,
unsupported events, parser failure, and uncounted events produce an explicit
status instead of fabricated numeric values.

The status is written to `perf_status.json` and to runtime result rows. Use
cache fields only when `perf_status` is `ok`. A blank or zero count with a
non-ok status is not evidence of a zero miss rate.

## Interpretation

The reported miss rate belongs to `rch_block_read_probe`, not directly to the
ordering call. It depends on CPU microarchitecture, kernel, event mapping,
system load, memory placement, and the probe workload. Compare counters only
under a recorded and controlled environment, and report the exact event names
and `perf` status.
