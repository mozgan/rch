# Build and experiment workflows

Run `make help` for the maintained entry points. The Makefile follows a dependency
pyramid: environment and maintenance → artifact-independent builds/tests → other
compiler presets → measurements → artifact generation and integration checks.

## Local development

```sh
make venv
make build
make test
```

`test` runs the debug suite without experiment artifacts, then checks the developer
CLIs. Use the narrower targets or call CTest directly after building:

```sh
make test-property
make test-oracle
ctest --test-dir build/debug --output-on-failure -R application_workflow_python
make test-cli
make examples
```

`examples` builds the maintained basic example; `example-basic` also runs it.
`release` builds the `release` preset. Use `make release-gcc` for GCC and
`make test-release RELEASE_TEST_PRESET=release-gcc` for its artifact-independent tests.
Sanitizer targets (`asan`,
`ubsan`, `tsan`, `fuzz`) build and test their own presets. `coverage`, `repro`
and `repro-smoke` remain available; `test-fuzz-soak` is a separate long run.

## Measurements

`bench-cpp` prepares the shared benchmark binaries. `cgal-build` builds and
smoke-tests the external adapter using the user-local `CGAL_DIR`. `real-data`
prepares the pinned Stanford meshes, the USGS LAZ tile and three NOAA COPC files.

`bench-synthetic`, `bench-real`, `bench-independent` and `bench-cgal` can run
separately. `bench-independent` includes independent sampling, controlled frame
ablations, clamping analysis, timing decomposition and the PCA-Hilbert control.
Its output root is `experiments/outputs/independent_benchmarks`; its inventory is
`benchmark_manifest.json`. `analyze-independent` reanalyzes that existing data.
`bench-micro-run` builds and runs the micro-benchmarks; tune `BENCH_MICRO_TIME` as needed.

`bench` runs the ordering, component, and application experiments sequentially, records
CTest results, renders artifacts and runs `test-integration`. It includes the full
application/tree/database/page-cache workloads.

## Application queries and artifacts

`app-query-smoke` runs four correctness windows per dataset. `app-query` runs
the full seven-dataset, seven-layout, 256-query, five-repeat workload and then
analyzes it. `app-query-analysis` validates and reanalyzes existing query results.
Each new query run needs an unused `APPLICATION_QUERY_OUTPUT_DIR` (or
`APPLICATION_QUERY_SMOKE_DIR` for a smoke run).

Application, tree and DBMS workflows share `APPLICATION_QUERY_OUTPUT_DIR`,
which defaults to `experiments/outputs/application_query/full_benchmark`.
Their readers use this same source; there is no separate tree/DBMS source
override or automatic selection of an older run. Consumer source snapshots
must match the shared application manifest exactly. Changed source code or
a replaced application run requires regenerating the affected measurements.
The application matrix includes C0 controls and distinct C2/C3/C4 RCH layouts;
tree and DBMS comparisons consume its Hilbert and RCH C0 controls.
A single source does not make those C0 controls native C3 experiments.

`paper-artifacts` reads existing measurements and generates tables, figures and
provenance snapshots, including a page-cache latency figure/table when that study
is present. It never launches new measurements. `test-integration`
checks input/artifact presence, runs artifact coverage tests and verifies query
artifact checksums. `paper-pdf` is a separate optional document build; see
[manuscript build](#optional-manuscript-build).

The continuous storage/query workflow is included in `bench-extended` and
therefore in `bench` and `all-targets`. It measures read, one ordering call,
storage preparation, 256/512/1024 queries, result materialization, and file
synchronization in one interval. It also has a standalone
`bench-application-workflow` target. See [application-workflow.md](application-workflow.md)
for clean reruns, pilot/resume commands, I/O boundaries, and runtime planning.

## Complete clean run

To download and checksum-check Stanford, USGS and NOAA archives without conversion
or benchmarks, use `make download-data` (`make docker-download-data` in Docker).
It prepares Python dependencies and reuses checksum-valid files. `make real-data`
depends on this target and then converts the datasets.

Run data preparation, builds, tests, measurements, and artifact validation with:

```sh
make all-targets
```

To preserve existing results before cleanup, run `make archive` first. It writes
an archive and checksum under `backups/sources/`, which cleanup preserves.
`all-targets` creates or updates `.venv`, then runs `real-data` to download,
checksum-check and convert all Stanford, USGS and NOAA inputs before cleanup
or builds. A download, verification or conversion failure stops the run while
existing build and measurement outputs are still retained. After cleanup,
`demo-data` generates the demo archives, manifests, runlists and A7 fixture;
it runs after `clean-artifacts` so those generated files are retained.
Failure here also stops the run before compilation and tests.
The target then runs formatting, debug
and CLI tests, Clang/GCC release tests, sanitizers, coverage, reproducibility,
`bench` with its application studies, artifact generation, and integration checks.
It does not compile the manuscript.
`clean-artifacts` preserves downloaded, converted and cached datasets. `real-data`
verifies/reuses them. Only the manual `make clean-data` target removes
`data/raw`, `data/processed` and `data/cache` contents; it is excluded from
`all-targets`. The long fuzz soak remains an explicit operation.
The sequential aggregate recipes preserve phase
order under `make -j`; independent top-level goals should still be chained with
`&&` when one consumes another's output.

## Tree benchmark

After the full `app-query` inputs exist, run `make test-tree` for short native
query and workflow checks, then `make bench-tree` for the long tree experiment.
CGAL k-d-tree DFS layouts are compared using the common page-file engine;
native CGAL queries are compared to separate resident-memory controls.
`make paper-artifacts` publishes the tree figure/table if results exist, and
`make test-integration` checks their inventory. `all-targets` includes this tree
phase after app-query. Existing results are not overwritten; select a new
`TREE_OUTPUT_DIR` for another run. See
the shared-source and resident-memory/page-file limits above.

## DBMS benchmark

`make test-dbms` runs short live PostgreSQL/PostGIS checks. After app-query,
`make bench-dbms` runs six arms (input/Hilbert/RCH × sequential/ND-GiST) on
the same frozen inputs and queries. Managed mode starts/stops its own private
socket-only cluster; installed PostgreSQL/PostGIS binaries and Psycopg are
required. The existing host service and roles are not changed. The same mode
works with `make docker-test-dbms` and `make docker-bench-dbms` in the RCH image.
`all-targets` includes this phase after tree. `paper-artifacts` publishes DBMS
results if present; `test-integration` validates them. See
the shared-source query protocol above.

## Maintained entry points

| Goal | Command |
| --- | --- |
| Complete clean build/test/production run | `make all-targets` |
| Core plus all dependent production measurements | `make bench` |
| Dependent studies after the core matrices exist | `make bench-extended` |
| Checkpointed archive/rerun and recovery | `make rerun-benchmarks`, `make resume-benchmarks` |
| Stored refinement/key-sharing analysis | `make measurement-diagnostics` |
| Derived tables/figures only | `make paper-artifacts` |
| Artifact validation | `make test-integration` |

Demo benchmark runs, container wrappers and the 24-hour fuzz soak remain opt-in.
Demo fixture generation is part of the early `all-targets` data phase.
Production results use the actual adapters and available hardware counters.

## Component and application benchmarks

The seven application datasets include four LiDAR projects: Cameron Peak,
Santiam River, Long Island and Southwest Florida. The NOAA manifest pins full
files, project metadata, checksums, CRS and metre conversion. No crop or thinning
is applied. Sensor models are supported at project level; selected-tile serial
numbers are unknown. COPC record order may already be spatially clustered.

`make test-clamping-intervention` checks the native replay and controlled
quantizer. `make bench-clamping-intervention` runs 220 independent-cloud
interventions plus four-site subcloud sensitivity checks. It requires the frozen
independent benchmark inputs. `make test-cost-stability` tests the scenario
selection rule; `make bench-cost-stability` measures six native policies on the
same 220 clouds. Existing output directories must first be archived.

`make validate-extended-benchmarks` verifies recorded sources, permutations,
quantization snapshots, MIAD, Kendall and budget decisions. When clamping, cost/stability, and real-data clamping
measurements exist, `test-integration` also checks their published
source snapshots, generator hash, tables and figure checksums.
`make extended-benchmark-artifacts` publishes source-linked tables and figures
from the completed measurements. `make bench-extended` runs these
experiments, application/tree/DBMS measurements and artifacts sequentially.
It requires the independent input suite to exist and unused measurement paths.
It does not edit the manuscript.

## Stored measurement diagnostics and checkpointed reruns

`make test-measurement-integrity` checks RSS and key-count regressions.
`make measurement-diagnostics` compares off/all refinement and separates
identical coordinates from mixed-coordinate key collisions in stored orders.

`make plan-benchmark-rerun` prints the production rerun plan without moving files.
`make rerun-benchmarks` archives measured/generated outputs under `backups/`
and records stage checkpoints under `experiments/logs/benchmark_pipeline/`.
`make plan-benchmark-resume` shows pending steps; `make resume-benchmarks` preserves
completed core matrices and completed dependent studies. Only a failed dependent
step's private outputs are archived before retry. `make test-benchmark-resume`
checks recovery and relative/absolute executable paths.

## Fallback diagnostics

`make fallback-evidence` counts saved estimator/axis fallback records with explicit
unknown telemetry. `make validate-fallback-evidence` checks source/artifact hashes;
`make test-fallback-evidence` runs boundary-input and output checks. Controls write
under `experiments/logs/validation/`. These checks do not prove universal robustness.

## Verified page-cache experiment

`make bench-application-cache` consumes the frozen shared application files, with
per-query verified empty/full Linux page-cache conditions. It does not evict device
controller caches. `make validate-application-cache` validates all rows and hashes;
`make resume-application-cache` preserves completed layout tasks after interruption.
The timing includes file open/header/close with a resident directory, so it differs
from the workload-pass warm-cache query protocol.

## Optional manuscript build

Use `make paper-pdf` as a separate command when manuscript sources are
present. It is not part of `make all-targets`.

Artifact generation does not edit manuscript prose, literal numerical tables,
or citations. The optional PDF build copies referenced generated figures and
compiles the existing author files. It does not integrate new results.

`all-targets` is a clean restart, not a checkpointed run. For interruption in
the measurement phase, use [checkpointed reruns](#stored-measurement-diagnostics-and-checkpointed-reruns).
This recovery does not cover the build and sanitizer phases.
