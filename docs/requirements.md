# Requirements

RCH is header-only, but the repository contains tests, CLIs, experiments, and
analysis tooling with additional dependencies. Install only the layer you need.

## Core Library And Example

Required:

- a C++23 compiler;
- CMake 3.28 or newer;
- Ninja, Make, or another CMake generator.

The checked presets target Clang and GCC. Other conforming compilers may work
but are outside the recorded cross-toolchain matrix.

Build only the example:

```bash
cmake -S . -B build/examples \
  -DRCH_BUILD_TESTS=OFF \
  -DRCH_BUILD_EXAMPLES=ON
cmake --build build/examples --target rch_basic_order --parallel
```

## Python Layer

Repository scripts require Python 3.10 or newer. The complete imported
third-party package set is:

| Package | Minimum | Used for |
| --- | ---: | --- |
| PyYAML | 6.0 | runlists, manifests, and configurations |
| NumPy | 1.24 | array processing and generated summaries |
| SciPy | 1.10 | statistical tests and neighbor support |
| Matplotlib | 3.7 | paper figures |

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

No Python package is needed by an application that only includes the C++
headers.

## CMake Options

| Option | Default | Purpose |
| --- | --- | --- |
| `RCH_BUILD_TESTS` | ON | test tree and GoogleTest dependency |
| `RCH_BUILD_BENCHMARKS` | OFF | Google Benchmark executables |
| `RCH_BUILD_TOOLS` | OFF | developer CLIs |
| `RCH_BUILD_EXAMPLES` | OFF | maintained public-API examples |
| `RCH_WITH_CGAL` | OFF | external CGAL spatial-sort adapter |
| `RCH_BUILD_FUZZ` | OFF | Clang libFuzzer harnesses |
| `RCH_ENABLE_INSTALL` | ON | header and CMake target export rules |

`RCH_WITH_PCL` and `RCH_WITH_OPEN3D` are reserved feature switches in the
current options module; this repository does not add corresponding adapter
subdirectories.

## Optional CGAL Baseline

CGAL, Boost headers, GMP, and MPFR are required only for the external A7
adapter and workflows that depend on it.

On Ubuntu-like systems:

```bash
sudo apt-get install libcgal-dev libboost-dev libgmp-dev libmpfr-dev
make cgal-adapter-bin
```

CGAL is not a dependency of `rch::core`.

## Optional R Oracles

Regenerating or checking the external robust-statistics references needs R,
`Rscript`, and:

```r
install.packages(c("robustbase", "rrcov", "MAINT.Data"))
```

The ordinary C++ library does not embed R.

## Optional Analysis And Document Tools

The manuscript build needs a LaTeX distribution with the packages imported by
`paper/manuscript.tex`, plus BibTeX. Its LaTeX class and style files are stored
in `paper/`.

`make paper-artifacts` also needs `pdftops` from Poppler to emit EPS copies.
`make paper-pdf` uses `pdflatex`, `bibtex`, and `pdftotext` when available for
checks.

## Optional Instrumentation

- Linux `perf` supplies cache-reference and cache-miss counters.
- Clang is required for the fuzz preset.
- sanitizer runtimes are required by ASan, UBSan, and TSan presets.
- coverage uses the tools configured in `cmake/Coverage.cmake` and
  `scripts/coverage.sh`.

See [linux-perf.md](linux-perf.md) before changing kernel permissions.

## Docker Alternative

The repository Docker image provides Ubuntu 24.04, Clang 20, GCC/G++ 13,
CMake, Ninja, CGAL, and the Python environment. It is useful when the host
does not have this toolchain. See [docker.md](docker.md).
