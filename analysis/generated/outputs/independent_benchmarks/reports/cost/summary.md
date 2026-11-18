# Stage 2 cost decomposition summary

Each cell aggregates 10 independently generated clouds (2 geometries × 5 seeds). Values are medians across cloud-level medians of five in-process timing repeats; parentheses show the interquartile range. Units are milliseconds. `frame` excludes measured DetMCD pilot/estimation time. `total` is end-to-end ordering wall time, including diagnostics and hashing.

| Refinement | Algorithm | N | Total | Robust | Frame | Domain/bits | Encode | Key sort | Diagnostics | Refinement |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all | A5_pca_compact_hilbert | 1024 | 9.925 (8.908–10.037) | 0.000 (0.000–0.000) | 0.006 (0.006–0.006) | 0.005 (0.005–0.005) | 0.353 (0.348–0.361) | 0.044 (0.041–0.046) | 0.379 (0.377–0.381) | 9.070 (8.025–9.151) |
| all | A5_pca_compact_hilbert | 4096 | 46.553 (46.477–46.772) | 0.000 (0.000–0.000) | 0.021 (0.021–0.022) | 0.021 (0.020–0.021) | 1.427 (1.398–1.472) | 0.237 (0.228–0.246) | 1.605 (1.589–1.614) | 42.890 (42.833–43.142) |
| all | A5_pca_compact_hilbert | 16384 | 210.081 (209.575–211.875) | 0.000 (0.000–0.000) | 0.083 (0.083–0.084) | 0.081 (0.081–0.082) | 5.852 (5.715–5.964) | 1.119 (1.077–1.162) | 6.508 (6.474–6.559) | 195.049 (194.484–196.766) |
| all | A6_rch | 1024 | 14.790 (14.454–15.911) | 4.478 (4.320–4.950) | 0.004 (0.004–0.004) | 0.005 (0.005–0.005) | 0.359 (0.352–0.366) | 0.047 (0.046–0.048) | 0.389 (0.387–0.391) | 9.143 (9.066–10.322) |
| all | A6_rch | 4096 | 74.331 (73.147–78.285) | 25.777 (24.345–26.961) | 0.026 (0.026–0.027) | 0.021 (0.021–0.021) | 1.434 (1.394–1.480) | 0.236 (0.227–0.246) | 1.601 (1.595–1.604) | 42.891 (42.736–48.846) |
| all | A6_rch | 16384 | 332.540 (319.280–355.413) | 121.540 (114.471–151.475) | 0.119 (0.116–0.121) | 0.081 (0.081–0.082) | 5.803 (5.756–6.025) | 1.098 (1.076–1.160) | 6.537 (6.509–6.593) | 195.551 (192.735–197.083) |
| off | A5_pca_compact_hilbert | 1024 | 0.865 (0.860–0.868) | 0.000 (0.000–0.000) | 0.006 (0.006–0.006) | 0.005 (0.005–0.005) | 0.357 (0.350–0.359) | 0.041 (0.041–0.044) | 0.376 (0.375–0.376) | 0.000 (0.000–0.000) |
| off | A5_pca_compact_hilbert | 4096 | 3.611 (3.592–3.658) | 0.000 (0.000–0.000) | 0.021 (0.021–0.021) | 0.020 (0.020–0.021) | 1.418 (1.397–1.460) | 0.235 (0.228–0.243) | 1.599 (1.592–1.606) | 0.000 (0.000–0.000) |
| off | A5_pca_compact_hilbert | 16384 | 14.997 (14.927–15.120) | 0.000 (0.000–0.000) | 0.083 (0.083–0.084) | 0.081 (0.080–0.081) | 5.855 (5.773–5.945) | 1.117 (1.091–1.164) | 6.559 (6.534–6.574) | 0.000 (0.000–0.000) |
| off | A6_rch | 1024 | 5.362 (5.211–5.826) | 4.492 (4.325–4.953) | 0.004 (0.004–0.004) | 0.005 (0.005–0.005) | 0.362 (0.348–0.367) | 0.047 (0.045–0.048) | 0.388 (0.385–0.391) | 0.000 (0.000–0.000) |
| off | A6_rch | 4096 | 29.688 (27.928–30.723) | 26.010 (24.255–27.043) | 0.026 (0.026–0.026) | 0.021 (0.020–0.021) | 1.420 (1.407–1.466) | 0.237 (0.229–0.246) | 1.602 (1.594–1.619) | 0.000 (0.000–0.000) |
| off | A6_rch | 16384 | 136.736 (129.904–166.224) | 121.448 (115.077–150.968) | 0.117 (0.115–0.118) | 0.082 (0.081–0.082) | 5.910 (5.745–6.054) | 1.118 (1.074–1.160) | 6.559 (6.541–6.581) | 0.000 (0.000–0.000) |

Nested estimator subphases (pilot, guard, starts, concentration, finalization, remainder) are reported separately in the CSV; never add them again to the top-level robust total. Old inputs lacking subphases have empty cells, not fabricated zeros. The estimator implementation applies consistency/cutoff finalization; no unimplemented reweighting phase is claimed.

Q1/Q3 are empirical 25th/75th percentiles over the 10 independent clouds. The separately aggregated phase medians need not sum to the total median. The unassigned wall-time remainder includes input validation, allocations, output hashing, and timer/dispatch overhead.
