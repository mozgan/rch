# RCH Documentation

This directory explains the implementation as it exists in this repository.
Claims about behavior are tied to public headers, tests, and experiment
records. Claims about benchmark outcomes are kept separate from the
algorithm contract so that measured evidence is not mistaken for a theorem.

## Choose A Path

For a first successful run:

1. Read [Getting started](getting-started.md).
2. Build and run `examples/basic_order.cpp`.
3. Read [C++ API](api.md) before integrating RCH into an application.

For the mathematics and computational geometry:

Read [Algorithm](algorithm.md) for the six-stage pipeline.

For experiments and reproducibility:

1. Read [Experiments and interpretation](experiments.md).
2. Install the optional tools in [Requirements](requirements.md).
3. Follow [Reproducibility](reproducibility.md).
4. Consult [Linux performance counters](linux-perf.md) before interpreting
   cache columns.

For isolated builds, use [Docker](docker.md).

## Contract Versus Evidence

The public implementation guarantees only what its API and tests establish:
validated finite `N x 3` input, a permutation containing every accepted input
index exactly once, deterministic tie-breaking within the documented arithmetic
scope, bounded integer keys, explicit fallback state, and structured errors.

The recorded experiments provide finite observations on specified synthetic and
reconstruction datasets. They do not prove universal locality, robustness,
runtime, memory, or cache behavior. [Experiments and
interpretation](experiments.md) lists the exact boundaries.

## Authoritative Files

When documentation and implementation disagree, treat these as the behavioral
authorities and open an issue or patch the documentation:

- `include/rch/orderings/orderer.hpp` for the public ordering contract;
- `include/rch/robust/` and `include/rch/frames/` for robust-frame behavior;
- `include/rch/curves/` for bit allocation, quantization, and curve keys;
- `tests/` for executable edge cases and external oracles;
- `experiments/configs/` and `experiments/runlists/` for recorded treatments;
- `analysis/generated/` for generated summaries.

