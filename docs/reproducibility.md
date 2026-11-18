# Reproducibility

RCH uses several levels of verification. Choose the smallest level that answers
the question at hand and record the toolchain when comparing outputs.

## Level 1: Core Test Pyramid

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
make test
```

This builds the debug preset and runs artifact-independent unit, property,
oracle, regression, and Python tests. Important coverage includes:

- finite-input and shape validation;
- total-order and permutation properties;
- quantization bounds and curve-key range;
- compact and standard Hilbert oracle vectors;
- DetMCD, MRCD, and OGK reference cases;
- fallback semantics and degenerate clouds;
- pinned hashes for seven tiny fixtures across eight methods.

`make test` also runs the developer CLI checks; use `make test-cli` to run
those checks separately.

## Level 2: Reproducibility Smoke

```bash
make repro-smoke
```

The smoke script builds the reproducibility preset, runs the hash-locked tests,
generates three small inputs, runs each ordering twice, compares the CSVs, and
requires equal integer-output digests in the manifests. It checks repeat execution in the current
environment; it is not by itself a cross-platform proof.

The pinned portability record in
`reproducibility/expected_outputs/portability_diff.json` covers the integer
output digest for recorded x86-64 Clang and GCC runs. Its scope explicitly
excludes bit-exact floating-point diagnostics.

## Level 3: Measurements and Artifact Validation

```bash
make bench
```

`bench` runs the synthetic, real, independent and CGAL ordering matrices,
then application, tree, DBMS, page-cache and continuous storage/query
experiments, followed by artifacts and validation. `app-query` can also run
separately on seven real datasets. Do not rerun it in the same output
directory after a successful `bench`; use a new directory for new measurements.
Application, tree and DBMS all use the same `APPLICATION_QUERY_OUTPUT_DIR`
(default `experiments/outputs/application_query/full_benchmark`). Their
source manifest hashes must match. Each query run requires an unused output
directory; archive completed runs before regeneration. See
[build workflows](build-workflows.md) for the clean sequence and overrides.

## Level 4: Stored Results

To regenerate tables and figures from existing full outputs:

```bash
make paper-artifacts
```

`paper-artifacts` requires existing core and application measurements and Poppler's `pdftops`.
It reads `experiments/outputs/` and writes `analysis/generated/` before the
document build copies the referenced generated figures into `paper/figures/`.
`make paper-pdf` is an optional next step when manuscript sources are present.
It copies the referenced figures and compiles the document. Inline manuscript
tables and claims must still be updated by hand.

Run the stored-result consistency checks:

```bash
make validate-extended-benchmarks
make test-integration
```

These commands require the matching recorded experiment outputs. They reject
changed source hashes; that rejection requires rerunning affected measurements,
not editing the stored hashes. `make measurement-diagnostics` analyzes preserved
refinement and key/coordinate records without claiming a new benchmark run.
See [the complete workflow](build-workflows.md#complete-clean-run) for clean-run
instructions and checkpointed benchmark recovery.

## Level 5: Clean or checkpointed reruns

For a complete clean restart, see [Build workflows](build-workflows.md#complete-clean-run).
`make all-targets` includes data preparation, cleanup, builds, tests,
measurements, artifact generation, and validation. It does not compile the manuscript.

For a measurement rerun with existing results, inspect the plan before running:

```bash
make plan-benchmark-rerun
make rerun-benchmarks
```

The run command archives existing outputs and records checkpoints. After an
interruption, inspect `make plan-benchmark-resume`, then use
`make resume-benchmarks`. These checkpoints cover measurement stages, not the
full build and sanitizer sequence. The continuous workflow has its own
[resume command](application-workflow.md#separate-execution).

Record the OS, CPU, kernel, compiler, CMake, Python packages, CGAL and database
versions. Check source checksums and [perf permissions](linux-perf.md). Do not
compare timing columns with different measurement boundaries.

## Sharing results

Share the source commit together with the matching manifests, row-level
results, workload/input hashes, source snapshots, and environment records.
Real source archives must be downloaded from their providers using the tracked
manifests. Do not replace missing provenance with invented values. Preserve
completed outputs before cleanup; `make archive` writes a local backup, not
a public release or permanent identifier.

Documentation links point to maintained repository files. Paths to generated
outputs describe where commands write results; they are not promised downloads.

## Digest Semantics

The per-order SHA-256 digest contains integer output state: method, bit depths,
fallback flag, permutation, and primary keys. It deliberately excludes input
file bytes and floating-point diagnostics.

Therefore equal digests mean that the covered integer ordering payloads match.
They do not prove that:

- the input files were byte-identical;
- centers, axes, extents, timing, RSS, or counters were bit-identical;
- the executable was built from trusted source;
- SHA-256 was used as a signature or authenticity mechanism.

Use dataset checksums and environment manifests alongside the ordering digest.

## Expected Variability

Timing, RSS, scheduler behavior, CPU frequency, page cache, and hardware events
are environment-dependent. Floating-point results can vary with compiler,
standard library, mathematics library, architecture, contraction policy, and
coordinate scale. The build disables unsafe fast-math transformations, but
that does not make every floating-point operation universally bit identical.
