# RCH Examples

The example program `basic_order.cpp` shows how to consume the public
header-only API. It accepts a tiny XYZ file or uses embedded points.

Build it from the repository root:

```bash
make examples
```

Run the default RCH path:

```bash
build/examples/examples/rch_basic_order
```

Run on the fixture file:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz
```

Output on `stdout` is CSV:

```text
rank,raw_index,key
```

Diagnostic metadata is printed on `stderr`: method, frame estimator, bit
allocator, refinement mode, point count, bit depths, fallback flag, and hash.

## RCH Bit-Rule Variants

Default RCH uses DetMCD and `frame_core_occupancy`:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch \
  --frame det_mcd \
  --bit-allocator frame_core_occupancy \
  --refinement off
```

Use the hybrid rule tested as `C4_hybrid` in the paper:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch \
  --frame det_mcd \
  --bit-allocator hybrid_occupancy \
  --refinement off
```

Use the sample-count equal-depth rule:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch \
  --frame det_mcd \
  --bit-allocator sample_count_uniform
```

## Frame Estimator Variants

DetMCD default:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch --frame det_mcd
```

MRCD ablation:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch --frame mrcd
```

OGK ablation:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch --frame ogk
```

Classical sample-covariance frame:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method pca_compact_hilbert --frame sample_covariance --bit-allocator uniform
```

## Internal Baselines

Lexicographic:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method lexicographic
```

Morton on the axis-aligned domain:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method morton --bit-allocator occupancy_floor1
```

Isotropic Hilbert:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method isotropic_hilbert --bit-allocator sample_count_uniform
```

Compact Hilbert on the axis-aligned domain:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method compact_hilbert_aabb --bit-allocator occupancy_floor1
```

Robust-frame Morton:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method robust_frame_morton --frame det_mcd --bit-allocator frame_core_occupancy
```

## Refinement

The default is `off`. To apply the same local MIAD-refinement stage to every
non-input method:

```bash
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz \
  --method rch --refinement all
```

The refinement changes the final permutation. The printed primary keys remain
the original compact-Hilbert keys by raw point index.

## Help

```bash
build/examples/examples/rch_basic_order --help
```
