# PCA-frame fixed-resolution Hilbert control

A5 uses the existing sample-covariance PCA frame with C0 uniform allocation (10 bits per axis; 30 total bits). A3 is the isotropic fixed 10-bit-per-axis Hilbert reference. A6 is RCH under the same C0 bit rule. Covering boxes and frames differ: equal bit counts do not fix physical cell widths or isolate rotation alone. Each geometry has 20 paired independent clouds (384 points each); differences are left minus right, so negative values favor the left algorithm. Intervals are percentile bootstrap 95% CIs over the independent cloud seeds, computed separately per geometry.

| Geometry | Comparison | Median MIAD or paired difference | 95% bootstrap CI | n |
|---|---|---:|---:|---:|
| E1 | median_miad: A3_isotropic_hilbert | 1.36378 | — | 20 |
| E1 | median_miad: A5_pca_compact_hilbert | 1.74906 | — | 20 |
| E1 | median_miad: A6_rch | 1.71804 | — | 20 |
| E1 | paired_median_difference: A5_pca_compact_hilbert − A3_isotropic_hilbert | 0.40399 | [0.252032, 0.466161] | 20 |
| E1 | paired_median_difference: A6_rch − A5_pca_compact_hilbert | -0.0162141 | [-0.0833538, -0.0058299] | 20 |
| E1 | paired_median_difference: A6_rch − A3_isotropic_hilbert | 0.293583 | [0.228499, 0.453951] | 20 |
| E10 | median_miad: A3_isotropic_hilbert | 1.61591 | — | 20 |
| E10 | median_miad: A5_pca_compact_hilbert | 2.30202 | — | 20 |
| E10 | median_miad: A6_rch | 2.26913 | — | 20 |
| E10 | paired_median_difference: A5_pca_compact_hilbert − A3_isotropic_hilbert | 0.734938 | [0.581451, 0.811737] | 20 |
| E10 | paired_median_difference: A6_rch − A5_pca_compact_hilbert | -0.0453516 | [-0.0829064, -0.00411759] | 20 |
| E10 | paired_median_difference: A6_rch − A3_isotropic_hilbert | 0.688794 | [0.528836, 0.789691] | 20 |
| E2 | median_miad: A3_isotropic_hilbert | 2.01171 | — | 20 |
| E2 | median_miad: A5_pca_compact_hilbert | 3.19883 | — | 20 |
| E2 | median_miad: A6_rch | 3.26052 | — | 20 |
| E2 | paired_median_difference: A5_pca_compact_hilbert − A3_isotropic_hilbert | 1.15155 | [1.01315, 1.458] | 20 |
| E2 | paired_median_difference: A6_rch − A5_pca_compact_hilbert | 0.025487 | [-0.036209, 0.106036] | 20 |
| E2 | paired_median_difference: A6_rch − A3_isotropic_hilbert | 1.17175 | [1.06617, 1.36429] | 20 |
| E9 | median_miad: A3_isotropic_hilbert | 0.99951 | — | 20 |
| E9 | median_miad: A5_pca_compact_hilbert | 1.1477 | — | 20 |
| E9 | median_miad: A6_rch | 1.1477 | — | 20 |
| E9 | paired_median_difference: A5_pca_compact_hilbert − A3_isotropic_hilbert | 0.122207 | [0.10651, 0.162054] | 20 |
| E9 | paired_median_difference: A6_rch − A5_pca_compact_hilbert | 0.007541 | [-0.00862456, 0.0126696] | 20 |
| E9 | paired_median_difference: A6_rch − A3_isotropic_hilbert | 0.137366 | [0.115539, 0.169913] | 20 |

The bootstrap unit is the independently generated cloud seed, not algorithm/run rows. This is a synthetic ordering comparison; it does not measure database query or storage performance.
