# Docker

The Dockerfile defines a development environment: Ubuntu
24.04, Clang 20, GCC/G++ 13, CMake, Ninja, CGAL development packages, and the
Python packages from `requirements.txt`. It does not freeze the host kernel,
CPU, Docker engine, downloaded research datasets, or runtime load. OS and Python
package versions are resolved when the image is built; the image is not a fully
pinned environment.

## Build The Image

```bash
make docker-image
```

The default local tag is `rch-dev:local`. Override it with
`DOCKER_IMAGE=name:tag`.

## Run Maintained Targets

Every target listed in `DOCKER_MAKE_TARGETS` can be invoked with a
`docker-` prefix:

```bash
make docker-examples
make docker-test
make docker-test-cli
make docker-repro-smoke
make docker-bench
```

The container uses the same benchmark stages as local Makefile targets; see
[Build workflows](build-workflows.md). With manuscript sources present,
`docker-paper-pdf` can compile them separately from the benchmark workflow.

The repository is bind-mounted at `/work/rch` and container builds go to
`docker-build/` by default. Generated files therefore remain in the host
working tree.

Open an interactive shell with:

```bash
make docker-shell
```

## File Ownership

A rootful Docker daemon may create root-owned build artifacts in the bind
mount. Pass the host user explicitly when necessary:

```bash
make docker-test \
  DOCKER_USER_FLAGS="--user $(id -u):$(id -g)"
```

The Makefile directs XDG and Matplotlib caches into the repository's `.cache/`
directory through the bind mount.

## Network And Data

The image includes PostgreSQL 16, its client and PostGIS 3.
Psycopg is included through the main `requirements.txt`. No separate DBMS image
is needed. The container starts a development shell. `make docker-test-dbms`
and `make docker-bench-dbms` initialize and stop a private non-root server
automatically in managed mode. See [requirements.md](requirements.md#dbms-benchmark-environment) for the
equivalent local Ubuntu installation and database setup.

Building the image downloads OS and Python packages. The first full real-data
benchmark also downloads archives listed in `data/manifests/`. Verify their
recorded checksums and comply with the upstream dataset terms.

The demo benchmark uses repository-generated file-backed data and is the
preferred end-to-end pipeline check when external downloads are undesirable.

## Performance Caveat

Containerization does not make timing, RSS, or hardware counters portable.
Docker uses the host kernel, and access to `perf_event_open(2)` may be restricted
by the host, container capabilities, or security policy. Never replace a
missing counter with zero; keep the emitted `perf_status`.
