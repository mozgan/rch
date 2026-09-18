# Robust Compact Hilbert (RCH)

RCH is a C++23 header-only library and research artifact for ordering indexed
three-dimensional point clouds. The default method estimates a robust principal
frame, allocates unequal per-axis bit depths, quantizes the projected points,
and sorts compact Hilbert keys. The result is a permutation of the original
records; RCH does not resample, merge, or replace the input coordinates.

The repository contains the public library, developer command-line tools,
examples, tests, experiment runners, stored results, analysis scripts, and the
accompanying research paper.

## What RCH Is For

Use RCH when a point set needs a deterministic one-dimensional traversal for
storage, block access, or downstream locality experiments. RCH is an ordering
component, not a surface reconstruction algorithm, spatial database, or proof
that one order is best for every workload.

The recorded evidence is deliberately bounded. RCH improves selected locality
and contamination-stability measures on the recorded anisotropic synthetic
clouds, costs more than the simpler internal baselines, and does not beat
isotropic Hilbert on mean inter-adjacent distance for the two recorded Stanford
reconstruction vertex sets. See [the evidence guide](docs/experiments.md) before
generalizing the results.

## Quick Start

Requirements for the basic example are CMake 3.28 or newer, a C++23 compiler,
and a build tool supported by CMake.

```bash
make example-basic
```

This builds and runs `examples/basic_order.cpp` on embedded points and on the
small fixture in `examples/tiny_point_cloud.xyz`.

To use the public API directly:

```cpp
#include <span>
#include <vector>

#include "rch/orderings/orderer.hpp"

std::vector<double> xyz{
    0.0, 0.0, 0.0,
    1.0, 0.0, 0.0,
    0.0, 1.0, 0.0,
    0.0, 0.0, 1.0,
};

rch::orderings::OrderingConfig config{}; // RCH + DetMCD + core occupancy
auto ordered = rch::orderings::order_point_cloud(
    std::span<const double>{xyz}, config
);

if (!ordered) {
    // Handle ordered.error().code and ordered.error().message.
}
```

On success, `ordered->permutation[rank]` is the original point index at that
rank. `ordered->primary_keys[raw_index]` is the curve key associated with an
original point. See [the API guide](docs/api.md) for the full result contract.

## Build And Test

Create a Python environment before running repository tests or analysis:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Build the default debug preset and run the artifact-independent test pyramid:

```bash
make build
make test
```

Useful narrower checks are:

```bash
make test-unit
make test-property
make test-oracle
make test-regression
make test-cli
make repro-smoke
```

The full benchmark and paper-artifact workflow needs optional CGAL, dataset,
Linux performance-counter, and LaTeX dependencies. Start with the small
file-backed workflow:

```bash
make bench-demo
```

See [requirements](docs/requirements.md) and
[reproducibility](docs/reproducibility.md) before running `make bench`.

## Developer CLI

Build the tools without the test suite:

```bash
cmake -S . -B build/src-tools \
  -DRCH_BUILD_TOOLS=ON \
  -DRCH_BUILD_TESTS=OFF
cmake --build build/src-tools --parallel
```

Order an XYZ file and write both the permutation and its provenance:

```bash
build/src-tools/src/cli/rch_order \
  --input examples/tiny_point_cloud.xyz \
  --method rch \
  --frame-estimator det_mcd \
  --bit-allocator frame_core_occupancy \
  --refinement off \
  --output /tmp/rch-order.csv \
  --manifest /tmp/rch-manifest.json
```

The CSV schema is `rank,raw_index,key`. The JSON manifest records the effective
method, frame estimator, bit rule, bit depths, fallback state, timing, frame,
and SHA-256 integer-output digest. Details are in [the CLI guide](docs/cli.md).

## Documentation

- [Documentation map](docs/README.md)
- [Getting started](docs/getting-started.md)
- [Algorithm and mathematical contract](docs/algorithm.md)
- [C++ API](docs/api.md)
- [Command-line tools](docs/cli.md)
- [Experiments and interpretation](docs/experiments.md)
- [Reproducibility](docs/reproducibility.md)
- [Requirements](docs/requirements.md)
- [Docker](docs/docker.md)
- [Linux performance counters](docs/linux-perf.md)

## Repository Map

| Path | Purpose |
| --- | --- |
| `include/rch/` | Public header-only C++ library |
| `src/cli/` | Ordering, comparison, and block-read tools |
| `examples/` | Minimal public-API program and tiny point cloud |
| `tests/` | Unit, property, oracle, regression, integration, and fuzz tests |
| `experiments/` | Algorithm configurations, runlists, runners, and outputs |
| `analysis/` | Table, statistic, and figure generation |
| `data/` | Synthetic generators and external-data manifests |
| `baselines/reference_r/` | R reference computations for robust estimators |
| `reproducibility/` | Smoke workflow and expected portability records |
| `paper/` | Research paper, bibliography, figures, and supporting files |

## Citation And License

Citation metadata are provided in [CITATION.cff](CITATION.cff). The software is
released under the [MIT License](LICENSE).
