# C++ API

The stable public facade is `include/rch/orderings/orderer.hpp`. RCH is
header-only and requires C++23 because it returns `std::expected`.

## Minimal Call

```cpp
#include <span>
#include <vector>

#include "rch/orderings/orderer.hpp"

std::vector<double> xyz{
    0.0, 0.0, 0.0,
    1.0, 0.0, 0.0,
    0.0, 1.0, 0.0,
};

rch::orderings::OrderingConfig config{};
auto result = rch::orderings::order_point_cloud(
    std::span<const double>{xyz}, config
);

if (!result) {
    // result.error().code is stable for program logic.
    // result.error().message is a short diagnostic.
}
```

The span is interpreted as a row-major `N x 3` matrix. RCH does not own or
mutate it.

## Configuration

`OrderingConfig` defaults to the standard RCH path:

| Field | Default | Meaning |
| --- | --- | --- |
| `method` | `RCH` | ordering strategy |
| `frame` | `DetMCD` | frame estimator for robust-frame methods |
| `bit_alloc` | `FrameCoreOccupancy` | bit rule and quantization domain |
| `bit_sum_max` | 63 | total compact-key bit budget |
| `uniform_bits` | 10 | equal depth for uniform rules |
| `min_axis_bits` | 1 | requested minimum for occupancy allocation |
| `refinement` | `Off` | optional local MIAD search |
| `tau_quant_squared` | 4.0 | squared scatter-radius multiplier; gives core half-extents `2 sqrt(lambda_j)` |

The encoder enforces its own supported caps even if a larger numeric value is
provided. Prefer defaults unless an experiment has a reason to vary them.

### Ordering methods

| Enum | Token | Frame and curve |
| --- | --- | --- |
| `InputOrder` | `input` | original index order |
| `Lexicographic` | `lexicographic` | raw `(x,y,z,index)` order |
| `Morton` | `morton` | raw AABB, Morton key |
| `IsotropicHilbert` | `isotropic_hilbert` | raw AABB, equal-depth Hilbert |
| `CompactHilbertAABB` | `compact_hilbert_aabb` | raw AABB, unequal-depth Hilbert |
| `PcaCompactHilbert` | `pca_compact_hilbert` | sample-covariance frame |
| `RobustFrameMorton` | `robust_frame_morton` | selected robust frame, Morton key |
| `RCH` | `rch` | selected robust frame, compact Hilbert key |

### Frame estimators

`SampleCovariance`, `DetMCD`, `MRCD`, and `OGK` are available. The PCA compact
method always uses sample covariance. Robust estimators may fall back according
to their numerical policy; inspect `robust_fallback_used`.

### Bit allocators

`Uniform`, `SampleCountUniform`, `MonotoneHalf`, `OccupancyFloor1`,
`OccupancyFloor10`, `FrameCoreOccupancy`, and `HybridOccupancy` are public.
Their domain semantics are described in [algorithm.md](algorithm.md).

## Result Contract

On success, `OrderingResult` contains:

| Field | Indexing or meaning |
| --- | --- |
| `method` | effective ordering method |
| `permutation` | sorted rank to original zero-based point index |
| `primary_keys` | original point index to primary curve key |
| `bits_axis` | encoded depths for x, y, and z in the chosen domain |
| `center` | location used by a frame-based method |
| `half_extent` | quantization-domain half-extents |
| `frame_axes` | 3 x 3 axis matrix |
| `scatter_regularized` | selected scatter required a numerical repair |
| `robust_fallback_used` | requested robust estimate was replaced by sample moments |
| `finite_only_passed` | accepted input passed finite validation |
| `output_hash` | SHA-256 of the documented integer output payload |

Apply the permutation to any parallel application array:

```cpp
for (std::size_t rank = 0; rank < result->permutation.size(); ++rank) {
    const std::size_t raw =
        static_cast<std::size_t>(result->permutation[rank]);
    consume(xyz[3 * raw], xyz[3 * raw + 1], xyz[3 * raw + 2]);
    consume_attribute(attributes[raw]);
}
```

Do not index `primary_keys` by rank. It is stored by original point index:

```cpp
const auto raw = result->permutation[rank];
const auto key = result->primary_keys[raw];
```

After refinement, `key` remains the pre-refinement curve key and may no longer
be monotone along `permutation`.

## Errors

`OrderingErrorCode` separates four categories:

- `invalid_shape`: coordinate count is not divisible by three;
- `invalid_input`: at least one coordinate is not finite;
- `unsupported_method`: the requested enum is not implemented;
- `key_encoding_failed`: a quantized point cannot be encoded.

Branch on the enum rather than matching `message` text.

## Determinism Boundaries

The total sort key makes ties deterministic for a fixed accepted input and the
documented arithmetic behavior. The integer digest is regression-tested across
the recorded GCC/Clang fixtures. RCH does not promise identical floating-point
diagnostics, timing, RSS, or performance counters across all compilers,
libraries, architectures, build flags, and coordinate scales.

## Convenience Wrapper

`include/rch/orderings/robust_compact_hilbert_order.hpp` provides:

```cpp
auto robust_compact_hilbert_order(
    std::span<const double> points_xyz,
    OrderingConfig config = {}
) -> OrderingExpected;
```

It forces `method = RCH` and `frame = DetMCD` while preserving the caller's bit
allocator and other settings. Use the main facade when selecting MRCD or OGK.
