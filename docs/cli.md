# Command-Line Tools

The developer CLIs are built only when `RCH_BUILD_TOOLS=ON`.

```bash
cmake -S . -B build/src-tools \
  -DRCH_BUILD_TOOLS=ON \
  -DRCH_BUILD_TESTS=OFF
cmake --build build/src-tools --parallel
```

The executables are written under `build/src-tools/src/cli/`.

## rch_order

`rch_order` reads points, calls the public ordering facade, writes a permutation
CSV, and records a JSON manifest.

```bash
mkdir -p build/cli-output
build/src-tools/src/cli/rch_order \
  --input examples/tiny_point_cloud.xyz \
  --method rch \
  --frame-estimator det_mcd \
  --bit-allocator frame_core_occupancy \
  --refinement off \
  --timing-repeats 3 \
  --output build/cli-output/order.csv \
  --manifest build/cli-output/order.json
```

All three file options, `--input`, `--output`, and `--manifest`, are required.
The CLI accepts:

- whitespace-separated `.xyz` rows;
- comma-, semicolon-, or whitespace-separated `.csv` rows without a header;
- ASCII PLY 1.0 vertex files whose first three vertex fields are x, y, and z.

Only the first three numeric fields of each row are read. Binary PLY and
unsupported extensions are rejected.

### Method tokens

`input`, `lexicographic`, `morton`, `isotropic_hilbert`,
`compact_hilbert_aabb`, `pca_compact_hilbert`,
`robust_frame_morton`, and `rch`.

### Frame tokens

`sample`, `sample_covariance`, `det_mcd`, `mrcd`, and `ogk`. Frame selection
matters only for methods that use a statistical frame. PCA compact Hilbert
reports sample covariance regardless of this option.

### Bit-rule tokens

`uniform`, `sample_count_uniform`, `monotone_half`,
`occupancy_floor1`, `occupancy_floor10`,
`frame_core_occupancy`, and `hybrid_occupancy`.

The experiment aliases such as `c0_uniform` and `c4_hybrid` are also parsed by
the CLI, but descriptive names are preferable in user scripts.

### Numeric controls

- `--uniform-bits N` sets the equal per-axis depth used by uniform allocation;
- `--min-axis-bits N` sets the requested occupancy floor;
- `--timing-repeats N` reports the median of repeated ordering calls and must be
  positive.

`--refinement` accepts `off` or `all`.

The frame-control options are `--fixed-frame-domain-half-extent X`,
`--fixed-frame-quantizer H0,H1,H2,B0,B1,B2`, and
`--frame-grid-shift-cells F`. They support controlled PCA/RCH experiments;
use the defaults for normal ordering. See [API controls](api.md#configuration).

## Output CSV

The order file is:

```text
rank,raw_index,key
0,5,17
1,2,21
...
```

`raw_index` refers to the input row. `key` is indexed by that original row.
With refinement enabled, ranks may no longer be monotone in `key`.

## Manifest

The manifest records enough context to audit one invocation, including:

- requested/effective method and frame estimator;
- bit allocator, allocation model, and budget-projection rule;
- refinement mode and numeric settings;
- point count, bit depths, frame axes, center, and half-extents;
- scatter repair and robust-fallback flags;
- integer-output SHA-256 digest;
- clipping, saturation, shared-key counts, and phase timings;
- median ordering time and process peak RSS when supported.

Timing and RSS are environment-dependent diagnostics. They are not part of the
integer-output digest. Nested estimator phases must not be added again to
the estimator total. Saved flags do not give a complete event history of
repairs, non-convergence, or failure reasons.

## Other Tools

`rch_compare_orders` computes comparison metrics used by experiment runners.
`rch_block_read_probe` performs the deterministic block-read workload used with
Linux `perf`. These tools are research infrastructure rather than a stable
end-user API. Their command lines are exercised by
`tests/integration/test_cli_tools.py`.

Run the maintained CLI smoke test with:

```bash
make test-cli
```

## Failure Handling

The tool returns nonzero for malformed options, unreadable or unsupported
input, ordering failure, and output-write failure. Experiment scripts should
check the exit code and the expected output files; they should not infer
success from a partially written log.
