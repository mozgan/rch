# Recorded C1 interpretation

These numbers are recomputed from existing records, not a clean benchmark rerun. Values may change after new measurements. No population or causal conclusion is inferred.

- stanford_bunny / A5_pca_compact_hilbert: bits [10, 4, 1]; MIAD 0.0127434; shared-key points 86.50791%; within-key path contribution 25.96742%; clipped fraction 0.0.
- stanford_bunny / A6_rch: bits [10, 4, 1]; MIAD 0.01201001; shared-key points 92.24970%; within-key path contribution 30.76882%; clipped fraction 0.0.
- stanford_armadillo / A5_pca_compact_hilbert: bits [10, 4, 1]; MIAD 3.923383; shared-key points 99.84391%; within-key path contribution 70.48849%; clipped fraction 0.0.
- stanford_armadillo / A6_rch: bits [10, 4, 1]; MIAD 3.797857; shared-key points 99.87744%; within-key path contribution 72.17729%; clipped fraction 0.0.

The C1 allocator greedily spends half of the maximum equal-axis budget on the longest axes first (see bit_allocation_monotone.hpp). With a 10-bit axis cap and 1-bit minimum, ranked axes receive 10/4/1 bits: the last axis has two bins. This is the specified heuristic, not evidence of an encoder bug. C0/C1 comparisons change total bits and their distribution. Equal-budget balancing in the optional fixed-frame experiment is needed to separate these mechanisms.
