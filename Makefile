# RCH Makefile — convenience layer over CMake/CTest.
#
# DESIGN — HIERARCHICAL DEPENDENCY PYRAMID
# ════════════════════════════════════════════════════════════════════════
#  L0  No dependencies     │  help, venv, archive, format, clean, clean-artifacts
#                          │  clean-data (manual; excluded from all-targets)
#  L1  Needs debug build   │  test-unit, test-property, test-oracle,
#                          │  test-python, test-regression, test-determinism
#                          │     aggregate: `make test` (artifact-free)
#  L2  Needs other presets │  test-release, asan, ubsan, tsan, fuzz,
#                          │  coverage, repro-smoke
#  L3  Needs experiment    │  bench-cpp, cgal-adapter, bench-synthetic, bench-real,
#       artifacts          │  bench-independent, bench-cgal, app-query,
#                          │  paper-artifacts, test-cgal, test-integration
#                          │     aggregate: `make bench` produces artifacts;
#                          │      `make test-integration` validates them.
#  L∞  Comprehensive       │  `make all-targets` — prepares data, then L0→L1→L2→L3.
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

CMAKE  ?= cmake
CTEST  ?= ctest
ifdef VIRTUAL_ENV
PYTHON ?= $(VIRTUAL_ENV)/bin/python
else
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
endif
VENV_DIR ?= .venv
VENV_PYTHON ?= python3
PYTHON_EXECUTABLE := $(shell "$(PYTHON)" -c 'import sys; print(sys.executable)' 2>/dev/null || command -v "$(PYTHON)" 2>/dev/null || printf '%s' "$(PYTHON)")
CMAKE_PYTHON_ARGS ?= -DPython3_EXECUTABLE:FILEPATH=$(PYTHON_EXECUTABLE)
JOBS   ?= $(shell nproc 2>/dev/null || getconf _NPROCESSORS_ONLN || echo 1)
BUILD_ROOT ?= build
CMAKE_BUILD_ROOT_ARGS ?= -DFETCHCONTENT_BASE_DIR:PATH=$(abspath $(BUILD_ROOT)/_deps)
CGAL_DIR ?= $(HOME)/.local/opt/CGAL-6.2.1

DOCKER             ?= docker
DOCKER_IMAGE       ?= rch-dev:local
DOCKER_WORKDIR     ?= /work/rch
DOCKER_RUN_FLAGS   ?= --rm
DOCKER_USER_FLAGS  ?=
DOCKER_INNER_MAKE  ?= make
DOCKER_BUILD_ROOT  ?= docker-build
DOCKER_MAKE_TARGETS = \
	help venv archive clean clean-artifacts clean-data download-data format \
	configure build debug test tests test-pyramid \
	test-unit test-property test-oracle test-python \
	test-regression test-determinism \
	examples example-basic \
	release release-clang release-gcc test-release \
	asan ubsan tsan fuzz coverage repro repro-smoke test-smoke \
	bench-cpp cgal-adapter-bin cgal-adapter bench-test bench-micro bench-micro-run \
	bench-synthetic bench-real bench-independent bench-cgal real-data \
	app-query-smoke app-query app-query-analysis analyze-independent \
	tree-build test-tree bench-tree tree-analysis \
	test-dbms bench-dbms dbms-analysis \
	test-frame-stability bench-regime test-regime \
	bench paper-artifacts test-integration \
	test-cgal test-cli \
	demo-data cgal-demo-appendix bench-demo-synthetic bench-demo-real \
	paper-artifacts-demo verify-demo bench-demo \
	test-all paper-all paper-pdf \
	test-fuzz test-fuzz-soak ci-clang ci-gcc test-all-presets \
	bench-extended bench-clamping-intervention bench-cost-stability \
	measurement-diagnostics validate-extended-benchmarks extended-benchmark-artifacts \
	plan-benchmark-rerun rerun-benchmarks plan-benchmark-resume resume-benchmarks \
	plan-application-cache bench-application-cache resume-application-cache validate-application-cache \
	test-measurement-integrity test-benchmark-resume test-clamping-intervention test-cost-stability \
	fallback-evidence test-fallback-evidence validate-fallback-evidence test-application-cache \
	all-targets all

BENCH_PRESET     ?= bench
RELEASE_TEST_PRESET ?= release
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
INDEPENDENT_OUTPUT_DIR ?= experiments/outputs/independent_benchmarks
REGIME_OUTPUT_DIR ?= $(INDEPENDENT_OUTPUT_DIR)/regime_map
C1_RESOLUTION_OUTPUT_DIR ?= experiments/outputs/c1_resolution_ablation
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
NOAA_MANIFEST ?= data/manifests/noaa_lidar.yml
NOAA_RAW_DIR ?= data/raw/noaa_lidar
NOAA_PROCESSED_DIR ?= data/processed/noaa_lidar
USGS_MANIFEST ?= data/manifests/usgs_3dep.yml
USGS_RAW_DIR ?= data/raw/usgs_3dep
USGS_PROCESSED_DIR ?= data/processed/usgs_3dep
APPLICATION_QUERY_DATASETS ?= stanford_bunny stanford_armadillo stanford_dragon usgs_cameron_peak noaa_santiam_river noaa_long_island noaa_southwest_florida
APPLICATION_QUERY_REPEATS ?= 5
APPLICATION_ORDERING_REPEATS ?= 5
APPLICATION_QUERY_SMOKE_DIR ?= experiments/outputs/application_query/make_smoke
APPLICATION_QUERY_OUTPUT_DIR ?= experiments/outputs/application_query/full_benchmark
APPLICATION_QUERY_ANALYSIS_DIR ?= $(APPLICATION_QUERY_OUTPUT_DIR)/analysis
APPLICATION_QUERY_DATASET_ARGS = $(foreach dataset,$(APPLICATION_QUERY_DATASETS),--dataset $(dataset))
TREE_OUTPUT_DIR ?= experiments/outputs/tree_benchmark/full_benchmark
TREE_BIN ?= $(BUILD_ROOT)/tree/adapters/cgal/rch_cgal_tree_benchmark
TREE_CXX ?= clang++
TREE_REPEATS ?= 5
TREE_BUCKET ?= 128
TREE_DATASETS ?=
DBMS_OUTPUT_DIR ?= experiments/outputs/dbms_benchmark/full_benchmark
DBMS_MODE ?= managed
DBMS_REPEATS ?= 5
DBMS_DATASETS ?=

# Artifact readers may reuse a completed alternate run without redirecting writers.
# Prefer the canonical full matrix; closure is a fallback only when it is complete.
ARTIFACT_READER_TARGETS := paper-artifacts test-integration tree-analysis dbms-analysis fallback-evidence c1-diagnostics
ARTIFACT_INDEPENDENT_ROOT = $(if $(and $(wildcard experiments/outputs/independent_benchmarks/benchmark_manifest.json),$(wildcard experiments/outputs/independent_benchmarks/regime_map/run_manifest.json)),experiments/outputs/independent_benchmarks,$(if $(and $(wildcard experiments/outputs/independent_benchmarks_closure/benchmark_manifest.json),$(wildcard experiments/outputs/independent_benchmarks_closure/regime_map/run_manifest.json)),experiments/outputs/independent_benchmarks_closure,experiments/outputs/independent_benchmarks))
ifeq ($(origin INDEPENDENT_OUTPUT_DIR),file)
$(ARTIFACT_READER_TARGETS): INDEPENDENT_OUTPUT_DIR = $(ARTIFACT_INDEPENDENT_ROOT)
endif
ifeq ($(origin REAL_OUTPUT_DIR),file)
$(ARTIFACT_READER_TARGETS): REAL_OUTPUT_DIR = $(if $(filter experiments/outputs/independent_benchmarks_closure,$(INDEPENDENT_OUTPUT_DIR)),experiments/outputs/real_dataset_closure,experiments/outputs/real_dataset)
endif

# CTest regexes
RE_PROPERTY       := Property
RE_ORACLE         := Oracle|Cutoff
RE_REGRESSION     := Reproducibility|CrossToolchain
RE_DETERMINISM    := Determinism|CrossToolchain
RE_PY_UNIT_SYNTHETIC_REAL  := synthetic_python_pipeline|real_python_pipeline|reference_r_baselines|scripts_python_tools|download_retry_python
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
	test-frame-stability bench-regime test-regime \
	test-dbms bench-dbms dbms-analysis \
	tree-build test-tree bench-tree tree-analysis cgal-build \
	help venv python-deps archive download-data real-data bench-independent bench-cgal \
	app-query-smoke app-query app-query-analysis analyze-independent \
	clean clean-artifacts clean-data format \
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
	@echo "  make venv                  Create .venv and install requirements.txt"
	@echo "  make python-deps           Install Python test/analysis dependencies"
	@echo "  make archive               Archive sources/results under backups/sources/"
	@echo "  make format                Apply clang-format in-place"
	@echo "  make clean                 Remove $(BUILD_ROOT)/ and Python caches"
	@echo "  make clean-artifacts       Remove benchmark outputs, logs and paper artifacts; keep datasets"
	@echo "  make clean-data            Remove raw/processed/cache data (manual; downloads needed again)"
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
	@echo "  make bench-cpp             Configure bench preset + build tools and tests"
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
	@echo "  make real-data             Download/verify/convert Stanford + USGS data"
	@echo "  make download-data         Download + checksum only; no conversion or benchmarks"
	@echo "  make bench-independent     Independent matrices, stability controls, costs and regimes"
	@echo "  make bench-regime          Geometry/shape/contamination matrix + size sensitivity"
	@echo "  make c1-diagnostics        Decompose recorded C1 failures (no ordering runs)"
	@echo "  make bench-c1-resolution   Full-scene fixed-frame C1 bit controls (new measurements)"
	@echo "  make refresh-legacy-labels Update descriptive labels without numerical reanalysis"
	@echo "  make test-regime           Small independent regime/metric validation"
	@echo "  make test-frame-stability  Small resolution/origin/tie-break stability checks"
	@echo "  make bench-cgal            A7 CGAL spatial_sort appendix measurements"
	@echo "  make bench                 All production matrices + extended/application/cache + artifacts"
	@echo "  make app-query-smoke       Exact query correctness windows on real datasets"
	@echo "  make app-query             C0 + native C2/C3/C4 query matrix (long)"
	@echo "                             Reuse requires a new APPLICATION_QUERY_OUTPUT_DIR"
	@echo "  make app-query-analysis    Analyze an existing full query matrix"
	@echo "  make tree-build            Build CGAL k-d-tree adapter (C++23)"
	@echo "  make test-tree             Small exact query + workflow checks"
	@echo "  make bench-tree            Tree DFS layouts + native queries (long; after app-query)"
	@echo "                             TREE_BUCKET=128 TREE_REPEATS=5; TREE_DATASETS selects a subset"
	@echo "  make tree-analysis         Validate existing tree results + generate paper artifacts"
	@echo "  make test-dbms             Short live PostGIS correctness + artifact checks"
	@echo "  make bench-dbms            PostgreSQL/PostGIS matrix (long; after app-query)"
	@echo "                             DBMS_MODE=managed starts/stops a private local cluster"
	@echo "  make dbms-analysis         Validate existing DBMS results + publish artifacts"
	@echo "  make analyze-independent   Reanalyze existing independent outputs"
	@echo "  make bench-extended        Clamp/cost + app/tree/DBMS/cache/workflow + artifacts"
	@echo "  make bench-application-workflow  Continuous read/order/store/query/write runs (256/512/1024)"
	@echo "  make plan-application-workflow   Show workflow workload size without executing it"
	@echo "  make measurement-diagnostics  Analyze refinement and key sharing from stored records"
	@echo "  make rerun-benchmarks      Archive outputs and rerun the checkpointed production suite"
	@echo "  make resume-benchmarks     Continue that suite, preserving completed stages"
	@echo "  make bench-application-cache  Verified cold/warm page-cache matrix (after app-query)"
	@echo "  make validate-extended-benchmarks / validate-application-cache"
	@echo "  make paper-artifacts       Render figures + tables"
	@echo "                             Readers reuse complete closure outputs when canonical regime data is absent"
	@echo "                             Tree/DBMS readers verify their archived application source; CLI overrides win"
	@echo "  make bench-demo            Demo data through canonical synthetic+real artifact checks"
	@echo "  make test-integration      Artifact-BOUND coverage gates"
	@echo "  make test-all              L1 pyramid + CLI + L3 integration + smoke"
	@echo "  make paper-all             format → bench → artifacts"
	@echo "  make paper-pdf             Compile paper/ → paper/build/manuscript.pdf"
	@echo ""
	@echo "L∞ — COMPREHENSIVE:"
	@echo "  make all-targets           ★ Prepare data → clean → build/tests → experiments/artifacts"
	@echo "                             Includes micro-benches, clamp/cost studies, app/tree/DBMS and page-cache."
	@echo "                             Excludes 24h fuzz-soak and duplicate ci-* runs."
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

venv:
	@$(VENV_PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or newer is required (hashlib.file_digest)")'
	@if [ ! -x "$(VENV_DIR)/bin/python" ]; then \
		echo "[venv] Creating $(VENV_DIR) with $(VENV_PYTHON)"; \
		$(VENV_PYTHON) -m venv "$(VENV_DIR)"; \
	fi
	@echo "[venv] Installing requirements.txt into $(VENV_DIR)"
	"$(VENV_DIR)/bin/python" -m pip install --upgrade pip
	"$(VENV_DIR)/bin/python" -m pip install -r requirements.txt

python-deps: venv

archive:
	$(PYTHON) scripts/archive_results.py

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
	@echo "[L0/clean-artifacts] Removing generated artifacts; keeping datasets and .gitkeep"
	@for dir in experiments/outputs experiments/logs analysis/generated paper/build; do \
		if [ -d "$$dir" ]; then \
			find "$$dir" -type f ! -name '.gitkeep' -delete; \
			find "$$dir" -type l -delete; \
			find "$$dir" -depth -mindepth 1 -type d -empty -delete; \
		fi; \
	done
	@echo "[L0/clean-artifacts] Done."

# Explicit opt-in data reset. Never invoked by all-targets or artifact cleanup.
clean-data:
	@echo "[L0/clean-data] Removing raw, processed and cached datasets (preserving .gitkeep)"
	@for dir in data/raw data/processed data/cache; do \
		if [ -d "$$dir" ]; then \
			find "$$dir" -mindepth 1 ! -type d ! -name '.gitkeep' -delete; \
			find "$$dir" -depth -mindepth 1 -type d -empty -delete; \
		fi; \
	done

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
test-python: python-deps
	@echo "[L1/test-python] Synthetic/Real python pipeline (unit-level)"
	$(CMAKE) --preset debug -B $(BUILD_ROOT)/debug \
		-DPython3_EXECUTABLE:FILEPATH=$(abspath $(VENV_DIR)/bin/python) \
		$(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/debug --parallel $(JOBS)
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-R "$(RE_PY_UNIT_SYNTHETIC_REAL)"

# Aggregate L1 — what `make test` runs. Single ctest invocation that
# excludes the artifact-bound coverage gate (paper_artifacts_python ⊃
# PaperArtifactRepoCoverageTest).
test-pyramid: build
	@echo "[L1/test] Artifact-INDEPENDENT pyramid (exclude $(RE_PY_INTEGRATION))"
	$(CTEST) --test-dir $(BUILD_ROOT)/debug --parallel $(JOBS) --output-on-failure \
		-E "$(RE_PY_INTEGRATION)"

test:  test-pyramid test-cli
	$(MAKE) test-cli
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
	@mkdir -p .cache/matplotlib
	$(DOCKER) run --rm -it $(DOCKER_USER_FLAGS) \
		-e XDG_CACHE_HOME=$(DOCKER_WORKDIR)/.cache \
		-e MPLCONFIGDIR=$(DOCKER_WORKDIR)/.cache/matplotlib \
		-e BUILD_ROOT=$(DOCKER_BUILD_ROOT) \
		-e RCH_BUILD_ROOT=$(DOCKER_BUILD_ROOT) \
		-v "$(CURDIR):$(DOCKER_WORKDIR)" \
		-w "$(DOCKER_WORKDIR)" \
		$(DOCKER_IMAGE) bash

docker-%: docker-image
	@if printf '%s\n' $(DOCKER_MAKE_TARGETS) | grep -qx '$*'; then \
			echo "[docker/$*] Run make $* in $(DOCKER_IMAGE)"; \
				mkdir -p .cache/matplotlib; \
				$(DOCKER) run $(DOCKER_RUN_FLAGS) $(DOCKER_USER_FLAGS) \
					-e XDG_CACHE_HOME=$(DOCKER_WORKDIR)/.cache \
					-e MPLCONFIGDIR=$(DOCKER_WORKDIR)/.cache/matplotlib \
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

test-release: $(RELEASE_TEST_PRESET)
	@echo "[L2/test-release] ctest on $(RELEASE_TEST_PRESET) preset"
	$(CTEST) --test-dir $(BUILD_ROOT)/$(RELEASE_TEST_PRESET) --parallel $(JOBS) --output-on-failure \
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
	CMAKE="$(CMAKE)" CTEST="$(CTEST)" PYTHON="$(PYTHON)" JOBS="$(JOBS)" \
		RCH_BUILD_ROOT="$(BUILD_ROOT)" CTEST_EXCLUDE_REGEX="$(RE_PY_INTEGRATION)" \
		bash scripts/coverage.sh

repro:
	@echo "[L2/repro] Release + reproducible flags"
	$(CMAKE) --preset repro -B $(BUILD_ROOT)/repro \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/repro --parallel $(JOBS)

repro-smoke:
	@echo "[L2/repro-smoke] Reproducibility smoke (<30s)"
	CMAKE="$(CMAKE)" CTEST="$(CTEST)" PYTHON="$(PYTHON)" JOBS="$(JOBS)" \
		RCH_BUILD_ROOT="$(BUILD_ROOT)" CTEST_EXCLUDE_REGEX="$(RE_PY_INTEGRATION)" \
		bash reproducibility/scripts/reproduce_smoke.sh

test-smoke: repro-smoke
	@echo "[L2/test-smoke] alias for repro-smoke"

# ════════════════════════════════════════════════════════════════════════
# L3 — EXPERIMENT ARTIFACTS + INTEGRATION GATES
# These targets produce/consume experiments/outputs/ and analysis/generated/.
# test-integration reads CSVs written by bench-synthetic/bench-real.
# ════════════════════════════════════════════════════════════════════════
bench-cpp:
	@echo "[L3/bench-cpp] Configure bench preset + build tools and tests"
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS)

cgal-adapter-bin:
	@echo "[L3/cgal-adapter-bin] Build A7 CGAL spatial_sort adapter"
	$(CMAKE) -S . -B $(BUILD_ROOT)/cgal-adapter \
		-DCMAKE_BUILD_TYPE=$(CGAL_BUILD_TYPE) \
		-DCGAL_DIR:PATH=$(abspath $(CGAL_DIR)) \
		-DCGAL_DISABLE_GMP:BOOL=ON \
		-DRCH_WITH_CGAL=ON -DRCH_BUILD_TOOLS=ON -DRCH_BUILD_TESTS=OFF \
		$(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/cgal-adapter \
		--target rch_cgal_spatial_sort --parallel $(JOBS)

cgal-build: cgal-adapter-bin
	@echo "[L3/cgal-build] Optional CGAL spatial_sort adapter smoke test"
	$(PYTHON) tests/integration/test_cgal_spatial_sort_adapter.py $(CGAL_ADAPTER_BIN)

# Tree consumers use frozen app-query inputs; they never rerun app-query.
tree-build: python-deps
	$(CMAKE) -S . -B $(BUILD_ROOT)/tree \
		-DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=$(TREE_CXX) \
		-DCGAL_DIR:PATH=$(abspath $(CGAL_DIR)) -DCGAL_DISABLE_GMP:BOOL=ON \
		-DRCH_WITH_CGAL=ON -DRCH_BUILD_TOOLS=OFF -DRCH_BUILD_TESTS=OFF \
		$(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/tree --target rch_cgal_tree_benchmark --parallel $(JOBS)

test-tree: tree-build
	$(PYTHON) tests/integration/test_tree_benchmark.py $(TREE_BIN)

bench-tree: tree-build
	@test -f "$(APPLICATION_QUERY_OUTPUT_DIR)/run_manifest.json" || { echo "Run make app-query first"; exit 2; }
	$(PYTHON) experiments/runners/run_tree_benchmarks.py --binary $(TREE_BIN) \
		--source-root $(APPLICATION_QUERY_OUTPUT_DIR) --output-dir $(TREE_OUTPUT_DIR) \
		--repeats $(TREE_REPEATS) --bucket $(TREE_BUCKET) \
		$(foreach dataset,$(TREE_DATASETS),--dataset $(dataset))

tree-analysis:
	$(PYTHON) analysis/scripts/analyze_tree_benchmarks.py --input-root $(TREE_OUTPUT_DIR) \
		--application-root "$(APPLICATION_QUERY_OUTPUT_DIR)" \
		--output-dir analysis/generated/outputs/tree_benchmark --artifact-root analysis/generated

# DBMS consumers use frozen app-query inputs. Managed mode uses private
# socket-only PostgreSQL data and leaves the system cluster untouched.
test-dbms: python-deps
	$(PYTHON) tests/integration/test_dbms_benchmark.py

bench-dbms: python-deps
	@test -f "$(APPLICATION_QUERY_OUTPUT_DIR)/run_manifest.json" || { echo "Run make app-query first"; exit 2; }
	$(PYTHON) experiments/runners/run_dbms_benchmarks.py \
		--source-root $(APPLICATION_QUERY_OUTPUT_DIR) --output-dir $(DBMS_OUTPUT_DIR) \
		--mode $(DBMS_MODE) --repeats $(DBMS_REPEATS) \
		$(foreach dataset,$(DBMS_DATASETS),--dataset $(dataset))

dbms-analysis:
	$(PYTHON) analysis/scripts/analyze_dbms_benchmarks.py --input-root $(DBMS_OUTPUT_DIR) \
		--application-root "$(APPLICATION_QUERY_OUTPUT_DIR)" --artifact-root analysis/generated \
		--output-dir analysis/generated/outputs/dbms_benchmark

cgal-adapter: cgal-adapter-bin
	@echo "[L3/cgal-adapter] A7 CGAL spatial_sort appendix"
	$(PYTHON) experiments/runners/run_cgal_appendix.py \
		--adapter-bin $(CGAL_ADAPTER_BIN) \
		--output-dir $(A7_OUTPUT_DIR)

test-cgal: cgal-build

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
	@echo "[L3/bench-test] Artifact-independent CTest suite and determinism log"
	PYTHON="$(PYTHON)" RCH_BUILD_ROOT="$(BUILD_ROOT)" CTEST_EXCLUDE_REGEX="$(RE_PY_INTEGRATION)" bash scripts/test.sh $(BENCH_PRESET)

bench-synthetic: bench-cpp cgal-build
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

download-data: python-deps
	@echo "[L3/download-data] Download and verify Stanford + USGS + NOAA archives"
	$(PYTHON) scripts/download_dataset.py \
		--manifest $(STANFORD_MANIFEST) --raw-dir $(STANFORD_RAW_DIR)
	$(PYTHON) scripts/download_dataset.py \
		--manifest $(USGS_MANIFEST) --raw-dir $(USGS_RAW_DIR)
	$(PYTHON) scripts/download_dataset.py \
		--manifest $(NOAA_MANIFEST) --raw-dir $(NOAA_RAW_DIR)

real-data: download-data
	@echo "[L3/real-data] Convert verified Stanford + USGS + NOAA data"
	$(PYTHON) scripts/convert_dataset.py \
		--manifest $(STANFORD_MANIFEST) \
		--raw-dir $(STANFORD_RAW_DIR) \
		--processed-dir $(STANFORD_PROCESSED_DIR)
	$(PYTHON) scripts/prepare_usgs_dataset.py \
		--manifest $(USGS_MANIFEST) --raw-dir $(USGS_RAW_DIR) \
		--processed-dir $(USGS_PROCESSED_DIR)

	$(PYTHON) scripts/prepare_usgs_dataset.py \
		--manifest $(NOAA_MANIFEST) --raw-dir $(NOAA_RAW_DIR) \
		--processed-dir $(NOAA_PROCESSED_DIR)

bench-real: bench-cpp cgal-build real-data
	@echo "[L3/bench-real] Stanford + USGS LiDAR dataset matrix"
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

bench-independent: bench-cpp cgal-build
	@echo "[L3/bench-independent] Independent sampling, ablations and diagnostics"
	$(PYTHON) experiments/runners/run_independent_benchmarks.py \
		--output-dir $(INDEPENDENT_OUTPUT_DIR) \
		--rch-order-bin $(RCH_ORDER_BIN) --cgal-adapter-bin $(CGAL_ADAPTER_BIN)

bench-regime: bench-cpp
	@echo "[L3/bench-regime] Geometry, shape, contamination and size sensitivity"
	$(PYTHON) experiments/runners/run_regime_benchmarks.py \
		--output-dir $(REGIME_OUTPUT_DIR) --rch-order-bin $(RCH_ORDER_BIN)

test-regime: bench-cpp
	$(PYTHON) tests/integration/test_regime_benchmarks.py $(RCH_ORDER_BIN)

test-frame-stability: bench-cpp
	$(PYTHON) tests/integration/test_frame_stability.py $(RCH_ORDER_BIN)

bench-cgal: cgal-adapter-bin
	@echo "[L3/bench-cgal] A7 CGAL spatial_sort appendix"
	$(PYTHON) experiments/runners/run_cgal_appendix.py \
		--adapter-bin $(CGAL_ADAPTER_BIN) \
		--output-dir $(A7_OUTPUT_DIR)

# Build/run optional micro-benchmarks after the production data matrices.
bench-micro:
	@echo "[L3/bench-micro] Configure bench preset + build micro-benchmarks"
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) \
		--target $(BENCH_MICRO_BINS)

bench-micro-run: bench-micro
	@for bin in $(BENCH_MICRO_BINS); do \
		$(BUILD_ROOT)/$(BENCH_PRESET)/benchmarks/$$bin \
			--benchmark_min_time=$(BENCH_MICRO_TIME) || exit $$? ; \
	done

app-query-smoke: bench-cpp real-data
	@echo "[L3/app-query-smoke] Exact query correctness windows"
	$(PYTHON) experiments/runners/run_application_query_smoke.py \
		--raw-dir $(STANFORD_RAW_DIR) --processed-dir $(STANFORD_PROCESSED_DIR) \
		$(APPLICATION_QUERY_DATASET_ARGS) \
		--rch-order-bin $(RCH_ORDER_BIN) \
		--smoke-bin $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_application_query_smoke \
		--output-dir $(APPLICATION_QUERY_SMOKE_DIR)

app-query: bench-cpp real-data
	@echo "[L3/app-query] Full warm-cache application query matrix"
	$(PYTHON) experiments/runners/run_application_query_smoke.py \
		--raw-dir $(STANFORD_RAW_DIR) --processed-dir $(STANFORD_PROCESSED_DIR) \
		$(APPLICATION_QUERY_DATASET_ARGS) --full-query-matrix \
		--measured-repeats $(APPLICATION_QUERY_REPEATS) \
		--ordering-repeats $(APPLICATION_ORDERING_REPEATS) \
		--measure-warm-cache-compression \
		--rch-order-bin $(RCH_ORDER_BIN) \
		--smoke-bin $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_application_query_smoke \
		--output-dir $(APPLICATION_QUERY_OUTPUT_DIR)
	$(MAKE) app-query-analysis

app-query-analysis:
	$(PYTHON) analysis/scripts/analyze_application_query_metrics.py \
		--input-root $(APPLICATION_QUERY_OUTPUT_DIR) \
		--expected-repeats $(APPLICATION_QUERY_REPEATS) \
		$(foreach dataset,$(APPLICATION_QUERY_DATASETS),--expected-dataset $(dataset)) \
		--output-dir $(APPLICATION_QUERY_ANALYSIS_DIR)

analyze-independent:
	@test -f "$(INDEPENDENT_OUTPUT_DIR)/benchmark_manifest.json" || { echo "Run make bench-independent first"; exit 2; }
	$(PYTHON) experiments/runners/run_independent_benchmarks.py \
		--output-dir $(INDEPENDENT_OUTPUT_DIR) \
		--rch-order-bin $(RCH_ORDER_BIN) --cgal-adapter-bin $(CGAL_ADAPTER_BIN) --analyze-only

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
	MPLCONFIGDIR="$(abspath .cache/matplotlib-rch-demo)" $(PYTHON) analysis/scripts/make_paper_artifacts.py \
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

paper-artifacts:
	@for file in $(SYNTHETIC_PRIMARY_RESULTS_DIR)/table_3_locality.csv \
		$(REAL_PRIMARY_RESULTS_DIR)/table_2_dataset_summary.csv \
		$(A7_OUTPUT_DIR)/a7_cgal_spatial_sort.csv \
		$(INDEPENDENT_OUTPUT_DIR)/benchmark_manifest.json \
		$(REGIME_OUTPUT_DIR)/run_manifest.json; do \
		test -f "$$file" || { echo "[paper-artifacts] Missing $$file; run make bench first"; exit 2; }; \
	done
	@echo "[L3/paper-artifacts] Render figures + tables from existing outputs"
	@echo "[paper-artifacts] independent=$(INDEPENDENT_OUTPUT_DIR) real=$(REAL_OUTPUT_DIR) application=$(APPLICATION_QUERY_OUTPUT_DIR)"
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
	$(PYTHON) analysis/scripts/make_application_artifacts.py \
		--input-root $(APPLICATION_QUERY_OUTPUT_DIR) --real-results-dir $(REAL_OUTPUT_DIR)
	@if [ -f "$(APPLICATION_CACHE_OUTPUT_DIR)/run_manifest.json" ]; then \
		$(PYTHON) analysis/scripts/make_application_cache_artifacts.py \
			--input-root "$(APPLICATION_CACHE_OUTPUT_DIR)"; \
	fi
	@if [ -f "$(APPLICATION_WORKFLOW_OUTPUT_DIR)/run_manifest.json" ]; then \
		$(MAKE) application-workflow-artifacts; \
	fi
	$(MAKE) measurement-diagnostics APPLICATION_QUERY_OUTPUT_DIR="$(APPLICATION_QUERY_OUTPUT_DIR)" SYNTHETIC_OUTPUT_DIR="$(SYNTHETIC_OUTPUT_DIR)"
	@if [ -f "$(APPLICATION_QUERY_OUTPUT_DIR)/run_manifest.json" ] && \
	    [ -f experiments/outputs/cost_stability_scenarios/run_manifest.json ]; then \
		$(MAKE) fallback-evidence APPLICATION_QUERY_OUTPUT_DIR="$(APPLICATION_QUERY_OUTPUT_DIR)" \
			INDEPENDENT_OUTPUT_DIR="$(INDEPENDENT_OUTPUT_DIR)" REAL_OUTPUT_DIR="$(REAL_OUTPUT_DIR)"; \
	fi
	@if [ -f "$(INDEPENDENT_OUTPUT_DIR)/frame_stability/run_manifest.json" ]; then \
		$(PYTHON) analysis/scripts/analyze_frame_stability.py \
			--input-root $(INDEPENDENT_OUTPUT_DIR)/frame_stability \
			--output-dir analysis/generated/outputs/frame_stability --artifact-root analysis/generated; \
	fi
	$(PYTHON) analysis/scripts/analyze_regime_benchmarks.py \
		--input-root $(REGIME_OUTPUT_DIR) --output-dir analysis/generated/outputs/regime_map \
		--artifact-root analysis/generated
	$(PYTHON) analysis/scripts/analyze_regime_diagnostics.py \
		--input-root $(INDEPENDENT_OUTPUT_DIR) --artifact-root analysis/generated
	$(PYTHON) analysis/scripts/analyze_c1_failure.py --real-root $(REAL_PRIMARY_RESULTS_DIR)
	@if test -f "$(C1_RESOLUTION_OUTPUT_DIR)/run_manifest.json"; then \
		$(PYTHON) analysis/scripts/analyze_c1_failure.py \
			--ablation-root $(C1_RESOLUTION_OUTPUT_DIR) \
			--output-dir analysis/generated/outputs/c1_resolution_ablation; \
	fi
	@if [ -f "$(TREE_OUTPUT_DIR)/run_manifest.json" ]; then $(MAKE) tree-analysis APPLICATION_QUERY_OUTPUT_DIR="$(APPLICATION_QUERY_OUTPUT_DIR)" TREE_OUTPUT_DIR="$(TREE_OUTPUT_DIR)"; fi
	@if [ -f "$(DBMS_OUTPUT_DIR)/run_manifest.json" ]; then $(MAKE) dbms-analysis APPLICATION_QUERY_OUTPUT_DIR="$(APPLICATION_QUERY_OUTPUT_DIR)" DBMS_OUTPUT_DIR="$(DBMS_OUTPUT_DIR)"; fi
	@if [ -d "$(INDEPENDENT_OUTPUT_DIR)/reports" ]; then \
		mkdir -p analysis/generated/outputs/independent_benchmarks; \
		cp -R "$(INDEPENDENT_OUTPUT_DIR)/reports" analysis/generated/outputs/independent_benchmarks/; \
		cp "$(INDEPENDENT_OUTPUT_DIR)/benchmark_manifest.json" analysis/generated/outputs/independent_benchmarks/; \
	fi
	@if [ -f experiments/outputs/clamping_intervention/run_manifest.json ] && \
	    [ -f experiments/outputs/cost_stability_scenarios/run_manifest.json ] && \
	    [ -f experiments/outputs/real_clamping_checks/run_manifest.json ]; then \
		$(PYTHON) analysis/scripts/make_extended_benchmark_artifacts.py --application-root $(APPLICATION_QUERY_OUTPUT_DIR); \
	fi
	@command -v pdftops >/dev/null 2>&1 || { \
		echo "[paper-artifacts] ERROR: pdftops not found (install poppler-utils for EPS)."; exit 2; }
	@echo "[L3/paper-artifacts] Emit PostScript (EPS) copies of each figure"
	@for f in analysis/generated/figures/*.pdf; do \
		case "$$f" in *-eps-converted-to.pdf) continue;; esac; \
		pdftops -eps "$$f" "$${f%.pdf}.eps" || exit 1; \
	done

bench:
	@echo "[L3/bench] Sequential production measurements and validation"
	$(MAKE) bench-synthetic
	$(MAKE) bench-real
	$(MAKE) bench-independent
	$(MAKE) bench-cgal
	$(MAKE) test-measurement-integrity
	$(MAKE) test-benchmark-resume
	$(MAKE) test-clamping-intervention
	$(MAKE) test-cost-stability
	$(MAKE) test-fallback-evidence
	$(MAKE) test-application-cache
	$(MAKE) test-application-workflow
	$(MAKE) test-tree
	$(MAKE) test-dbms
	$(MAKE) bench-extended
	$(MAKE) test-integration
	@echo "[L3/bench] All production measurements and artifact gates passed"

# Artifact-bound coverage gate. Fails fast if Synthetic/Real outputs are missing.
test-integration: bench-cpp
	@echo "[L3/test-integration] Artifact-bound paper-artifact coverage gates"
	@for file in $(SYNTHETIC_PRIMARY_RESULTS_DIR)/table_3_locality.csv \
		$(REAL_PRIMARY_RESULTS_DIR)/table_2_dataset_summary.csv \
		$(A7_OUTPUT_DIR)/a7_cgal_spatial_sort.csv \
		$(INDEPENDENT_OUTPUT_DIR)/benchmark_manifest.json \
		$(REGIME_OUTPUT_DIR)/run_manifest.json \
		analysis/generated/stats/paper_artifacts_manifest.json \
		analysis/generated/stats/application_artifacts_manifest.json; do \
		test -f "$$file" || { echo "[L3/test-integration] Missing $$file; run make paper-artifacts first"; exit 2; }; \
	done
	$(CTEST) --test-dir $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) --output-on-failure \
		--no-tests=error -R "$(RE_PY_INTEGRATION)"
	$(PYTHON) analysis/scripts/check_application_artifacts.py --input-root $(APPLICATION_QUERY_OUTPUT_DIR)
	$(PYTHON) analysis/scripts/analyze_regime_benchmarks.py \
		--input-root $(REGIME_OUTPUT_DIR) --output-dir analysis/generated/outputs/regime_map \
		--artifact-root analysis/generated --validate-only
	$(PYTHON) analysis/scripts/analyze_regime_diagnostics.py \
		--input-root $(INDEPENDENT_OUTPUT_DIR) --artifact-root analysis/generated --validate-only
	@if [ -f "$(INDEPENDENT_OUTPUT_DIR)/frame_stability/run_manifest.json" ]; then \
		$(PYTHON) analysis/scripts/analyze_frame_stability.py \
			--input-root $(INDEPENDENT_OUTPUT_DIR)/frame_stability \
			--output-dir analysis/generated/outputs/frame_stability --artifact-root analysis/generated --validate-only; \
	fi
	@if [ -f "$(DBMS_OUTPUT_DIR)/run_manifest.json" ]; then \
		$(PYTHON) analysis/scripts/analyze_dbms_benchmarks.py --input-root $(DBMS_OUTPUT_DIR) \
			--application-root "$(APPLICATION_QUERY_OUTPUT_DIR)" --artifact-root analysis/generated \
			--output-dir analysis/generated/outputs/dbms_benchmark --validate-only; \
	fi
	@if [ -f "$(TREE_OUTPUT_DIR)/run_manifest.json" ]; then \
		$(PYTHON) analysis/scripts/analyze_tree_benchmarks.py --input-root $(TREE_OUTPUT_DIR) \
			--application-root "$(APPLICATION_QUERY_OUTPUT_DIR)" --artifact-root analysis/generated \
			--output-dir analysis/generated/outputs/tree_benchmark --validate-only; \
	fi

	@if [ -f experiments/outputs/clamping_intervention/run_manifest.json ] && \
	    [ -f experiments/outputs/cost_stability_scenarios/run_manifest.json ] && \
	    [ -f experiments/outputs/real_clamping_checks/run_manifest.json ]; then \
		$(PYTHON) analysis/scripts/check_extended_benchmarks.py --published-only \
			--application-root $(APPLICATION_QUERY_OUTPUT_DIR); \
	fi

	@if [ -f analysis/generated/outputs/fallback_evidence/analysis_manifest.json ]; then \
		$(PYTHON) analysis/scripts/analyze_fallback_evidence.py --validate-only; \
	fi

	@if [ -f "$(APPLICATION_CACHE_OUTPUT_DIR)/run_manifest.json" ]; then \
		$(MAKE) validate-application-cache; \
		$(PYTHON) analysis/scripts/make_application_cache_artifacts.py \
			--input-root "$(APPLICATION_CACHE_OUTPUT_DIR)" --validate-only; \
	fi
	@if [ -f "$(APPLICATION_WORKFLOW_OUTPUT_DIR)/run_manifest.json" ]; then \
		$(MAKE) validate-application-workflow; \
	fi

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

.PHONY: paper-sync-figures
paper-sync-figures:
	$(PYTHON) scripts/sync_paper_figures.py

paper-pdf: paper-sync-figures
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
# Prepares real data before cleanup and demo data after cleanup, then walks
# L0 → L1 → L2 → L3. Each phase is a recursive $(MAKE) so a failure
# inside (say) sanitizers surfaces with a clear phase label and bails out
# before the bench phase wastes time. Excluded by design:
#   • test-fuzz-soak  — 24h budget; nightly-only.
#   • ci-clang/ci-gcc — re-run of L1's debug+ctest; pure duplication.
#   • paper-pdf     — optional manuscript build.
# ════════════════════════════════════════════════════════════════════════
all-targets:
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "L∞/all-targets — L0 → L1 → L2 → L3 (every dependency level)"
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "── Phase L0/environment ──"
	$(MAKE) venv
	@echo ""
	@echo "── Phase L0/real data (download, verify and convert before cleanup/builds) ──"
	$(MAKE) real-data
	@echo ""
	@echo "── Phase L0/cleanup ──"
	$(MAKE) clean
	$(MAKE) clean-artifacts
	@echo ""
	@echo "── Phase L0/demo data (after artifact cleanup, before builds) ──"
	$(MAKE) demo-data
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
	$(MAKE) test-release RELEASE_TEST_PRESET=release-clang
	$(MAKE) test-release RELEASE_TEST_PRESET=release-gcc
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
	@echo "── Phase L3/developer CLIs, examples and external adapter checks ──"
	$(MAKE) examples
	$(MAKE) example-basic
	$(MAKE) test-cli
	$(MAKE) test-cgal
	@echo ""
	@echo "── Phase L3/micro-benchmarks ──"
	$(MAKE) bench-micro-run
	@echo ""
	@echo "── Phase L3/all production measurements, artifacts and integration gates ──"
	$(MAKE) bench
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "✓ all-targets: builds, tests, measurements, artifacts and integration checks passed."
	@echo "  Opt-in: paper-pdf, test-fuzz-soak (24h), ci-clang, ci-gcc."
	@echo "═══════════════════════════════════════════════════════════════════"

.PHONY: measurement-diagnostics test-measurement-integrity
measurement-diagnostics:
	$(PYTHON) analysis/scripts/analyze_measurement_diagnostics.py \
		--synthetic-root $(SYNTHETIC_OUTPUT_DIR) --application-root $(APPLICATION_QUERY_OUTPUT_DIR)

test-measurement-integrity: bench-cpp
	$(PYTHON) tests/integration/test_order_measurement_integrity.py $(RCH_ORDER_BIN)
	$(PYTHON) -m unittest tests.python.test_measurement_diagnostics

# Extended benchmark experiments use the frozen independent clouds and shared app source.
.PHONY: bench-clamping-intervention test-clamping-intervention bench-cost-stability test-cost-stability validate-extended-benchmarks extended-benchmark-artifacts
bench-clamping-intervention: bench-cpp
	$(PYTHON) experiments/runners/run_clamping_ablation.py \
		--input-root $(ARTIFACT_INDEPENDENT_ROOT) \
		--binary $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_clamping_ablation
	$(PYTHON) experiments/runners/run_real_clamping_checks.py \
		--binary $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_clamping_ablation

test-clamping-intervention: bench-cpp
	$(PYTHON) tests/integration/test_clamping_ablation.py \
		$(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_clamping_ablation

bench-cost-stability: bench-cpp
	$(PYTHON) experiments/runners/run_cost_stability_scenarios.py \
		--input-root $(ARTIFACT_INDEPENDENT_ROOT) --binary $(RCH_ORDER_BIN)

test-cost-stability:
	$(PYTHON) -m unittest tests.python.test_cost_stability_decisions

validate-extended-benchmarks:
	$(PYTHON) analysis/scripts/check_extended_benchmarks.py

extended-benchmark-artifacts: validate-extended-benchmarks
	$(PYTHON) analysis/scripts/make_extended_benchmark_artifacts.py --application-root $(APPLICATION_QUERY_OUTPUT_DIR)
	$(PYTHON) analysis/scripts/check_extended_benchmarks.py --published-only --application-root $(APPLICATION_QUERY_OUTPUT_DIR)

.PHONY: bench-extended
bench-extended:
	$(MAKE) bench-test
	$(MAKE) bench-c1-resolution
	$(MAKE) bench-clamping-intervention
	$(MAKE) bench-cost-stability
	$(MAKE) app-query
	$(MAKE) bench-tree
	$(MAKE) bench-dbms
	$(MAKE) bench-application-cache
	$(MAKE) bench-application-workflow
	$(MAKE) paper-artifacts
	$(MAKE) validate-extended-benchmarks
	$(MAKE) validate-application-cache
	$(MAKE) validate-application-workflow

.PHONY: c1-diagnostics bench-c1-resolution refresh-legacy-labels test-review-followup
c1-diagnostics:
	$(PYTHON) analysis/scripts/analyze_c1_failure.py --real-root $(REAL_PRIMARY_RESULTS_DIR)

bench-c1-resolution: bench-cpp
	$(PYTHON) experiments/runners/run_c1_resolution_ablation.py \
		--binary $(RCH_ORDER_BIN) --real-root $(REAL_PRIMARY_RESULTS_DIR) \
		--output-dir $(C1_RESOLUTION_OUTPUT_DIR)

refresh-legacy-labels:
	$(PYTHON) analysis/scripts/refresh_legacy_interpretation.py

test-review-followup:
	$(PYTHON) -m unittest discover -s tests/python -p test_review_followup.py

.PHONY: plan-benchmark-rerun rerun-benchmarks
plan-benchmark-rerun:
	$(PYTHON) scripts/run_benchmark_pipeline.py

# Explicit long run: preserve current measured/generated outputs under backups/.
rerun-benchmarks:
	$(PYTHON) scripts/run_benchmark_pipeline.py --run

.PHONY: plan-benchmark-resume resume-benchmarks
plan-benchmark-resume:
	$(PYTHON) scripts/run_benchmark_pipeline.py --resume

# Continue saved checkpoints; completed core measurements are kept in place.
resume-benchmarks:
	$(PYTHON) scripts/run_benchmark_pipeline.py --run --resume

.PHONY: test-benchmark-resume
test-benchmark-resume: bench-cpp
	$(PYTHON) -m unittest tests.python.test_benchmark_resume
	$(PYTHON) tests/integration/test_benchmark_runner_paths.py

.PHONY: fallback-evidence test-fallback-evidence validate-fallback-evidence
fallback-evidence:
	$(PYTHON) analysis/scripts/analyze_fallback_evidence.py \
		--synthetic-root $(SYNTHETIC_OUTPUT_DIR) --real-root $(REAL_OUTPUT_DIR) \
		--independent-root $(INDEPENDENT_OUTPUT_DIR) --application-root $(APPLICATION_QUERY_OUTPUT_DIR)

test-fallback-evidence: bench-cpp
	$(PYTHON) -m unittest tests.python.test_fallback_evidence
	$(PYTHON) tests/integration/test_fallback_cli_evidence.py $(RCH_ORDER_BIN) \
		--report experiments/logs/validation/fallback_controls.json

validate-fallback-evidence:
	$(PYTHON) analysis/scripts/analyze_fallback_evidence.py --validate-only

# Independent continuous workflow; no dependency on prior ordering/query artifacts.
APPLICATION_WORKFLOW_OUTPUT_DIR ?= experiments/outputs/application_workflow/full_benchmark
APPLICATION_WORKFLOW_ARTIFACT_ROOT ?= analysis/generated
APPLICATION_WORKFLOW_QUERY_COUNTS ?= 256 512 1024
APPLICATION_WORKFLOW_REPEATS ?= 5
APPLICATION_WORKFLOW_DATASETS ?= $(APPLICATION_QUERY_DATASETS)
APPLICATION_WORKFLOW_BIN ?= $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_application_workflow
APPLICATION_WORKFLOW_KEEP_ARGS ?=
APPLICATION_WORKFLOW_ARGS = --binary $(APPLICATION_WORKFLOW_BIN) \
	--output-dir $(APPLICATION_WORKFLOW_OUTPUT_DIR) \
	--query-counts $(APPLICATION_WORKFLOW_QUERY_COUNTS) --repeats $(APPLICATION_WORKFLOW_REPEATS) \
	$(foreach dataset,$(APPLICATION_WORKFLOW_DATASETS),--dataset $(dataset)) $(APPLICATION_WORKFLOW_KEEP_ARGS)

.PHONY: application-workflow-bin plan-application-workflow bench-application-workflow resume-application-workflow validate-application-workflow application-workflow-artifacts test-application-workflow
application-workflow-bin:
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) \
		--target rch_application_workflow

plan-application-workflow:
	$(PYTHON) experiments/runners/run_application_workflow.py $(APPLICATION_WORKFLOW_ARGS)

bench-application-workflow: application-workflow-bin real-data
	$(PYTHON) experiments/runners/run_application_workflow.py $(APPLICATION_WORKFLOW_ARGS) --run
	$(MAKE) application-workflow-artifacts

resume-application-workflow: application-workflow-bin
	$(PYTHON) experiments/runners/run_application_workflow.py $(APPLICATION_WORKFLOW_ARGS) --run --resume
	$(MAKE) application-workflow-artifacts

application-workflow-artifacts:
	$(PYTHON) analysis/scripts/make_application_workflow_artifacts.py \
		--input-root $(APPLICATION_WORKFLOW_OUTPUT_DIR) --artifact-root $(APPLICATION_WORKFLOW_ARTIFACT_ROOT)

validate-application-workflow:
	$(PYTHON) experiments/runners/run_application_workflow.py \
		--output-dir $(APPLICATION_WORKFLOW_OUTPUT_DIR) --validate-only
	$(PYTHON) analysis/scripts/make_application_workflow_artifacts.py \
		--input-root $(APPLICATION_WORKFLOW_OUTPUT_DIR) --artifact-root $(APPLICATION_WORKFLOW_ARTIFACT_ROOT) --validate-only

test-application-workflow: application-workflow-bin
	$(PYTHON) tests/integration/test_application_workflow_e2e.py $(APPLICATION_WORKFLOW_BIN)
	$(PYTHON) tests/integration/test_application_io_artifacts.py

# Separate cache intervention; consumes frozen application storage, no ordering rerun.
APPLICATION_CACHE_OUTPUT_DIR ?= experiments/outputs/application_cache/full_benchmark
APPLICATION_CACHE_REPEATS ?= 5
APPLICATION_CACHE_BIN = $(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_application_cache_probe
APPLICATION_CACHE_ARGS = --application-root $(APPLICATION_QUERY_OUTPUT_DIR) \
	--output-dir $(APPLICATION_CACHE_OUTPUT_DIR) --probe-bin $(APPLICATION_CACHE_BIN) \
	--repeats $(APPLICATION_CACHE_REPEATS)

.PHONY: application-cache-bin plan-application-cache bench-application-cache resume-application-cache validate-application-cache test-application-cache
application-cache-bin:
	$(CMAKE) --preset $(BENCH_PRESET) -B $(BUILD_ROOT)/$(BENCH_PRESET) \
		$(CMAKE_PYTHON_ARGS) $(CMAKE_BUILD_ROOT_ARGS)
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) \
		--target rch_application_cache_probe

plan-application-cache: application-cache-bin
	$(PYTHON) experiments/runners/run_application_cache.py $(APPLICATION_CACHE_ARGS)

bench-application-cache: application-cache-bin
	$(PYTHON) experiments/runners/run_application_cache.py $(APPLICATION_CACHE_ARGS) --run

resume-application-cache: application-cache-bin
	$(PYTHON) experiments/runners/run_application_cache.py $(APPLICATION_CACHE_ARGS) --run --resume

validate-application-cache:
	$(PYTHON) experiments/runners/run_application_cache.py $(APPLICATION_CACHE_ARGS) --validate-only

test-application-cache: application-cache-bin
	$(CMAKE) --build $(BUILD_ROOT)/$(BENCH_PRESET) --parallel $(JOBS) --target rch_application_query_smoke
	$(PYTHON) tests/integration/test_application_cache.py \
		$(BUILD_ROOT)/$(BENCH_PRESET)/src/cli/rch_application_query_smoke $(APPLICATION_CACHE_BIN)
