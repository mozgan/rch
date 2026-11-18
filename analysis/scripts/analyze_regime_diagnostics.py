#!/usr/bin/env python3
"""Observed clean-cloud regimes, without a fitted or causal selection rule."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RULES = ('C2_occupancy_floor1', 'C3_frame_core_occupancy', 'C4_hybrid')
GEOMETRIES = ('E1', 'E2', 'E9', 'E10')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root):
    inventory = json.loads((root / 'benchmark_manifest.json').read_text())['files_sha256']
    used = {}

    def verified(relative):
        path = root / relative
        actual = digest(path)
        if inventory.get(relative) != actual:
            raise ValueError(f'Inventory mismatch: {relative}')
        used[relative] = actual
        return path

    relative = 'table_3_locality/off/table_3_locality_independent.csv'
    rows = list(csv.DictReader(verified(relative).open()))
    cells = {}
    for row in rows:
        if row['algorithm_id'] not in ('A3_isotropic_hilbert', 'A6_rch'):
            continue
        if row['contamination_id'] != 'D0' or row['refinement'] != 'off':
            raise ValueError('Expected clean unrefined observations')
        key = (row['geometry_id'], int(row['seed']), row['bit_rule'], row['algorithm_id'])
        if key in cells:
            raise ValueError(f'Duplicate observation: {key}')
        cells[key] = row
    expected = {(g, s, r, a) for g in GEOMETRIES for s in range(20)
                for r in RULES for a in ('A3_isotropic_hilbert', 'A6_rch')}
    if set(cells) != expected:
        raise ValueError('Incomplete clean-cloud comparison matrix')
    output = []
    for g in GEOMETRIES:
        for seed in range(20):
            reference_hash = None
            for rule in RULES:
                a, b = [cells[g, seed, rule, alg] for alg in ('A3_isotropic_hilbert', 'A6_rch')]
                hashes = []
                points = None
                for row in (a, b):
                    stem = f"{row['algorithm_id']}__{rule}__D0__{g}__n384__s{seed}"
                    path = verified(f'table_3_locality/off/data/{stem}.csv')
                    hashes.append(digest(path))
                    if row['point_count'] != '384':
                        raise ValueError('Unexpected sample size')
                    points = np.loadtxt(path, delimiter=',')
                if hashes[0] != hashes[1] or (reference_hash and reference_hash != hashes[0]):
                    raise ValueError('Methods/rules do not share the same cloud')
                reference_hash = hashes[0]
                if points.shape != (384, 3) or not np.isfinite(points).all():
                    raise ValueError('Invalid point array')
                eig = np.linalg.eigvalsh(np.cov(points, rowvar=False))[::-1]
                if eig[-1] <= 0:
                    raise ValueError('Rank-deficient cloud needs a separate interpretation')
                values = [float(a['miad']), float(b['miad']), float(b['domain_clipped_point_fraction']),
                          float(b['duplicate_hilbert_key_point_fraction'])]
                if not np.isfinite(values).all() or min(values[:2]) < 0 or not all(0 <= v <= 1 for v in values[2:]):
                    raise ValueError('Invalid metrics')
                output.append(dict(geometry_id=g, seed=seed, bit_rule=rule,
                    covariance_axis_aspect=float(np.sqrt(eig[0]/eig[-1])),
                    normalized_gap_12=float((eig[0]-eig[1])/eig[0]),
                    normalized_gap_23=float((eig[1]-eig[2])/eig[0]),
                    miad_A3=values[0], miad_RCH=values[1], delta_miad=values[1]-values[0],
                    clipped_fraction=values[2], duplicate_key_fraction=values[3]))
    return output, used


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', type=Path, default=ROOT/'experiments/outputs/independent_benchmarks')
    parser.add_argument('--artifact-root', type=Path, default=ROOT/'analysis/generated')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    rows, sources = collect(args.input_root)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    content = stream.getvalue()
    out = args.artifact_root/'outputs/regime_diagnostics'
    figure = args.artifact_root/'figures/fig_regime_diagnostics.pdf'
    table = args.artifact_root/'tables/table_regime_diagnostics.tex'
    if args.validate_only:
        manifest = json.loads((out/'manifest.json').read_text())
        if manifest['sources_sha256'] != sources or (out/'cloud_diagnostics.csv').read_bytes() != content.encode():
            raise ValueError('Stale sources or diagnostic CSV')
        for relative, expected in manifest['outputs_sha256'].items():
            if digest(args.artifact_root/relative) != expected:
                raise ValueError(f'Stale diagnostic artifact: {relative}')
        print('Observed-regime matrix, shared-cloud hashes and published artifacts verified')
        return
    out.mkdir(parents=True, exist_ok=True); figure.parent.mkdir(parents=True, exist_ok=True); table.parent.mkdir(parents=True, exist_ok=True)
    (out/'cloud_diagnostics.csv').write_bytes(content.encode())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout='constrained')
    for g, color in zip(GEOMETRIES, ('C0', 'C1', 'C2', 'C3')):
        for rule, marker in zip(RULES, ('o', '^', 's')):
            group = [r for r in rows if r['geometry_id'] == g and r['bit_rule'] == rule]
            for ax, x in zip(axes, ('covariance_axis_aspect', 'normalized_gap_12')):
                ax.scatter([r[x] for r in group], [r['delta_miad'] for r in group],
                           color=color, marker=marker, s=15, alpha=.5, label=f'{g}/{rule[:2]}')
    for ax in axes:
        ax.axhline(0, color='black', linewidth=.8); ax.set_ylabel('MIAD(RCH) − MIAD(fixed Hilbert)')
    axes[0].set_xlabel('Sample covariance axis aspect √(λ1/λ3)')
    axes[1].set_xlabel('Normalized sample eigengap (λ1−λ2)/λ1')
    axes[1].legend(fontsize=6, ncol=3)
    fig.suptitle('Observed clean regimes: 80 clouds; 3 paired rules per cloud')
    fig.savefig(figure, metadata={'CreationDate': None}); plt.close(fig)
    lines = [r'\begin{tabular}{llrrrr}', r'\hline', r'Geometry & Rule & Clouds & Median $\Delta$MIAD & RCH lower & Median clip \\', r'\hline']
    for g in GEOMETRIES:
        for rule in RULES:
            group = [r for r in rows if r['geometry_id'] == g and r['bit_rule'] == rule]
            lines.append(f"{g} & {rule[:2]} & {len(group)} & {np.median([r['delta_miad'] for r in group]):.4f} & {sum(r['delta_miad'] < 0 for r in group)}/20 & {np.median([r['clipped_fraction'] for r in group]):.4f}" + r' \\')
    lines.extend([r'\hline', r'\end{tabular}'])
    table.write_text('\n'.join(lines)+'\n')
    outputs = [out/'cloud_diagnostics.csv', figure, table]
    manifest = dict(schema='rch.observed_regimes.v1', n_independent_clouds=80, n_paired_rule_observations=240,
        scope='D0 only, n=384, native rules; descriptive, no threshold learning, no causal or universal selection claim',
        sources_sha256=sources, outputs_sha256={str(p.relative_to(args.artifact_root)): digest(p) for p in outputs})
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Wrote observed-regime diagnostic CSV, figure, table and provenance manifest')


if __name__ == '__main__':
    main()
