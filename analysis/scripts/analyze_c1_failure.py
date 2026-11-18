#!/usr/bin/env python3
"""Decompose recorded real-data C1 failures without running an orderer.

The measured path contributions are descriptive. Causal resolution contrasts
come from the separate fixed-frame runner, not from comparing C0 with C1 alone.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.runners.run_real_datasets import read_processed_points


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_rows(path: Path) -> list[dict]:
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def write_rows(path: Path, rows: list[dict]) -> None:
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def measure_order(points: np.ndarray, order_path: Path, meta: dict) -> dict:
    """Validate the permutation and split its MIAD sum at equal-key edges."""
    n = len(points)
    if points.shape != (n, 3) or n < 2 or not np.isfinite(points).all():
        raise ValueError('expected at least two finite XYZ points')
    order = read_rows(order_path)
    ids = np.array([int(r['raw_index']) for r in order], dtype=np.int64)
    keys = np.array([int(r['key']) for r in order], dtype=np.uint64)
    if len(ids) != n or not np.array_equal(np.sort(ids), np.arange(n)):
        raise ValueError('order is not a complete permutation')
    if [int(r['rank']) for r in order] != list(range(n)) or np.any(keys[1:] < keys[:-1]):
        raise ValueError('noncanonical ranks or unsorted curve keys')
    bits = meta['bits_axis']
    half = np.asarray(meta['frame_domain_half_extents'], dtype=float)
    if (len(bits) != 3 or any(type(b) is not int or not 1 <= b <= 32 for b in bits)
            or sum(bits) > 63 or not np.isfinite(half).all() or np.any(half < 0)):
        raise ValueError('invalid quantization domain/depth')
    widths = [math.ldexp(2 * float(h), -b) for h, b in zip(half, bits)]
    lengths = np.linalg.norm(np.diff(points[ids], axis=0), axis=1)
    same = keys[1:] == keys[:-1]
    _, counts = np.unique(keys, return_counts=True)
    q = meta.get('quantization_diagnostics', {})
    shared = int(counts[counts > 1].sum())
    if q.get('duplicate_hilbert_key_point_count', shared) != shared:
        raise ValueError('stored shared-key count disagrees with order file')
    within, cross = float(lengths[same].sum()), float(lengths[~same].sum())
    return dict(
        point_count=n, bits_axis=json.dumps(bits), total_bits=sum(bits),
        cell_widths=json.dumps(widths), cell_edge_ratio=max(widths) / min(widths) if min(widths) > 0 else '',
        miad=float(lengths.mean()), within_key_miad_contribution=within / (n - 1),
        cross_key_miad_contribution=cross / (n - 1),
        within_key_path_fraction=within / (within + cross) if within + cross else 0,
        same_key_edge_fraction=float(same.mean()), shared_key_point_fraction=shared / n,
        unique_keys=len(counts), max_key_group_size=int(counts.max()),
        clipped_point_fraction=q['domain_clipped_point_count'] / n if 'domain_clipped_point_count' in q else '',
        frame_mode=(meta.get('fitted_frame_diagnostics') or {}).get('mode', 'unknown'),
        robust_fallback_used=meta.get('robust_fallback_used', 'unknown'),
    )


def collect_recorded(real_root: Path, datasets: list[str]) -> tuple[list[dict], dict]:
    matrix_path = real_root / 'table_2_dataset_summary.csv'
    matrix = read_rows(matrix_path)
    sources = {str(matrix_path.resolve()): digest(matrix_path)}
    output = []
    for dataset in datasets:
        input_hash = None
        for algorithm, rule in (('A3_isotropic_hilbert', 'C0_uniform'),
                                ('A5_pca_compact_hilbert', 'C0_uniform'),
                                ('A5_pca_compact_hilbert', 'C1_monotone_half'),
                                ('A6_rch', 'C0_uniform'), ('A6_rch', 'C1_monotone_half')):
            matches = [r for r in matrix if r['dataset_id'] == dataset and r['algorithm_id'] == algorithm
                       and r['bit_rule'] == rule and r['seed'] == '0' and r['contamination_id'] == 'D0']
            if len(matches) != 1:
                raise ValueError(f'missing/duplicate recorded cell: {dataset}/{algorithm}/{rule}')
            row = matches[0]
            if row.get('refinement', 'off') != 'off':
                raise ValueError('expected unrefined results')
            stem = f'{dataset}__{algorithm}__{rule}__D0__s0'
            meta_path = real_root / 'manifests' / (stem + '.manifest.json')
            order_path = real_root / 'orders' / (stem + '.order.csv')
            meta = json.loads(meta_path.read_text())
            if meta.get('hash') != row['output_hash'] or meta.get('status') != 'ok':
                raise ValueError('recorded CSV/manifest mismatch')
            path = Path(meta['input'])
            path = path if path.is_absolute() else ROOT / path
            actual_hash = digest(path)
            if input_hash is not None and actual_hash != input_hash:
                raise ValueError('methods did not use identical input bytes')
            input_hash = actual_hash
            points = np.asarray(read_processed_points(path), dtype=float)
            measured = measure_order(points, order_path, meta)
            if not math.isclose(measured['miad'], float(row['miad']), rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError('recomputed MIAD disagrees with stored result; inputs may be stale')
            eigen = np.linalg.eigvalsh(np.cov(points, rowvar=False))[::-1]
            bbox = np.ptp(points, axis=0)
            output.append(dict(dataset_id=dataset, algorithm_id=algorithm, bit_rule=rule,
                bbox_aspect=float(max(bbox) / min(bbox)) if min(bbox) > 0 else '',
                covariance_axis_aspect=float(np.sqrt(eigen[0] / eigen[-1])) if eigen[-1] > 0 else '',
                sample_gap12=float((eigen[0] - eigen[1]) / eigen[0]) if eigen[0] > 0 else '',
                sample_gap23=float((eigen[1] - eigen[2]) / eigen[0]) if eigen[0] > 0 else '',
                frame_center=json.dumps(meta['frame_center']), frame_axes=json.dumps(meta['frame_axes']),
                half_extents=json.dumps(meta['frame_domain_half_extents']), **measured))
            for p in (path, meta_path, order_path):
                sources[str(p.resolve())] = digest(p)
    return output, sources


def publish(rows: list[dict], sources: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_rows(output / 'diagnostics.csv', rows)
    contrasts = []
    for row in rows:
        if row['bit_rule'] != 'C1_monotone_half':
            continue
        c0 = next(r for r in rows if r['dataset_id'] == row['dataset_id']
                  and r['algorithm_id'] == row['algorithm_id'] and r['bit_rule'] == 'C0_uniform')
        fixed = all(row[k] == c0[k] for k in ('frame_center', 'frame_axes', 'half_extents'))
        if not fixed:
            raise ValueError('C0/C1 frame/domain changed; cannot describe a fixed-frame contrast')
        contrasts.append(dict(dataset_id=row['dataset_id'], algorithm_id=row['algorithm_id'],
            same_frame_and_domain=fixed, delta_miad_c1_minus_c0=row['miad'] - c0['miad'],
            delta_within_key_contribution=row['within_key_miad_contribution'] - c0['within_key_miad_contribution'],
            delta_cross_key_contribution=row['cross_key_miad_contribution'] - c0['cross_key_miad_contribution']))
    write_rows(output / 'contrasts.csv', contrasts)
    text = ['# Recorded C1 interpretation', '',
            'These numbers are recomputed from existing records, not a clean benchmark rerun. '
            'Values may change after new measurements. No population or causal conclusion is inferred.', '']
    for row in rows:
        if row['bit_rule'] != 'C1_monotone_half':
            continue
        text.append(f"- {row['dataset_id']} / {row['algorithm_id']}: bits {row['bits_axis']}; "
                    f"MIAD {row['miad']:.7g}; shared-key points {row['shared_key_point_fraction']:.5%}; "
                    f"within-key path contribution {row['within_key_path_fraction']:.5%}; "
                    f"clipped fraction {row['clipped_point_fraction']!s}.")
    text += ['', 'The C1 allocator greedily spends half of the maximum equal-axis budget on '
             'the longest axes first (see bit_allocation_monotone.hpp). With a 10-bit axis cap '
             'and 1-bit minimum, ranked axes receive 10/4/1 bits: the last axis has two bins. '
             'This is the specified heuristic, not evidence of an encoder bug. C0/C1 comparisons '
             'change total bits and their distribution. Equal-budget balancing in the optional '
             'fixed-frame experiment is needed to separate these mechanisms.']
    (output / 'interpretation.md').write_text('\n'.join(text) + '\n')
    (output / 'scope.md').write_text(
        '# Recorded C1 failure diagnostics\n\n'
        'One fixed dataset per site, seed 0 only; repeated seed labels are not independent scenes. '
        'Recomputed MIAD must agree with recorded CSVs. C0/C1 frame and covering-domain equality is checked. '
        'C1 changes both the bit budget and its distribution: this comparison does not isolate either alone. '
        'Within-key and cross-key contributions sum to MIAD; their fractions describe the observed path, '
        'not a causal tie-breaking loss. Missing clipping diagnostics remain unknown. '
        'No scene-level confidence intervals or deployable selection thresholds are inferred. '
        'Use run_c1_resolution_ablation.py for equal-budget and fixed-domain interventions.\n')
    (output / 'manifest.json').write_text(json.dumps(dict(schema='rch.c1_failure_diagnostics.v1',
        sources_sha256=sources, analyzer_sha256=digest(Path(__file__)),
        outputs_sha256={p.name: digest(p) for p in output.iterdir() if p.name in
                       ('diagnostics.csv', 'contrasts.csv', 'scope.md', 'interpretation.md')}), indent=2) + '\n')


def publish_controls(root: Path, output: Path) -> None:
    """Publish only complete, inventoried interventions; never launch a runner."""
    manifest_path = root / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 'rch.c1_resolution_ablation.v1':
        raise ValueError('invalid C1 control schema')
    for name, expected in manifest['files_sha256'].items():
        path = (root / name).resolve()
        path.relative_to(root.resolve())
        if digest(path) != expected:
            raise ValueError(f'changed control artifact: {name}')
    for path, expected in manifest['sources_sha256'].items():
        if digest(Path(path)) != expected:
            raise ValueError(f'changed control source: {path}')
    output.mkdir(parents=True, exist_ok=True)
    for name in ('metrics.csv', 'scope.md', 'run_manifest.json'):
        shutil.copyfile(root / name, output / name)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--real-root', type=Path, default=ROOT / 'experiments/outputs/real_dataset/off')
    p.add_argument('--output-dir', type=Path, default=ROOT / 'analysis/generated/outputs/c1_failure_diagnostics')
    p.add_argument('--dataset', action='append')
    p.add_argument('--ablation-root', type=Path, help='publish existing fixed-frame controls instead of reading the legacy matrix')
    args = p.parse_args()
    if args.ablation_root:
        publish_controls(args.ablation_root.resolve(), args.output_dir.resolve())
        print('Published recorded C1 controls; no ordering benchmark was executed')
        return
    rows, sources = collect_recorded(args.real_root.resolve(), args.dataset or ['stanford_bunny', 'stanford_armadillo'])
    publish(rows, sources, args.output_dir)
    print(f'Wrote {len(rows)} recorded cells; no ordering benchmark was executed')


if __name__ == '__main__':
    main()
