# Getting Started

This guide takes the shortest path from a fresh checkout to a verified RCH
ordering. It uses the small example target and does not download research data.

## 1. Check The Toolchain

The basic library path requires:

- CMake 3.28 or newer;
- a C++23 compiler;
- Ninja, Make, or another CMake build tool.

Python is not needed to call the header-only library, but Python 3.10 or newer
and `requirements.txt` are required by tests, experiment runners, and analysis.

```bash
cmake --version
c++ --version
python3 --version
```

See [requirements.md](requirements.md) for optional CGAL, R, `perf`, Poppler,
LaTeX, sanitizer, and fuzzing dependencies.

## 2. Run The Maintained Example

From the repository root:

```bash
make example-basic
```

The target configures `build/examples` with tests disabled, builds
`rch_basic_order`, and runs three cases: default RCH, RCH with the hybrid bit
rule, and PCA compact Hilbert with local refinement.

Run the executable directly when experimenting:

```bash
build/examples/examples/rch_basic_order
build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz
build/examples/examples/rch_basic_order --help
```

Diagnostics are written to standard error. Standard output is a CSV table:

```text
rank,raw_index,key
0,...,...
```

`raw_index` points into the original point array. It is the value to use when
reordering application attributes such as normals, colors, labels, or IDs.

## 3. Build Your Own Program

RCH is header-only. In an in-tree CMake project, add this repository and link
the interface target:

```cmake
add_subdirectory(path/to/rch)
add_executable(my_order main.cpp)
target_link_libraries(my_order PRIVATE rch::core)
```

The target propagates the include directory and C++23 requirement. The default
RCH configuration is:

```cpp
rch::orderings::OrderingConfig config{};
// config.method     == OrderingMethod::RCH
// config.frame      == FrameEstimator::DetMCD
// config.bit_alloc  == BitAllocator::FrameCoreOccupancy
// config.refinement == RefinementMode::Off
```

Input is a flat row-major span of binary64 values:

```text
x0, y0, z0, x1, y1, z1, ..., xN-1, yN-1, zN-1
```

The length must be divisible by three and every coordinate must be finite.
Malformed shape and `NaN`/infinity return `std::unexpected`; no point is
silently removed.

## 4. Run The Core Test Pyramid

Create an isolated Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Then build and test:

```bash
make build
make test
```

`make test` covers unit, property, oracle, regression, and Python checks that do
not require the full stored experiment matrix. CLI and artifact-bound checks are
separate targets; see [reproducibility.md](reproducibility.md).

## 5. Know What Success Means

A successful call means that RCH returned a total ordering of the accepted
records and its diagnostic fields were constructed. It does not mean that the
order minimizes path length, improves a particular application, or is more
robust than every baseline on the caller's data. Measure the downstream metric
that matters to the application.
