# Storage-read measurements

Frozen-result validation only; no queries or measured binaries executed.
Arithmetic mean KiB per query execution over all queries and repeats; 1 KiB = 1024 bytes.
Linux /proc/self/io read_bytes differences cover page-file open/header/query/close.
Cache setup and resident directory are excluded; device caches are uncontrolled.
Counters are process-attributed storage reads, not device-controller telemetry.
Read-ahead can exceed logical bytes; missing/incomplete counters are --, never zero.
