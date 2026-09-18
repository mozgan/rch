# RCH Makefile — convenience layer over CMake/CTest.
#
# DESIGN — HIERARCHICAL DEPENDENCY PYRAMID
# ════════════════════════════════════════════════════════════════════════
#  L0  No dependencies     │  help, format, clean, clean-artifacts
#  L1  Needs debug build   │  test-unit, test-property, test-oracle,
#                          │  test-python, test-regression, test-determinism
#                          │     aggregate: `make test` (artifact-free)
#  L2  Needs other presets │  test-release, asan, ubsan, tsan, fuzz,
#                          │  coverage, repro-smoke
#  L3  Needs experiment    │  bench-cpp, cgal-adapter, bench-synthetic, bench-real,
#       artifacts          │  paper-artifacts, test-cgal, test-integration
#                          │     aggregate: `make bench` produces artifacts;
#                          │      `make test-integration` validates them.
#  L∞  Comprehensive       │  `make all-targets` — runs L0→L1→L2→L3 in order.
#                          │  Excludes test-fuzz-soak (24h) and ci-* (debug
#                          │  duplicates). Both remain opt-in.
#
# Test-independence invariant: `make test` (L1) must pass on a clean
# checkout with no experiments/outputs/ artifacts. Coverage gates that
# read experiments/outputs/*.csv live in test-integration (L3) and are
# gated by an artifact-presence precondition.
# ════════════════════════════════════════════════════════════════════════

.DEFAULT_GOAL := help

# Fail fast
SHELL        = /bin/bash
.SHELLFLAGS  = -e -u -o pipefail -c

CMAKE  ?= /usr/bin/cmake
CTEST  ?= /usr/bin/ctest
ifdef VIRTUAL_ENV
PYTHON ?= $(VIRTUAL_ENV)/bin/python
else
PYTHON ?= python3
endif
PYTHON_EXECUTABLE := $(shell "$(PYTHON)" -c 'import sys; print(sys.executable)' 2>/dev/null || command -v "$(PYTHON)" 2>/dev/null || printf '%s' "$(PYTHON)")
CMAKE_PYTHON_ARGS ?= -DPython3_EXECUTABLE:FILEPATH=$(PYTHON_EXECUTABLE)
JOBS   ?= $(shell nproc 2>/dev/null || getconf _NPROCESSORS_ONLN || echo 1)
BUILD_ROOT ?= build
CMAKE_BUILD_ROOT_ARGS ?= -DFETCHCONTENT_BASE_DIR:PATH=$(abspath $(BUILD_ROOT)/_deps)

DOCKER             ?= docker
DOCKER_IMAGE       ?= rch-dev:local
DOCKER_WORKDIR     ?= /work/rch
DOCKER_RUN_FLAGS   ?= --rm
DOCKER_USER_FLAGS  ?=
DOCKER_INNER_MAKE  ?= make
DOCKER_BUILD_ROOT  ?= docker-build
DOCKER_MAKE_TARGETS = \
	help clean clean-artifacts format \
	configure build debug test tests test-pyramid \
	test-unit test-property test-oracle test-python \
	test-regression test-determinism \
	examples example-basic \
	release release-clang release-gcc test-release \
	asan ubsan tsan fuzz coverage repro repro-smoke test-smoke \
	bench-cpp cgal-adapter-bin cgal-adapter bench-test bench-micro bench-micro-run \
	bench-synthetic	bench-real bench paper-artifacts test-integration \
	test-cgal test-cli \
	demo-data cgal-demo-appendix bench-demo-synthetic bench-demo-real \
	paper-artifacts-demo verify-demo bench-demo \
	test-all paper-all paper-pdf \
	test-fuzz test-fuzz-soak ci-clang ci-gcc test-all-presets \
	all-targets all

BENCH_PRESET     ?= bench
COVERAGE_PRESET  ?= coverage
CGAL_BUILD_TYPE  ?= Release
CLI_BUILD_DIR    ?= $(BUILD_ROOT)/src-tools
EXAMPLES_BUILD_DIR ?= $(BUILD_ROOT)/examples

RCH_ORDER_BIN        ?= $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_order
CGAL_ADAPTER_BIN     ?= $(BUILD_ROOT)/cgal-adapter/adapters/cgal/rch_cgal_spatial_sort
BLOCK_READ_PROBE_BIN ?= $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_block_read_probe
CLI_ORDER_BIN        ?= $(CLI_BUILD_DIR)/src/cli/rch_order
CLI_COMPARE_BIN      ?= $(CLI_BUILD_DIR)/src/cli/rch_compare_orders
CLI_BLOCK_PROBE_BIN  ?= $(CLI_BUILD_DIR)/src/cli/rch_block_read_probe
RCH_BASIC_ORDER_BIN  ?= $(EXAMPLES_BUILD_DIR)/examples/rch_basic_order

SYNTHETIC_OUTPUT_DIR ?= experiments/outputs/synthetic_dataset
REAL_OUTPUT_DIR      ?= experiments/outputs/real_dataset
A7_OUTPUT_DIR  ?= experiments/outputs/a7_cgal_appendix
PRIMARY_REFINEMENT ?= off

# Refinement-axis ablations write self-contained arms under
# $(SYNTHETIC_OUTPUT_DIR)/<mode>/ and $(REAL_OUTPUT_DIR)/<mode>/. The arms are
# declared once in experiments/configs/sweeps/refinement.yaml; override the
# per-dataset variables to run a subset.
REFINEMENT_MODES ?= $(shell "$(PYTHON)" -c "import yaml; print(' '.join(m['id'] for m in yaml.safe_load(open('experiments/configs/sweeps/refinement.yaml'))['modes']))")
SYNTHETIC_REFINE_MODES ?= $(REFINEMENT_MODES)
REAL_REFINE_MODES ?= $(REFINEMENT_MODES)
SYNTHETIC_PRIMARY_RESULTS_DIR ?= $(SYNTHETIC_OUTPUT_DIR)/$(PRIMARY_REFINEMENT)
REAL_PRIMARY_RESULTS_DIR      ?= $(REAL_OUTPUT_DIR)/$(PRIMARY_REFINEMENT)

DEMO_OUTPUT_ROOT ?= experiments/outputs/demo
DEMO_GENERATED_DIR ?= analysis/generated/demo
DEMO_SYNTHETIC_OUTPUT_DIR ?= $(DEMO_OUTPUT_ROOT)/synthetic_dataset
DEMO_REAL_OUTPUT_DIR      ?= $(DEMO_OUTPUT_ROOT)/real_dataset
DEMO_A7_OUTPUT_DIR        ?= $(DEMO_OUTPUT_ROOT)/a7_cgal_appendix
DEMO_RAW_DIR              ?= data/raw/rch_demo
DEMO_PROCESSED_DIR        ?= data/processed/rch_demo
DEMO_SOURCE_DIR           ?= data/demo/source
DEMO_MANIFEST             ?= data/manifests/rch_demo.yml
DEMO_REAL_CATALOG         ?= data/manifests/rch_demo_real_dataset_catalog.yml
DEMO_RUNLIST_DIR          ?= experiments/runlists/demo
DEMO_SYNTHETIC_LOCALITY_RUNLIST ?= $(DEMO_RUNLIST_DIR)/table_3_locality.yaml
DEMO_SYNTHETIC_OUTLIER_RUNLIST  ?= $(DEMO_RUNLIST_DIR)/table_4_outlier.yaml
DEMO_SYNTHETIC_RUNTIME_RUNLIST  ?= $(DEMO_RUNLIST_DIR)/table_5_runtime.yaml
DEMO_REAL_RUNLIST              ?= $(DEMO_RUNLIST_DIR)/table_2_dataset_summary.yaml

STANFORD_MANIFEST       ?= data/manifests/stanford_3d_scanning.yml
STANFORD_RAW_DIR        ?= data/raw/stanford_3d_scanning
STANFORD_PROCESSED_DIR  ?= data/processed/stanford_3d_scanning

# CTest regexes
RE_PROPERTY       := Property
RE_ORACLE         := Oracle|Cutoff
RE_REGRESSION     := Reproducibility|CrossToolchain
RE_DETERMINISM    := Determinism|CrossToolchain
RE_PY_UNIT_SYNTHETIC_REAL  := synthetic_python_pipeline|real_python_pipeline|reference_r_baselines|scripts_python_tools
RE_PY_INTEGRATION := paper_artifacts_python
RE_PY_ALL         := $(RE_PY_UNIT_SYNTHETIC_REAL)|$(RE_PY_INTEGRATION)
RE_UNIT_EXCLUDE   := $(RE_PROPERTY)|$(RE_ORACLE)|$(RE_REGRESSION)|$(RE_DETERMINISM)|$(RE_PY_ALL)

FUZZ_SOAK_SECONDS ?= 86400
FUZZ_SOAK_TARGET  ?= fuzz_preprocessing

# Google Benchmark micro-bench executables under benchmarks/.
BENCH_MICRO_BINS ?= \
	bench_quantization \
	bench_sfc_keygen \
	bench_sort \
	bench_metrics_knn \
	bench_ordering \
	bench_detmcd \
	bench_io

# Per-iteration wall-clock budget for `bench-micro-run`. Override on the
# command line for deeper profiles (e.g. `make bench-micro-run BENCH_MICRO_TIME=2s`).
BENCH_MICRO_TIME ?= 0.2s

.PHONY: \
	help \
	clean clean-artifacts format \
	configure build debug \
	examples example-basic \
	test tests test-pyramid \
	test-unit test-property test-oracle test-python \
	test-regression test-determinism \
	test-release release release-clang release-gcc \
	asan ubsan tsan fuzz coverage \
	repro repro-smoke test-smoke \
	bench-cpp cgal-adapter-bin cgal-adapter \
	bench-micro bench-micro-run \
	bench-synthetic \
	bench-real \
	demo-data demo-determinism-log cgal-demo-appendix bench-demo-synthetic bench-demo-real \
	paper-artifacts-demo verify-demo bench-demo \
	bench bench-test paper-artifacts paper-all paper-pdf \
	test-integration test-cli test-all \
	ci-clang ci-gcc test-all-presets \
	test-fuzz test-fuzz-soak \
	docker-image docker-shell \
	all-targets all

# ════════════════════════════════════════════════════════════════════════
# L0 — NO DEPENDENCIES (help, formatting, cleanup)
# ════════════════════════════════════════════════════════════════════════
help:
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "RCH Makefile — hierarchical test/build pyramid"
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "L0 — NO DEPENDENCIES:"
	@echo "  make help                  Show this help"
	@echo "  make format                Apply clang-format in-place"
	@echo "  make clean                 Remove $(BUILD_ROOT)/ and Python caches"
	@echo "  make clean-artifacts       Remove generated artifacts"
	@echo ""
	@echo "L1 — DEBUG BUILD ONLY (artifact-INDEPENDENT pyramid):"
	@echo "  make configure / build     Configure / compile debug preset"
	@echo "  make examples              Build header-only usage examples"
	@echo "  make example-basic         Build + run examples/basic_order.cpp smoke demo"
	@echo "  make test-unit             GoogleTest unit suite"
	@echo "  make test-property         Parametric property suite"
	@echo "  make test-oracle           Pinned oracle vectors"
	@echo "  make test-regression       Tiny-cloud + cross-toolchain"
	@echo "  make test-determinism      Determinism + cross-toolchain"
	@echo "  make test-python           Synthetic/Real python pipeline (unit)"
	@echo "  make test / tests          ★ L1 aggregate (pyramid, no artifacts)"
	@echo ""
	@echo "L2 — OTHER PRESETS (release / sanitizers / coverage):"
	@echo "  make release / release-clang / release-gcc"
	@echo "  make test-release          ctest on release preset"
	@echo "  make asan / ubsan / tsan   Sanitizer build+test"
	@echo "  make fuzz                  libFuzzer + ASan/UBSan smoke"
	@echo "  make coverage              Coverage build+report"
	@echo "  make repro                 Reproducible build flags"
	@echo "  make repro-smoke           Reproducibility smoke (<30s)"
	@echo "  make test-smoke            alias for repro-smoke"
	@echo ""
	@echo "L3 — EXPERIMENT ARTIFACTS:"
	@echo "  make bench-cpp             Configure bench preset + build CLIs"
	@echo "  make bench-micro           Build Google Benchmark micro-benches"
	@echo "  make bench-micro-run       Build + smoke-run all micro-benches"
	@echo "                             (override BENCH_MICRO_TIME=2s for deeper runs)"
	@echo "  make cgal-adapter-bin      Build optional A7 CGAL spatial_sort adapter"
	@echo "  make cgal-adapter          Build adapter + run optional A7 CGAL appendix"
	@echo "  make test-cgal             Build adapter + run CGAL adapter smoke test"
	@echo "  make test-cli              Build developer CLIs + run CLI smoke test"
	@echo "  make bench-synthetic       Run synthetic dataset matrix"
	@echo "  make bench-real            Run real dataset matrix (Network required!)"
	@echo "                             PRIMARY_REFINEMENT=$(PRIMARY_REFINEMENT); synthetic sweep=$(SYNTHETIC_REFINE_MODES); real sweep=$(REAL_REFINE_MODES)"
	@echo "  make bench                 Synthetic + Real + paper-artifacts"
	@echo "  make paper-artifacts       Render figures + tables"
	@echo "  make bench-demo            Demo data through canonical synthetic+real artifact checks"
	@echo "  make test-integration      Artifact-BOUND coverage gates"
	@echo "  make test-all              L1 pyramid + CLI + L3 integration + smoke"
	@echo "  make paper-all             format → bench → artifacts"
	@echo "  make paper-pdf             Compile paper/ → paper/build/manuscript.pdf"
	@echo ""
	@echo "L∞ — COMPREHENSIVE:"
	@echo "  make all-targets           ★ L0→L1→L2→L3 in order, end to end."
	@echo "                             Excludes 24h fuzz-soak and ci-* matrix."
	@echo ""
	@echo "DOCKER:"
	@echo "  make docker-image          Build the Docker image ($(DOCKER_IMAGE))"
	@echo "  make docker-shell          Open a shell in the Docker image"
	@echo "  make docker-<target>       Run any listed Make target inside Docker"
	@echo "                             e.g. docker-test, docker-coverage, docker-asan"
	@echo "  DOCKER_USER_FLAGS=...      Optional user flags for rootful Docker"
	@echo ""
	@echo "OPT-IN / MANUAL:"
	@echo "  make test-fuzz             alias for fuzz (libFuzzer smoke)"
	@echo "  make test-fuzz-soak        24h libFuzzer soak (CI-nightly)"
	@echo "  make ci-clang / ci-gcc     CI matrix (debug + cross-compiler)"
	@echo "  make test-all-presets      Run tests across every preset"
	@echo "  make all                   Legacy: clean+format+release+all-presets"
	@echo ""
	@echo "Default compiler: Clang 20. See CMakePresets.json."
	@echo "═══════════════════════════════════════════════════════════════════"

format:
	@echo "[L0/format] clang-format in-place (include/ + src/)"
	bash scripts/format.sh

clean:
	@echo "[L0/clean] Removing $(BUILD_ROOT)/ and Python bytecode caches"
	@if [ -z "$(strip $(BUILD_ROOT))" ] || [ "$(BUILD_ROOT)" = "/" ] || [ "$(BUILD_ROOT)" = "." ]; then \
		echo "[L0/clean] ERROR: unsafe BUILD_ROOT='$(BUILD_ROOT)'"; \
		exit 2; \
	fi
	rm -rf $(BUILD_ROOT)/
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

clean-artifacts:
	@echo "[L0/clean-artifacts] Removing generated artifacts (preserving .gitkeep)"
	@for dir in \
		experiments/outputs \
		experiments/logs \
			data/raw \
			data/processed \
			data/cache \
			analysis/generated/outputs \
			paper/build ; do \
		if [ -d "$$dir" ]; then \
			find "$$dir" -mindepth 1 ! -name '.gitkeep' \
				-exec rm -rf {} + 2>/dev/null || true ; \
		fi ; \
	done
	@rm -f analysis/generated/figures/*.pdf 2>/dev/null || true
	@rm -f analysis/generated/figures/*.eps 2>/dev/null || true
	@rm -f analysis/generated/tables/*.tex 2>/dev/null || true
	@rm -f analysis/generated/tables/*.csv 2>/dev/null || true
	@rm -f analysis/generated/tables/*.json 2>/dev/null || true
	@rm -f analysis/generated/stats/*.json 2>/dev/null || true
	@rm -f analysis/generated/stats/*.csv 2>/dev/null || true
	@rm -rf analysis/generated/demo/ 2>/dev/null || true
	@echo "[L0/clean-artifacts] Done."

# ════════════════════════════════════════════════════════════════════════
# L1 — DEBUG BUILD (artifact-INDEPENDENT pyramid)
# ════════════════════════════════════════════════════════════════════════
configure:
	@echo "[L1/configure] Debug preset (Clang 20)"
	$(CMAKE) --preset debug -B $(BUILD_ROOT)/debug \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)

build: configure
	@echo "[L1/build] Debug preset"
	$(CMAKE) --build $(BUILD_ROOT)/debug --parallel $(JOBS)

debug: build
	@echo "[L1/debug] alias for debug preset build"

examples:
	@echo "[L1/examples] Build header-only example programs"
	$(CMAKE) -S . -B $(EXAMPLES_BUILD_DIR) \
		-DRCH_BUILD_TESTS=OFF -DRCH_BUILD_EXAMPLES=ON \
		$(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(EXAMPLES_BUILD_DIR) \
		--target rch_basic_order --parallel $(JOBS)

example-basic: examples
	@echo "[L1/example-basic] Run embedded-point RCH demo"
	$(RCH_BASIC_ORDER_BIN)
	@echo "[L1/example-basic] Run fixture RCH hybrid-occupancy variant"
	$(RCH_BASIC_ORDER_BIN) examples/tiny_point_cloud.xyz \
		--method rch \
		--frame det_mcd \
		--bit-allocator hybrid_occupancy \
		--refinement off
	@echo "[L1/example-basic] Run fixture PCA compact-Hilbert variant"
	$(RCH_BASIC_ORDER_BIN) examples/tiny_point_cloud.xyz \
		--method pca_compact_hilbert \
		--frame sample_covariance \
		--bit-allocator uniform \
		--refinement all

# Pure GoogleTest unit suite (excludes other pyramid buckets).
test-unit: build
	@echo "[L1/test-unit] GoogleTest unit suite"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-E "$(RE_UNIT_EXCLUDE)"

# Parametric property suite.
test-property: build
	@echo "[L1/test-property] Parametric property suite"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_PROPERTY)"

# Pinned reference vectors via simdjson.
test-oracle: build
	@echo "[L1/test-oracle] Pinned oracle vectors"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_ORACLE)"

# Tiny-cloud reproducibility + cross-toolchain digest.
test-regression: build
	@echo "[L1/test-regression] Regression + cross-toolchain"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_REGRESSION)"

# Determinism + cross-toolchain pinned digest.
test-determinism: build
	@echo "[L1/test-determinism] Determinism"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_DETERMINISM)"

# Python Synthetic/Real unit-level (tempdir-only; verified independent
test-python: build
	@echo "[L1/test-python] Synthetic/Real python pipeline (unit-level)"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_PY_UNIT_SYNTHETIC_REAL)"

# Aggregate L1 — what `make test` runs. Single ctest invocation that
# excludes the artifact-bound coverage gate (paper_artifacts_python ⊃
# PaperArtifactRepoCoverageTest).
test-pyramid: build
	@echo "[L1/test] Artifact-INDEPENDENT pyramid (exclude $(RE_PY_INTEGRATION))"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

test:  test-pyramid
tests: test-pyramid

# ════════════════════════════════════════════════════════════════════════
# DOCKER — run Make targets in the Ubuntu 24.04 development image.
# Every target listed in DOCKER_MAKE_TARGETS can be run with a `docker-`
# prefix, for example `make docker-coverage` → container → `make coverage`.
# The repository is bind-mounted. Rootless Docker should use the default
# user mapping; rootful Docker users can pass DOCKER_USER_FLAGS="--user UID:GID".
# ════════════════════════════════════════════════════════════════════════
docker-image:
	@echo "[docker/image] Build $(DOCKER_IMAGE)"
	$(DOCKER) build -t $(DOCKER_IMAGE) .

docker-shell: docker-image
	@echo "[docker/shell] Open $(DOCKER_IMAGE)"
	$(DOCKER) run --rm -it $(DOCKER_USER_FLAGS) \
		-e HOME=/tmp \
		-e BUILD_ROOT=$(DOCKER_BUILD_ROOT) \
		-e RCH_BUILD_ROOT=$(DOCKER_BUILD_ROOT) \
		-v "$(CURDIR):$(DOCKER_WORKDIR)" \
		-w "$(DOCKER_WORKDIR)" \
		$(DOCKER_IMAGE) bash

docker-%: docker-image
	@if printf '%s\n' $(DOCKER_MAKE_TARGETS) | grep -qx '$*'; then \
			echo "[docker/$*] Run make $* in $(DOCKER_IMAGE)"; \
				$(DOCKER) run $(DOCKER_RUN_FLAGS) $(DOCKER_USER_FLAGS) \
					-e HOME=/tmp \
					-e BUILD_ROOT=$(DOCKER_BUILD_ROOT) \
					-e RCH_BUILD_ROOT=$(DOCKER_BUILD_ROOT) \
					-v "$(CURDIR):$(DOCKER_WORKDIR)" \
					-w "$(DOCKER_WORKDIR)" \
					$(DOCKER_IMAGE) \
				$(DOCKER_INNER_MAKE) $* BUILD_ROOT=$(DOCKER_BUILD_ROOT) RCH_BUILD_ROOT=$(DOCKER_BUILD_ROOT); \
	else \
		echo "[docker/$*] ERROR: unknown docker target."; \
		echo "[docker/$*] Add '$*' to DOCKER_MAKE_TARGETS if it should be supported."; \
		exit 2; \
	fi

# ════════════════════════════════════════════════════════════════════════
# L2 — OTHER PRESETS (release / sanitizer / coverage / repro)
# Each preset writes into $(BUILD_ROOT)/<preset>/, so L2 targets are independent
# of L1's $(BUILD_ROOT)/debug/ tree.
# ════════════════════════════════════════════════════════════════════════
release:
	@echo "[L2/release] Clang 20 (default)"
	$(CMAKE) --preset release -B $(BUILD_ROOT)/release \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/release --parallel $(JOBS)

release-clang:
	@echo "[L2/release-clang] Clang 20 (explicit)"
	$(CMAKE) --preset release-clang -B $(BUILD_ROOT)/release-clang \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/release-clang --parallel $(JOBS)

release-gcc:
	@echo "[L2/release-gcc] GCC 13"
	$(CMAKE) --preset release-gcc -B $(BUILD_ROOT)/release-gcc \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/release-gcc --parallel $(JOBS)

test-release: release
	@echo "[L2/test-release] ctest on release preset"
	$(CTEST) --test-dir $(BUILD_ROOT)/release --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

asan:
	@echo "[L2/asan] AddressSanitizer (Clang)"
	$(CMAKE) --preset asan -B $(BUILD_ROOT)/asan \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/asan --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/asan --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

ubsan:
	@echo "[L2/ubsan] UndefinedBehaviorSanitizer (Clang)"
	$(CMAKE) --preset ubsan -B $(BUILD_ROOT)/ubsan \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/ubsan --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/ubsan --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

tsan:
	@echo "[L2/tsan] ThreadSanitizer (Clang)"
	$(CMAKE) --preset tsan -B $(BUILD_ROOT)/tsan \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/tsan --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/tsan --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

fuzz:
	@echo "[L2/fuzz] libFuzzer + ASan/UBSan smoke"
	$(CMAKE) --preset fuzz -B $(BUILD_ROOT)/fuzz \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/fuzz --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/fuzz --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

coverage:
	@echo "[L2/coverage] Coverage preset"
	RCH_BUILD_ROOT="$(BUILD_ROOT)" CTEST_EXCLUDE_REGEX="$(RE_PY_INTEGRATION)" bash scripts/coverage.sh

repro:
	@echo "[L2/repro] Release + reproducible flags"
	$(CMAKE) --preset repro -B $(BUILD_ROOT)/repro \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/repro --parallel $(JOBS)

repro-smoke:
	@echo "[L2/repro-smoke] Reproducibility smoke (<30s)"
	RCH_BUILD_ROOT="$(BUILD_ROOT)" CTEST_EXCLUDE_REGEX="$(RE_PY_INTEGRATION)" bash reproducibility/scripts/reproduce_smoke.sh

test-smoke: repro-smoke
	@echo "[L2/test-smoke] alias for repro-smoke"

# ════════════════════════════════════════════════════════════════════════
# L3 — EXPERIMENT ARTIFACTS + INTEGRATION GATES
# These targets produce/consume experiments/outputs/ and analysis/generated/.
# test-integration reads CSVs written by bench-synthetic/bench-real.
# ════════════════════════════════════════════════════════════════════════
bench-cpp:
	@echo "[L3/bench-cpp] Configure bench preset + build CLIs"
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) \
		--target rch_order rch_compare_orders rch_block_read_probe --parallel $(JOBS)

cgal-adapter-bin:
	@echo "[L3/cgal-adapter-bin] Build A7 CGAL spatial_sort adapter"
	$(CMAKE) -S . -B $(BUILD_ROOT)/cgal-adapter \
		-DCMAKE_BUILD_TYPE=$(CGAL_BUILD_TYPE) \
		-DRCH_WITH_CGAL=ON -DRCH_BUILD_TOOLS=ON -DRCH_BUILD_TESTS=OFF \
		$(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/cgal-adapter \
		--target rch_cgal_spatial_sort --parallel $(JOBS)

cgal-adapter: cgal-adapter-bin
	@echo "[L3/cgal-adapter] A7 CGAL spatial_sort appendix"
	$(PYTHON) experiments/runners/run_cgal_appendix.py \
		--adapter-bin $(CGAL_ADAPTER_BIN) \
		--output-dir $(A7_OUTPUT_DIR)

test-cgal: cgal-adapter-bin
	@echo "[L3/test-cgal] Optional CGAL spatial_sort adapter smoke test"
	$(PYTHON) tests/integration/test_cgal_spatial_sort_adapter.py $(CGAL_ADAPTER_BIN)

test-cli:
	@echo "[L3/test-cli] Developer CLI smoke test"
	$(CMAKE) -S . -B $(CLI_BUILD_DIR) \
		-DRCH_BUILD_TOOLS=ON -DRCH_BUILD_TESTS=OFF \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(CLI_BUILD_DIR) \
		--target rch_order rch_compare_orders rch_block_read_probe --parallel $(JOBS)
	RCH_ORDER_BIN=$(CLI_ORDER_BIN) \
	RCH_COMPARE_ORDERS_BIN=$(CLI_COMPARE_BIN) \
	RCH_BLOCK_READ_PROBE_BIN=$(CLI_BLOCK_PROBE_BIN) \
		$(PYTHON) tests/integration/test_cli_tools.py

bench-test:
	@echo "[L3/bench-test] ctest under bench preset"
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) --output-on-failure

# Build the Google Benchmark micro-bench executables only. Faster than
# `bench-test` because it skips ctest re-discovery and the unit/property
# rebuild. Listed binaries come from BENCH_MICRO_BINS so adding a new
# benchmarks/bench_*.cpp file requires updating one place.
bench-micro:
	@echo "[L3/bench-micro] Configure bench preset + build micro-benchmarks"
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) \
		--target $(BENCH_MICRO_BINS)

# Run every micro-benchmark with a uniform `--benchmark_min_time` budget
# (default 0.2s per profile — fast smoke; override BENCH_MICRO_TIME for
# longer runs). Sequential by design so wall-clock numbers stay readable;
# CPU scaling warnings come from Google Benchmark itself when governors
# are not pinned.
bench-micro-run: bench-micro
	@echo "[L3/bench-micro-run] Smoke-run all micro-benchmarks (--benchmark_min_time=$(BENCH_MICRO_TIME))"
	@for bin in $(BENCH_MICRO_BINS); do \
		echo ""; \
		echo "── $$bin ──"; \
		$(BUILD_ROOT)/$(BENCH_PRESET)/benchmarks/$$bin \
			--benchmark_min_time=$(BENCH_MICRO_TIME) \
			|| exit $$? ; \
	done

bench-synthetic: bench-cpp cgal-adapter-bin
	@echo "[L3/bench-synthetic] Synthetic dataset matrix + refinement arms"
	@if [ -z "$(strip $(SYNTHETIC_REFINE_MODES))" ]; then \
		echo "[L3/bench-synthetic] ERROR: SYNTHETIC_REFINE_MODES is empty (check experiments/configs/sweeps/refinement.yaml)"; \
		exit 1; \
	fi
	@case " $(SYNTHETIC_REFINE_MODES) " in \
		*" $(PRIMARY_REFINEMENT) "*) ;; \
		*) echo "[L3/bench-synthetic] ERROR: PRIMARY_REFINEMENT=$(PRIMARY_REFINEMENT) is not in SYNTHETIC_REFINE_MODES=$(SYNTHETIC_REFINE_MODES)"; exit 1;; \
	esac
	@echo "[L3/bench-synthetic] Writing arms under $(SYNTHETIC_OUTPUT_DIR): $(SYNTHETIC_REFINE_MODES)"
	rm -rf $(SYNTHETIC_OUTPUT_DIR)
	mkdir -p $(SYNTHETIC_OUTPUT_DIR)
	@for mode in $(SYNTHETIC_REFINE_MODES); do \
		echo "  -> refinement=$$mode"; \
		$(PYTHON) experiments/runners/run_matrix.py \
			--runlist experiments/runlists/table_3_locality.yaml \
			--output-dir $(SYNTHETIC_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--refinement $$mode \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) || exit $$?; \
		$(PYTHON) experiments/runners/run_matrix.py \
			--runlist experiments/runlists/table_4_outlier.yaml \
			--output-dir $(SYNTHETIC_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--refinement $$mode \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) || exit $$?; \
		$(PYTHON) experiments/runners/run_matrix.py \
			--runlist experiments/runlists/table_5_runtime.yaml \
			--output-dir $(SYNTHETIC_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--block-read-probe-bin $(BLOCK_READ_PROBE_BIN) \
			--refinement $$mode \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) || exit $$?; \
	done

bench-real: bench-cpp cgal-adapter-bin
	@echo "[L3/bench-real] Stanford real dataset (Network on first run)"
	$(PYTHON) scripts/download_dataset.py \
		--manifest $(STANFORD_MANIFEST) --raw-dir $(STANFORD_RAW_DIR)
	$(PYTHON) scripts/convert_dataset.py \
		--manifest $(STANFORD_MANIFEST) \
		--raw-dir $(STANFORD_RAW_DIR) \
		--processed-dir $(STANFORD_PROCESSED_DIR)
	@if [ -z "$(strip $(REAL_REFINE_MODES))" ]; then \
		echo "[L3/bench-real] ERROR: REAL_REFINE_MODES is empty (check experiments/configs/sweeps/refinement.yaml)"; \
		exit 1; \
	fi
	@case " $(REAL_REFINE_MODES) " in \
		*" $(PRIMARY_REFINEMENT) "*) ;; \
		*) echo "[L3/bench-real] ERROR: PRIMARY_REFINEMENT=$(PRIMARY_REFINEMENT) is not in REAL_REFINE_MODES=$(REAL_REFINE_MODES)"; exit 1;; \
	esac
	rm -rf $(REAL_OUTPUT_DIR)
	mkdir -p $(REAL_OUTPUT_DIR)
	@echo "[L3/bench-real] Writing refinement arms under $(REAL_OUTPUT_DIR): $(REAL_REFINE_MODES)"
	@for mode in $(REAL_REFINE_MODES); do \
		echo "  -> refinement=$$mode"; \
		$(PYTHON) experiments/runners/run_real_datasets.py \
			--runlist experiments/runlists/table_2_dataset_summary.yaml \
			--output-dir $(REAL_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) \
			--refinement $$mode || exit $$?; \
	done

demo-data:
	@echo "[L3/demo-data] Generate deterministic demo data + canonical runlists"
	chmod +x tools/demo/perf
	$(PYTHON) scripts/create_demo_dataset.py \
		--source-dir $(DEMO_SOURCE_DIR) \
		--manifest $(DEMO_MANIFEST) \
		--processed-dir $(DEMO_PROCESSED_DIR) \
		--real-catalog $(DEMO_REAL_CATALOG) \
		--synthetic-locality-runlist $(DEMO_SYNTHETIC_LOCALITY_RUNLIST) \
		--synthetic-outlier-runlist $(DEMO_SYNTHETIC_OUTLIER_RUNLIST) \
		--synthetic-runtime-runlist $(DEMO_SYNTHETIC_RUNTIME_RUNLIST) \
		--real-runlist $(DEMO_REAL_RUNLIST) \
		--a7-output-dir $(DEMO_A7_OUTPUT_DIR)

bench-demo-synthetic: bench-cpp cgal-adapter-bin demo-data
	@echo "[L3/bench-demo-synthetic] Canonical synthetic matrix with off/all refinement"
	rm -rf $(DEMO_SYNTHETIC_OUTPUT_DIR)
	mkdir -p $(DEMO_SYNTHETIC_OUTPUT_DIR)
	@for mode in $(SYNTHETIC_REFINE_MODES); do \
		echo "  -> demo synthetic refinement=$$mode"; \
		PATH="$(abspath tools/demo):$$PATH" $(PYTHON) experiments/runners/run_matrix.py \
			--runlist $(DEMO_SYNTHETIC_LOCALITY_RUNLIST) \
			--output-dir $(DEMO_SYNTHETIC_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) \
			--refinement $$mode || exit $$?; \
		PATH="$(abspath tools/demo):$$PATH" $(PYTHON) experiments/runners/run_matrix.py \
			--runlist $(DEMO_SYNTHETIC_OUTLIER_RUNLIST) \
			--output-dir $(DEMO_SYNTHETIC_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) \
			--refinement $$mode || exit $$?; \
		PATH="$(abspath tools/demo):$$PATH" $(PYTHON) experiments/runners/run_matrix.py \
			--runlist $(DEMO_SYNTHETIC_RUNTIME_RUNLIST) \
			--output-dir $(DEMO_SYNTHETIC_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--block-read-probe-bin $(BLOCK_READ_PROBE_BIN) \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) \
			--refinement $$mode || exit $$?; \
	done

bench-demo-real: bench-cpp cgal-adapter-bin demo-data
	@echo "[L3/bench-demo-real] Demo file-backed real matrix with off/all refinement"
	rm -rf $(DEMO_REAL_OUTPUT_DIR)
	rm -rf $(DEMO_RAW_DIR)
	rm -rf $(DEMO_PROCESSED_DIR)
	$(PYTHON) scripts/download_dataset.py \
		--manifest $(DEMO_MANIFEST) --raw-dir $(DEMO_RAW_DIR)
	$(PYTHON) scripts/convert_dataset.py \
		--manifest $(DEMO_MANIFEST) \
		--raw-dir $(DEMO_RAW_DIR) \
		--processed-dir $(DEMO_PROCESSED_DIR)
	mkdir -p $(DEMO_REAL_OUTPUT_DIR)
	@for mode in $(REAL_REFINE_MODES); do \
		echo "  -> demo real refinement=$$mode"; \
		$(PYTHON) experiments/runners/run_real_datasets.py \
			--runlist $(DEMO_REAL_RUNLIST) \
			--output-dir $(DEMO_REAL_OUTPUT_DIR)/$$mode \
			--rch-order-bin $(RCH_ORDER_BIN) \
			--cgal-adapter-bin $(CGAL_ADAPTER_BIN) \
			--refinement $$mode || exit $$?; \
	done

cgal-demo-appendix: cgal-adapter-bin demo-data
	@echo "[L3/cgal-demo-appendix] Demo A7 CGAL spatial_sort appendix"
	rm -rf $(DEMO_A7_OUTPUT_DIR)
	$(PYTHON) experiments/runners/run_cgal_appendix.py \
		--adapter-bin $(CGAL_ADAPTER_BIN) \
		--output-dir $(DEMO_A7_OUTPUT_DIR)

demo-determinism-log: bench-demo-synthetic bench-demo-real cgal-demo-appendix
	@echo "[L3/demo-determinism-log] Record demo pipeline evidence for paper tables"
	$(PYTHON) scripts/write_demo_test_log.py \
		--logs-dir experiments/logs \
		--preset bench-demo

paper-artifacts-demo: bench-demo-synthetic bench-demo-real cgal-demo-appendix demo-determinism-log
	@echo "[L3/paper-artifacts-demo] Render paper artifacts from demo outputs"
	$(PYTHON) analysis/scripts/make_tables.py \
		--results-dir $(DEMO_SYNTHETIC_OUTPUT_DIR)/$(PRIMARY_REFINEMENT) \
		--tables-dir $(DEMO_GENERATED_DIR)/tables \
		--stats-dir $(DEMO_GENERATED_DIR)/stats
	$(PYTHON) analysis/scripts/make_real_tables.py \
		--results-dir $(DEMO_REAL_OUTPUT_DIR)/$(PRIMARY_REFINEMENT) \
		--tables-dir $(DEMO_GENERATED_DIR)/tables \
		--stats-dir $(DEMO_GENERATED_DIR)/stats
	MPLCONFIGDIR=/tmp/matplotlib-rch-demo $(PYTHON) analysis/scripts/make_paper_artifacts.py \
		--synthetic-results-dir $(DEMO_SYNTHETIC_OUTPUT_DIR)/$(PRIMARY_REFINEMENT) \
		--synthetic-refinement-results-dir $(DEMO_SYNTHETIC_OUTPUT_DIR) \
		--real-results-dir $(DEMO_REAL_OUTPUT_DIR)/$(PRIMARY_REFINEMENT) \
		--real-refinement-results-dir $(DEMO_REAL_OUTPUT_DIR) \
		--a7-results-dir $(DEMO_A7_OUTPUT_DIR) \
		--logs-dir experiments/logs \
		--figures-dir $(DEMO_GENERATED_DIR)/figures \
		--outputs-dir $(DEMO_GENERATED_DIR)/outputs \
		--tables-dir $(DEMO_GENERATED_DIR)/tables \
		--stats-dir $(DEMO_GENERATED_DIR)/stats \
		--dataset-catalog $(DEMO_REAL_CATALOG)

verify-demo: paper-artifacts-demo
	@echo "[L3/verify-demo] Check demo output layout, copies, and refinement effects"
	$(PYTHON) scripts/verify_demo_artifacts.py \
		--synthetic-dir $(DEMO_SYNTHETIC_OUTPUT_DIR) \
		--real-dir $(DEMO_REAL_OUTPUT_DIR) \
		--outputs-dir $(DEMO_GENERATED_DIR)/outputs \
		--tables-dir $(DEMO_GENERATED_DIR)/tables \
		--stats-dir $(DEMO_GENERATED_DIR)/stats \
		--manifest $(DEMO_MANIFEST) \
		--real-catalog $(DEMO_REAL_CATALOG) \
		--runlist-dir $(DEMO_RUNLIST_DIR) \
		--logs-dir experiments/logs \
		--repo-root .

bench-demo: verify-demo
	@echo "[L3/bench-demo] Demo benchmark pipeline PASSED"

paper-artifacts: cgal-adapter
	@echo "[L3/paper-artifacts] Render figures + tables from existing outputs"
	$(PYTHON) analysis/scripts/make_tables.py \
		--results-dir $(SYNTHETIC_PRIMARY_RESULTS_DIR) \
		--tables-dir analysis/generated/tables \
		--stats-dir analysis/generated/stats
	$(PYTHON) analysis/scripts/make_real_tables.py \
		--results-dir $(REAL_PRIMARY_RESULTS_DIR) \
		--tables-dir analysis/generated/tables \
		--stats-dir analysis/generated/stats
	$(PYTHON) analysis/scripts/make_paper_artifacts.py \
		--synthetic-results-dir $(SYNTHETIC_PRIMARY_RESULTS_DIR) \
		--synthetic-refinement-results-dir $(SYNTHETIC_OUTPUT_DIR) \
		--real-results-dir $(REAL_PRIMARY_RESULTS_DIR) \
		--real-refinement-results-dir $(REAL_OUTPUT_DIR) \
		--a7-results-dir $(A7_OUTPUT_DIR) \
		--logs-dir experiments/logs \
		--figures-dir analysis/generated/figures \
		--outputs-dir analysis/generated/outputs \
		--tables-dir analysis/generated/tables \
		--stats-dir analysis/generated/stats
	@command -v pdftops >/dev/null 2>&1 || { \
		echo "[paper-artifacts] ERROR: pdftops not found (install poppler-utils for EPS)."; exit 2; }
	@echo "[L3/paper-artifacts] Emit PostScript (EPS) copies of each figure"
	@for f in analysis/generated/figures/*.pdf; do \
		case "$$f" in *-eps-converted-to.pdf) continue;; esac; \
		pdftops -eps "$$f" "$${f%.pdf}.eps" || exit 1; \
	done

bench: bench-synthetic bench-real
	@echo "[L3/bench] Running tests + generating log for determinism evidence"
	RCH_BUILD_ROOT="$(BUILD_ROOT)" bash scripts/test.sh $(BENCH_PRESET)
	$(MAKE) paper-artifacts
	@echo "[L3/bench] Synthetic + Real + paper artifacts regenerated"

# Artifact-bound coverage gate. Fails fast if Synthetic/Real outputs are missing.
test-integration: build
	@echo "[L3/test-integration] Artifact-bound paper-artifact coverage gates"
	@if [ ! -f "$(SYNTHETIC_PRIMARY_RESULTS_DIR)/table_3_locality.csv" ] || \
	    [ ! -f "$(REAL_PRIMARY_RESULTS_DIR)/table_2_dataset_summary.csv" ]; then \
		echo "[L3/test-integration] ERROR: Synthetic/Real outputs missing under experiments/outputs/."; \
		echo "[L3/test-integration] Run 'make bench' first, then re-run 'make test-integration'."; \
		exit 2; \
	fi
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_PY_INTEGRATION)"

test-all: test-pyramid test-cli test-integration test-smoke
	@echo "[L3/test-all] L1 pyramid + CLI + L3 integration + smoke PASSED"

paper-all: override BENCH_PRESET := bench
paper-all: override CGAL_BUILD_TYPE := Release
paper-all: override RCH_ORDER_BIN = $(BUILD_ROOT)/bench/src/cli/rch_order
paper-all: override BLOCK_READ_PROBE_BIN = $(BUILD_ROOT)/bench/src/cli/rch_block_read_probe
paper-all: format bench
	@echo "[L3/paper-all] format → bench"
	@mkdir -p analysis/generated/figures analysis/generated/tables \
		analysis/generated/stats experiments/outputs

PDFLATEX ?= pdflatex
BIBTEX   ?= bibtex
PDFTOTEXT ?= pdftotext

paper-pdf:
	@command -v $(PDFLATEX) >/dev/null 2>&1 || { \
		echo "[paper-pdf] ERROR: $(PDFLATEX) not found (install TeX Live)."; exit 2; }
	@command -v $(BIBTEX) >/dev/null 2>&1 || { \
		echo "[paper-pdf] ERROR: $(BIBTEX) not found (install TeX Live)."; exit 2; }
	@mkdir -p paper/build
	cd paper && $(PDFLATEX) -shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build manuscript.tex
	cd paper && $(BIBTEX) build/manuscript.aux
	cd paper && $(PDFLATEX) -shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build manuscript.tex
	cd paper && $(PDFLATEX) -shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build manuscript.tex
	@! grep -q 'Citation .* undefined' paper/build/manuscript.log || { \
		echo "[paper-pdf] ERROR: undefined citations remain."; exit 3; }
	@echo "[paper-pdf] OK → paper/build/manuscript.pdf"

# ════════════════════════════════════════════════════════════════════════
# OPT-IN / MANUAL — excluded from `all-targets`.
# Reason: test-fuzz-soak is 24h; ci-* duplicate L1's debug+ctest path.
# ════════════════════════════════════════════════════════════════════════
test-fuzz: fuzz
	@echo "[opt-in/test-fuzz] alias for fuzz preset"

test-fuzz-soak:
	@echo "[opt-in/test-fuzz-soak] $(FUZZ_SOAK_SECONDS)s on $(FUZZ_SOAK_TARGET)"
	$(CMAKE) --preset fuzz -B $(BUILD_ROOT)/fuzz \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/fuzz --target $(FUZZ_SOAK_TARGET) --parallel $(JOBS)
	./$(BUILD_ROOT)/fuzz/tests/fuzz/$(FUZZ_SOAK_TARGET) \
		-max_total_time=$(FUZZ_SOAK_SECONDS) \
		-print_final_stats=1 -timeout=30 -rss_limit_mb=2048

ci-clang:
	@echo "[opt-in/ci-clang] Debug + Clang 20"
	$(CMAKE) --preset ci-clang -B $(BUILD_ROOT)/ci-clang \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/ci-clang --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/ci-clang --parallel $(JOBS) --output-on-failure

ci-gcc:
	@echo "[opt-in/ci-gcc] Debug + GCC 13"
	$(CMAKE) --preset ci-gcc -B $(BUILD_ROOT)/ci-gcc \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/ci-gcc --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/ci-gcc --parallel $(JOBS) --output-on-failure

test-all-presets:
	@echo "[opt-in/test-all-presets] Tests across every preset"
	RCH_BUILD_ROOT="$(BUILD_ROOT)" bash scripts/run_all_tests.sh
	@echo "[opt-in/test-all-presets] Reproducibility smoke"
	RCH_BUILD_ROOT="$(BUILD_ROOT)" bash reproducibility/scripts/reproduce_smoke.sh

# Legacy comprehensive target preserved for any external script that
# depends on it. New code should prefer `all-targets`.
all: clean format release-gcc release-clang test-all-presets
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "✓ Legacy `all` complete: clean + format + cross-compiler + matrix"
	@echo "═══════════════════════════════════════════════════════════════════"

# ════════════════════════════════════════════════════════════════════════
# L∞ — COMPREHENSIVE: every level in dependency order.
# Walks L0 → L1 → L2 → L3. Each phase is a recursive $(MAKE) so a failure
# inside (say) sanitizers surfaces with a clear phase label and bails out
# before the bench phase wastes time. Excluded by design:
#   • test-fuzz-soak  — 24h budget; nightly-only.
#   • ci-clang/ci-gcc — re-run of L1's debug+ctest; pure duplication.
# ════════════════════════════════════════════════════════════════════════
all-targets:
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "L∞/all-targets — L0 → L1 → L2 → L3 (every dependency level)"
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "── Phase L0/cleanup ──"
	$(MAKE) clean
	$(MAKE) clean-artifacts
	@echo ""
	@echo "── Phase L0/format ──"
	$(MAKE) format
	@echo ""
	@echo "── Phase L1/pyramid (debug build + artifact-free tests) ──"
	$(MAKE) test-pyramid
	@echo ""
	@echo "── Phase L2/release builds ──"
	$(MAKE) release-clang
	$(MAKE) release-gcc
	$(MAKE) test-release
	@echo ""
	@echo "── Phase L2/sanitizers + coverage ──"
	$(MAKE) asan
	$(MAKE) ubsan
	$(MAKE) tsan
	$(MAKE) fuzz
	$(MAKE) coverage
	@echo ""
	@echo "── Phase L2/reproducibility ──"
	$(MAKE) repro
	$(MAKE) repro-smoke
	@echo ""
	@echo "── Phase L3/benchmarks + paper artifacts ──"
	$(MAKE) bench
	@echo ""
	@echo "── Phase L3/integration gates ──"
	$(MAKE) test-cli
	$(MAKE) test-cgal
	$(MAKE) test-integration
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "✓ all-targets: every dependency level passed."
	@echo "  Excluded (opt-in only): test-fuzz-soak (24h), ci-clang, ci-gcc."
	@echo "═══════════════════════════════════════════════════════════════════"
