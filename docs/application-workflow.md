# Continuous storage/query workflow

This experiment starts with a prepared XYZ file. Each trial runs in a fresh
C++ process and measures one continuous interval:

1. Read and parse the points.
2. Call the ordering library **once**, with refinement off.
3. Write the order, binary page file, and page directory.
4. Read the directory, execute all queries, and write every matching point ID.
5. Close the files and call `fsync(2)` on the four output files and their directory.

The total is measured directly. It is not a sum of separately measured medians.
Phase times partition the same run; their medians need not sum to the median total.

The three layouts are input-order pages, isotropic Hilbert with ten bits per axis,
and default RCH/C3. The points, query windows, output format, file synchronization,
and correctness requirements are the same for all three.

## Timing and I/O scope

Before the timer, the input file is read to warm its page cache. `mincore(2)` must
confirm full residency. Frozen query windows and oracle hashes are also loaded
before the timer. Output-directory creation and process startup are excluded.
New page files keep their natural cache state after writing. This is **not** the
separate cold-page-cache query experiment.

The measured result file contains actual sorted raw point IDs, including an
empty result when a query matches no points. File data and directory entries
are synchronized before the timer stops. This uses the filesystem's `fsync(2)`
contract; it does not test device firmware or power-failure behavior.

Linux `/proc/self/io` counters (`proc_pid_io(5)`) provide `read_bytes` and
`write_bytes` differences for the full
workflow, including the synchronization stage. They are process-attributed
storage-layer counters, not device-controller telemetry. Missing counters stay
missing. Logical query-page bytes are reported separately. With warm input and
newly written pages, recorded storage reads can be zero. Storage writes are not
assumed equal to output-file sizes. The mount information is recorded.

CPU snapshots slightly bracket the steady-clock interval. Peak RSS includes
the process's pre-timer query loading and input-cache setup, but is captured
before the post-run verification.

Source download/conversion, oracle generation, cache setup, post-run checks,
artifact generation, and work-file cleanup are outside the timer. The driver
also records process wall time including verification, separately from the
primary workflow time. This is a storage/query application, not a full
classification or reconstruction pipeline.

## Workloads and repeats

By default, each of the seven pinned real inputs receives 256, 512, and 1024
queries, five whole-workflow repeats, and all three layouts:

* **315** fresh-process workflows;
* **188,160** measured queries in total;
* one ordering call per workflow, not five ordering calls inside one trial.

The 256-window block contains 86 small, 85 medium,
and 85 large windows. Their widths are 1/32, 1/8, and 1/2 of the bounding-box
extent on each axis. The other three 256-window blocks use different recorded seeds.
The 256/512 workloads are prefixes of the 1024-window workload; larger
workloads do not repeat the same 256 windows. Oracle generation scans the
coordinates independently with NumPy, outside all layout timers. It also
computes the expected SHA-256 of the entire materialized result file.

Layout/query-count execution order is shuffled with a recorded seed within
each dataset and repeat. All sizes begin with a new input read and a new order.
Repeats and nested query prefixes are not independent scenes. Artifacts report
descriptive medians and paired repeat differences, without population tests.

## Separate execution

Use a complete checkout on the measurement machine. Keep the compiler,
filesystem, host, and source commit fixed for comparisons. See
[Build workflows](build-workflows.md) for the shared benchmark setup.

Prepare the Python environment and inspect the plan:

```bash
make venv
make plan-application-workflow
make test-application-workflow
```

The test uses only tiny synthetic fixtures; it does not load downloaded scenes.
Run the production experiment and publish its artifacts:

```bash
set -o pipefail
make bench-application-workflow 2>&1 | tee application-workflow.log
make validate-application-workflow
```

The benchmark target builds the workflow CLI and runs `real-data` to check or
prepare the pinned source datasets. It does not require existing synthetic,
query, tree, or database experiment outputs. If outputs already exist, it fails
instead of overwriting them. Resume an interrupted run with identical code,
binary, and parameters:

```bash
make resume-application-workflow
```

For a pilot, use a separate directory so it cannot replace the main experiment:

```bash
make bench-application-workflow \
  APPLICATION_WORKFLOW_DATASETS=stanford_bunny \
  APPLICATION_WORKFLOW_QUERY_COUNTS=256 \
  APPLICATION_WORKFLOW_REPEATS=1 \
  APPLICATION_WORKFLOW_OUTPUT_DIR=experiments/outputs/application_workflow/pilot \
  APPLICATION_WORKFLOW_ARTIFACT_ROOT=experiments/outputs/application_workflow/pilot/artifacts
```

This runs three workflows. The pilot is for runtime/setup checks; it is not the
five-repeat, seven-input production experiment. Its artifact rows identify the
actual dataset, query count, and repeats. Its artifacts stay inside the pilot
directory and do not replace the main experiment's generated artifacts.

To run only the 256-query production workload, set
`APPLICATION_WORKFLOW_QUERY_COUNTS=256`. For all three sizes, keep the default
or set `APPLICATION_WORKFLOW_QUERY_COUNTS="256 512 1024"`.

## Clean full regeneration

`make all-targets` runs this experiment through `bench` and `bench-extended`.
It calls `clean` and `clean-artifacts` before building and measuring:

```bash
set -o pipefail
make all-targets 2>&1 | tee all-targets.log
```

To regenerate all measurements and artifacts without the complete sanitizer,
coverage, and cross-compiler test pyramid:

```bash
make clean
make clean-artifacts
make venv
set -o pipefail
make bench 2>&1 | tee bench.log
```

Cleaning removes measured outputs and generated artifacts, so all experiments
on the selected path run again. Raw and processed source datasets remain;
`real-data` validates their provenance. `clean-data` is a separate, optional
target if source datasets also need to be downloaded/converted again.

With manuscript sources present, `make paper-pdf` can compile them separately
after artifact generation. It is not part of `all-targets`.

**The manuscript has literal numerical tables and claims.** A successful PDF
build does not update them automatically. After a new run, compare the generated
artifacts and update the manuscript values, including the copied I/O table.
Do not insert tiny-test or pilot measurements into the paper as production data.

## Results and artifacts

Measurements are written under
`experiments/outputs/application_workflow/full_benchmark/`. The root manifest
records the run; `inputs/`, `sources/`, and `runs/` hold validation records.
These are generated output paths, not links to files in a fresh checkout.

The manifest records input/workload hashes, the measured binary hash, source
snapshots, cache and synchronization policies, and complete trial coverage.
After the timer, the C++ backend checks the page checksum and record readback,
the ordering permutation, and all per-query counts and ID hashes. The Python
driver independently checks the complete binary result file against its oracle.

Large order/page/index/result files are removed **after successful verification**
by default. Their sizes and hashes remain. Frozen inputs, workloads, sources,
metrics, and logs remain available for validation. Failed attempts may retain
partial files for diagnosis. To keep all successful bulk output files, add:

```bash
make bench-application-workflow APPLICATION_WORKFLOW_KEEP_ARGS=--keep-work-files
```

This can use much more disk space. In normal mode only one trial's successful
bulk files need to exist at a time.

Artifacts include measurement, summary, and paired-comparison CSV files under
`analysis/generated/outputs/application_workflow/`, two LaTeX tables under
`analysis/generated/tables/`, and PDF/EPS figures under `analysis/generated/figures/`.

The workflow I/O table uses **MiB per complete workflow**, not KiB per query as
in the separate cache table. `scope.md` states the full interpretation.

To regenerate only these artifacts, without any new measurements:

```bash
make application-workflow-artifacts
```

Stored-result validation does not open the measured executable and uses
relative paths inside the workflow package. This allows transferred results
to be checked without rewriting the original machine's paths or hashes.

## Runtime planning

Stored full-scene results are in `analysis/generated/outputs/application_workflow/`.
They describe the recorded host and workload; tiny tests cannot predict production time. Compared with testing only 256 queries, the three
sizes together run input/ordering/storage setup three times and execute seven
times as many queries. Result materialization, synchronization, and post-run
validation also take time, so total runtime need not scale linearly.
Use the pilot log and then a representative larger input to estimate time on
the measurement machine. Do not compare a tiny pilot's time with full-scene data.
