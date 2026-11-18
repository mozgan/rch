# Recorded fallback evidence

Counts are saved ordering manifests, not independent clouds or scene-level event rates.
Repeated rules, contamination conditions, off/all arms and timing repetitions must not be pooled as independent trials.
The estimator fallback flag and canonical-axis mode are separate mechanisms. Missing fields remain unknown.
A false estimator fallback flag does not imply an exact/global MCD solution or absence of regularization.
Exact estimator policy/reason and eigensolver-failure reason are not serialized by these CLI manifests; they cannot be inferred from the counts.
Synthetic/real manifest filenames can be reused across runlists; counts describe unique saved paths, not every CSV row.
Coverage: all saved *.manifest.json in the synthetic/real off/all manifest directories; inventoried independent manifests; application curve manifests; cost-stability order metadata.
Native clamping helpers serialize a different diagnostics format without frame mode. They are outside this manifest table; no zero canonical rate is assigned to them.

| Family | Estimator | Frame records | Estimator fallback / known | Canonical axes / known | Unknown applicability / flag / mode |
|---|---|---:|---:|---:|---:|
| application | det_mcd | 28 | 0/28 | 0/28 | 0/0/0 |
| cost_stability | det_mcd | 3300 | 0/3300 | 0/3300 | 0/0/0 |
| cost_stability | sample_covariance | 3300 | n/a | 0/3300 | 0/0/0 |
| independent/cost_decomposition | det_mcd | 60 | 0/60 | 0/60 | 0/0/0 |
| independent/cost_decomposition | sample_covariance | 60 | n/a | 0/60 | 0/0/0 |
| independent/frame_ablation_bit_rules | det_mcd | 3300 | 0/3300 | 0/3300 | 0/0/0 |
| independent/frame_ablation_bit_rules | sample_covariance | 3300 | n/a | 0/3300 | 0/0/0 |
| independent/frame_ablation_fixed_domain | det_mcd | 220 | 0/220 | 0/220 | 0/0/0 |
| independent/frame_ablation_fixed_domain | sample_covariance | 220 | n/a | 0/220 | 0/0/0 |
| independent/pca_fixed_hilbert_control | det_mcd | 80 | 0/80 | 0/80 | 0/0/0 |
| independent/pca_fixed_hilbert_control | sample_covariance | 80 | n/a | 0/80 | 0/0/0 |
| independent/regime_map | det_mcd | 6800 | 0/6800 | 0/6800 | 0/0/0 |
| independent/regime_map | sample_covariance | 6800 | n/a | 0/6800 | 0/0/0 |
| independent/table_3_locality | det_mcd | 240 | 0/240 | 0/240 | 0/0/0 |
| independent/table_4_outlier | det_mcd | 3300 | 0/3300 | 0/3300 | 0/0/0 |
| independent/table_4_outlier | sample_covariance | 3300 | n/a | 0/3300 | 0/0/0 |
| real/all | det_mcd | 150 | 0/150 | 0/150 | 0/0/0 |
| real/all | mrcd | 75 | 0/75 | 0/75 | 0/0/0 |
| real/all | ogk | 75 | 0/75 | 0/75 | 0/0/0 |
| real/all | sample_covariance | 75 | n/a | 0/75 | 0/0/0 |
| real/off | det_mcd | 150 | 0/150 | 0/150 | 0/0/0 |
| real/off | mrcd | 75 | 0/75 | 0/75 | 0/0/0 |
| real/off | ogk | 75 | 0/75 | 0/75 | 0/0/0 |
| real/off | sample_covariance | 75 | n/a | 0/75 | 0/0/0 |
| synthetic/all | det_mcd | 7000 | 0/7000 | 0/7000 | 0/0/0 |
| synthetic/all | mrcd | 3500 | 0/3500 | 0/3500 | 0/0/0 |
| synthetic/all | ogk | 3500 | 0/3500 | 0/3500 | 0/0/0 |
| synthetic/all | sample_covariance | 3500 | n/a | 0/3500 | 0/0/0 |
| synthetic/off | det_mcd | 7000 | 0/7000 | 0/7000 | 0/0/0 |
| synthetic/off | mrcd | 3500 | 0/3500 | 0/3500 | 0/0/0 |
| synthetic/off | ogk | 3500 | 0/3500 | 0/3500 | 0/0/0 |
| synthetic/off | sample_covariance | 3500 | n/a | 0/3500 | 0/0/0 |
