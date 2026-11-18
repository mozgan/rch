# Requirements

RCH is header-only, but the repository contains tests, CLIs, experiments, and
analysis tooling with additional dependencies. Install only the layer you need.

## Core Library And Example

Required:

- a C++23 compiler and standard library with `std::expected`;
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

Repository scripts require Python 3.11 or newer. The main third-party packages
in `requirements.txt` are:

| Package | Minimum | Used for |
| --- | ---: | --- |
| PyYAML | 6.0 | runlists, manifests, and configurations |
| NumPy | 1.24 | array processing and generated summaries |
| SciPy | 1.10 | statistical tests and neighbor support |
| Matplotlib | 3.7 | paper figures |
| laspy with lazrs | 2.5, below 3 | LAZ/COPC decoding |
| pyproj | 3.6, below 4 | coordinate-system and unit checks |
| Psycopg with binary support | 3.3, below 4 | PostgreSQL/PostGIS benchmark client |

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

The A7 spatial-sort adapter and the kd-tree benchmark need CGAL and Boost
headers. CGAL is header-only; these adapters can use an extracted release
without compiling or installing CGAL itself. The Makefile defaults to
`$HOME/.local/opt/CGAL-6.2.1` and passes `CGAL_DISABLE_GMP=ON` for the adapters'
`Simple_cartesian<double>` kernels. CGAL is not a dependency of `rch::core`.

### User-local CGAL 6.2.1 (Makefile Default)

On Ubuntu 24.04, install the build tools and Boost headers first. The C++23
compiler and CMake 3.28+ requirements above still apply.

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build libboost-dev curl xz-utils
```

Download the official library archive and its checksum list, verify the
download, and extract it into the default location. Run these commands from
the repository root; the subshell keeps the working directory unchanged.

```bash
(
  set -eu
  cgal_download_dir="$(mktemp -d)"
  cgal_release_url="https://github.com/CGAL/cgal/releases/download/v6.2.1"
  cd "$cgal_download_dir"
  curl --fail --location --retry 3 --output CGAL-6.2.1-library.tar.xz \
    "$cgal_release_url/CGAL-6.2.1-library.tar.xz"
  curl --fail --location --retry 3 --output sha256sum.txt \
    "$cgal_release_url/sha256sum.txt"
  sha256sum --check --ignore-missing sha256sum.txt
  mkdir -p "$HOME/.local/opt"
  tar -xJf CGAL-6.2.1-library.tar.xz -C "$HOME/.local/opt"
)
test -f "$HOME/.local/opt/CGAL-6.2.1/CGALConfig.cmake"
```

The checksum list covers several release assets; `--ignore-missing` checks
the downloaded archive while skipping assets that were not downloaded.

Build and smoke-test the A7 adapter from the repository root:

```bash
make cgal-build CGAL_DIR="$HOME/.local/opt/CGAL-6.2.1"
```

The default path also allows `make test-cgal` without a path override.
For the kd-tree adapter, use:

```bash
make test-tree CGAL_DIR="$HOME/.local/opt/CGAL-6.2.1"
```

`test-tree` also prepares the Python environment through `python-deps`.
These targets build and test the repository adapters; they do not install
system packages or run the full production benchmark matrix.

### Ubuntu Package Alternative

To use the distribution's CGAL version instead of the pinned source release:

```bash
sudo apt-get install -y libcgal-dev libboost-dev
export CGAL_DIR="$(dpkg-query -L libcgal-dev | sed -n 's@/CGALConfig.cmake$@@p')"
test -f "$CGAL_DIR/CGALConfig.cmake"
make cgal-build CGAL_DIR="$CGAL_DIR"
```

The exported variable applies to subsequent Makefile commands in the same
shell, including `make test-tree` and `make all-targets`. Record the installed
version with `dpkg-query -W libcgal-dev` for benchmark provenance; it may differ
from 6.2.1. For another installation, set `CGAL_DIR` to the directory containing
`CGALConfig.cmake`, rather than the `include/CGAL` directory. If CMake reports
that CGAL was not found and skips the adapter, check this path. If Boost is
missing, install `libboost-dev` or make its installation discoverable to CMake.

Sources: [CGAL 6.2.1 release and checksums](https://github.com/CGAL/cgal/releases/tag/v6.2.1),
[official installation manual](https://doc.cgal.org/latest/Manual/installation.html).

## DBMS Benchmark Environment

Use PostgreSQL 16 and the PostGIS 3 packages from Ubuntu 24.04. The DBMS
adapter uses Psycopg 3, installed by the main `requirements.txt` and `make venv`.
The server is installed through apt, not pip. The Dockerfile uses the same Ubuntu package names; record the actual installed
versions for each measurement run.

Install on the local host:

```bash
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-client-16 \
  postgresql-16-postgis-3 postgresql-16-postgis-3-scripts
make venv
pg_lsclusters
```

`make test-dbms` and `make bench-dbms` default to managed mode: they create a
private socket-only cluster and stop/remove it afterward. A running system
service or manually created role/database is not needed in this mode.

For optional `DBMS_MODE=external`, start the system service with
`sudo systemctl start postgresql`. For a fresh external setup, create a
dedicated login and database. The password prompt
keeps the password out of the command history. If the role/database already
exists, reuse it instead of repeating the creation commands:

```bash
sudo -u postgres createuser --login --pwprompt rch_bench
sudo -u postgres createdb --owner=rch_bench rch_bench
sudo -u postgres psql -v ON_ERROR_STOP=1 -d rch_bench \
  -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
psql -h 127.0.0.1 -U rch_bench -d rch_bench -W \
  -c 'SELECT version(), postgis_full_version();'
.venv/bin/python -c 'import psycopg; print(psycopg.__version__)'
```

The connection example uses the default port 5432; use the port reported by
`pg_lsclusters` if different. An extension installation needs the administrator
step shown above; the benchmark login does not need superuser privileges.

The repository `Dockerfile` installs these same four apt packages and
installs Psycopg from the main requirements file. Build it with the existing
`make docker-image` target. It keeps the development shell entry point; it does
not start a database server when the container starts. A container benchmark
cluster is initialized automatically by `make docker-bench-dbms` in managed
mode, using a non-root PostgreSQL process. A running host cluster is not
automatically available inside the container.

Record actual PostgreSQL/PostGIS/Psycopg versions and server settings in each
run. See [the database workflow](build-workflows.md#dbms-benchmark).
A point-table PostGIS baseline
is not a replication of PlainSFC, HistSFC, SplitSFC or pgPointCloud.

Sources: [Ubuntu PostGIS package](https://packages.ubuntu.com/noble/postgresql-16-postgis-3),
[PostgreSQL role setup](https://www.postgresql.org/docs/16/app-createuser.html),
[Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html).

## Optional R Oracles

Regenerating or checking the external robust-statistics references needs R,
`Rscript`, and:

```r
install.packages(c("robustbase", "rrcov", "MAINT.Data"))
```

The ordinary C++ library does not embed R.

## Optional Analysis And Document Tools

`make paper-pdf` is optional and separate from `all-targets`. With manuscript
sources present, it needs a LaTeX distribution with the packages imported by
`paper/manuscript.tex`, plus BibTeX. Its LaTeX class files are stored in `paper/`; the bibliography style
`elsarticle-num-names.bst` is supplied by TeX Live's Elsevier package.

`make paper-artifacts` also needs `pdftops` from Poppler to emit EPS copies.
`make paper-pdf` uses `pdflatex`, `bibtex`, and EPS conversion through
`epstopdf`/Ghostscript. It first copies referenced
generated figures into `paper/figures/`; it does not update inline numerical
tables or claims.

## Optional Instrumentation

- Linux `perf-stat(1)` supplies cache-reference and cache-miss counters.
- Clang is required for the fuzz preset.
- sanitizer runtimes are required by ASan, UBSan, and TSan presets.
- coverage uses the tools configured in `cmake/Coverage.cmake` and
  `scripts/coverage.sh`.

See [linux-perf.md](linux-perf.md) before changing kernel permissions.

## Docker Alternative

The repository Docker image provides Ubuntu 24.04, Clang 20, GCC/G++ 13,
CMake, Ninja, CGAL, and the Python environment. It is useful when the host
does not have this toolchain. See [docker.md](docker.md).
