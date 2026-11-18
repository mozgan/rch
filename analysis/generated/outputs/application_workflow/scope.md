# Continuous storage/query workflow

Total wall time is directly measured, not a sum of independent medians. One ordering call per fresh process; refinement off; file and directory fsync included. Input warming/mincore, oracle preparation/load, process startup, and post-run verification are excluded. Queries share naturally cached newly written pages; this is not the separate cold-page experiment.

Prepared XYZ is the starting input; download and source conversion are excluded. This is storage/query processing, not a downstream scientific application. Repeated workflows and nested query prefixes are not independent scenes. Tables show descriptive medians, with no population inference or significance claim. Paired differences use the same repeat number; phase medians need not sum to median total time.

I/O is process-attributed Linux read_bytes/write_bytes, not device telemetry. Writes may include filesystem accounting effects. Missing counters are --, never zero. I/O table units are MiB (1048576 bytes); all values are medians of workflow totals. Peak RSS covers this fresh process through the workflow, including pre-timer workload loading and input-cache setup; CPU snapshots slightly bracket the steady-clock interval.

Bulk outputs are independently checked against materialized result hashes before optional cleanup. Frozen inputs, oracle workloads, source snapshots, metrics, logs, output sizes and checksums remain.
