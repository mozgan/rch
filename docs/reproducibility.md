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

Use `make test-cli` for the developer executables.

## Level 2: Reproducibility Smoke

```bash
make repro-smoke
```

The smoke script builds the reproducibility preset, runs the hash-locked tests,
generates three small inputs, runs each ordering twice, compares the CSVs, and
requires equal manifest hashes. It checks repeat execution in the current
environment; it is not by itself a cross-platform proof.

The pinned portability record in
`reproducibility/expected_outputs/portability_diff.json` covers the integer
output digest for recorded x86-64 Clang and GCC runs. Its scope explicitly
excludes bit-exact floating-point diagnostics.

## Level 3: Small End-To-End Artifact Workflow

```bash
make bench-demo
```

This creates deterministic file-backed demo data, runs synthetic and real-data
demo matrices, exercises the CGAL adapter, generates report artifacts, and
checks their layout. The demo uses a controlled `perf` shim; it validates the
pipeline and schemas, not real hardware-counter values or the full study
sample size.

## Level 4: Stored Results

To regenerate tables and figures from existing full outputs:

```bash
make paper-artifacts
make paper-pdf
```

`paper-artifacts` requires the optional CGAL adapter and Poppler's `pdftops`.
It reads `experiments/outputs/` and writes `analysis/generated/` before the
document build consumes the generated figures.

Run the stored-result consistency checks:

```bash
python paper/review/verify_claims.py
python paper/review/round5/verify_comparison.py
python paper/review/round5/verify_estimator.py
```

Some checks require R, `robustbase`, a C++23 compiler, and PDF text tools.
Passing them establishes consistency with stored records; it does not rerun the
full experiment.

## Level 5: Full Experiment Rerun

```bash
make bench
make paper-pdf
```

The full workflow builds internal tools and CGAL, runs both refinement arms,
downloads Stanford source archives on the first real-data run, regenerates
tables and figures, and runs the recorded determinism checks. It is long and
can be affected by machine load and performance-counter permissions.

Before rerunning:

1. Preserve or archive existing `experiments/outputs/` and
   `analysis/generated/` if they are evidence you need to retain.
2. Record OS, architecture, compiler, CMake, Python package, CGAL, R package,
   CPU, memory, and kernel versions.
3. Check the source URLs and SHA-256 values in `data/manifests/`.
4. Read [linux-perf.md](linux-perf.md).
5. Do not compare internal and CGAL time columns as if their timing boundaries
   were identical.

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
