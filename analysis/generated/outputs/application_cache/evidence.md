# File page-cache measurements

Verified cold/warm file-page residency; device-controller caches are not controlled.
Directory resident; timing includes open/header/query/close. Values are means of
per-query median times across repeats, without population confidence intervals.

The I/O table reports arithmetic mean bytes per measured query execution across all queries and repeats (KiB = 1024 bytes). Logical bytes count page reads. Storage reads are process-attributed Linux /proc/self/io read_bytes deltas around open/header/query/close, not device-controller telemetry. Cache preparation and the resident directory are excluded. Missing or incomplete OS counters are shown as --, never zero. Cold reads may include filesystem read-ahead; warm reads may be zero.
