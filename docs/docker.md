# Docker

The Dockerfile defines a reproducible development *tooling layer*: Ubuntu
24.04, Clang 20, GCC/G++ 13, CMake, Ninja, CGAL development packages, and the
Python packages from `requirements.txt`. It does not freeze the host kernel,
CPU, Docker engine, downloaded research datasets, or runtime load.

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
make docker-example-basic
make docker-test
make docker-test-cli
make docker-repro-smoke
make docker-bench-demo
make docker-paper-pdf
```

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

The Makefile sets container `HOME=/tmp` so tools do not depend on a mounted
home directory.

## Network And Data

Building the image downloads OS and Python packages. The first full real-data
benchmark also downloads archives listed in `data/manifests/`. Verify their
recorded checksums and comply with the upstream dataset terms.

The demo benchmark uses repository-generated file-backed data and is the
preferred end-to-end pipeline check when external downloads are undesirable.

## Performance Caveat

Containerization does not make timing, RSS, or hardware counters portable.
Docker uses the host kernel, and access to `perf_event_open` may be restricted
by the host, container capabilities, or security policy. Never replace a
missing counter with zero; keep the emitted `perf_status`.
