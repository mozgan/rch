#!/usr/bin/env python3
"""Validate and analyze paired natural versus frozen-resolution inlier stability."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
import numpy as np
import yaml

FRAMES = ('A5_pca_compact_hilbert', 'A6_rch')
RULES = ('C2_occupancy_floor1', 'C3_frame_core_occupancy', 'C4_hybrid')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def validate(root):
    manifest = json.loads((root / 'run_manifest.json').read_text())
    if manifest['schema'] != 'rch.frame_stability.v1':
        raise ValueError('wrong stability schema')
    for name, checksum in manifest['files_sha256'].items():
        path = (root / name).resolve(); path.relative_to(root.resolve())
        if digest(path) != checksum:
            raise ValueError('stability checksum mismatch: ' + name)
    for name, checksum in [('runlist.yaml', manifest['runlist_sha256']), ('natural_results.csv', manifest['natural_results_sha256'])]:
        if digest(root / name) != checksum:
            raise ValueError('source snapshot mismatch')
    spec = yaml.safe_load((root / 'runlist.yaml').read_text())
    blocks = {(g, n, s) for g in spec['geometry_ids'] for n in spec['point_counts'] for s in spec['seeds']}
    conditions = spec['stability_control']['expected_contaminations']
    levels = spec['stability_control']['resolution_refinements']
    if manifest['conditions'] != conditions or manifest['resolution_refinements'] != levels:
        raise ValueError('control protocol mismatch')
    shifts = spec['stability_control'].get('grid_shifts_cells', [0.0])
    if manifest.get('grid_shifts_cells', [0.0]) != shifts: raise ValueError('grid origin protocol mismatch')
    all_values = {}
    natural = rows(root / 'natural_results.csv')
    controlled = rows(root / 'frame_stability.csv')
    for protocol, selected in [('natural', natural), *[(f'matched_resolution_{level}' + (f'_shift_{shift:g}' if shift else ''), [r for r in controlled if int(r['resolution']) == level and float(r.get('grid_shift_cells', 0)) == shift]) for level in levels for shift in shifts]]:
        index = {}
        for r in selected:
            block = r['geometry_id'], int(r['clean_point_count']), int(r['seed'])
            key = block, r['algorithm_id'], r['bit_rule'], r['contamination_id']
            if key in index:
                raise ValueError('duplicate stability cell')
            value = float(r['kendall_tau_clean'])
            if not math.isfinite(value) or not -1 <= value <= 1:
                raise ValueError('invalid Kendall value')
            if key[-1] == 'D0' and value != 1.0:
                raise ValueError('clean baseline must equal itself')
            index[key] = value
        expected = {(block, a, rule, d) for block in blocks for a in FRAMES for rule in RULES for d in conditions}
        if set(index) != expected:
            raise ValueError('incomplete stability factorial')
        all_values[protocol] = index
    if len(controlled) != len(blocks) * len(FRAMES) * len(RULES) * len(conditions) * len(levels) * len(shifts):
        raise ValueError('unexpected controlled levels/rows')
    source_blocks = {(b['geometry'], b['clean_count'], b['seed']): b for b in manifest['blocks']}
    if set(source_blocks) != blocks:
        raise ValueError('invalid quantizer block inventory')
    from sys import path as sys_path
    sys_path.insert(0, str(Path(__file__).resolve().parents[2] / 'experiments/runners'))
    from run_matrix import read_order_csv, kendall_tau_against_clean, is_permutation_of_size
    baseline = {}
    for r in controlled:
        if r['contamination_id'] == 'D0':
            key = r['geometry_id'], int(r['clean_point_count']), int(r['seed']), r['algorithm_id'], r['bit_rule'], int(r['resolution']), float(r.get('grid_shift_cells', 0))
            baseline[key] = read_order_csv(root / r['order_file'])
    for r in controlled:
        block = r['geometry_id'], int(r['clean_point_count']), int(r['seed'])
        reference = source_blocks[block]
        level = int(r['resolution'])
        bits = json.loads(r['bits_axis']); half = json.loads(r['half_extents']); widths = json.loads(r['cell_widths'])
        if bits != [b + level for b in reference['depths'][r['bit_rule']]] or half != reference['half_extents'][r['bit_rule']]:
            raise ValueError('frozen domain/depth drift')
        expected_widths = [math.ldexp(x, -level) for x in reference['base_cell_widths']]
        if any(math.ldexp(half[j], 1 - bits[j]) != expected_widths[j] or widths[j] != expected_widths[j] for j in range(3)):
            raise ValueError('physical resolution is not equal in all six cells')
        if r['input_sha256'] != reference['input_hashes'][r['contamination_id']]:
            raise ValueError('input pairing mismatch')
        if r['order_file'] not in manifest['files_sha256'] or r['manifest_file'] not in manifest['files_sha256']:
            raise ValueError('missing permutation/manifest checksum')
        meta = json.loads((root / r['manifest_file']).read_text())
        if float(meta.get('frame_grid_shift_cells', 0)) != float(r.get('grid_shift_cells', 0)):
            raise ValueError('C++ origin shift mismatch')
        if 'input_file' in r:
            for field in ('input_file', 'natural_manifest_file', 'tie_break_order_file'):
                if r[field] not in manifest['files_sha256']: raise ValueError('control snapshot missing from inventory')
            natural_meta = json.loads((root / r['natural_manifest_file']).read_text())
            for field in ('frame_center', 'frame_axes', 'robust_fallback_used'):
                if meta[field] != natural_meta[field]: raise ValueError('quantizer changed fitted frame')
            path = root / r['input_file']
            if digest(path) != r['input_sha256']: raise ValueError('snapshot input mismatch')
            points = [tuple(map(float, x)) for x in csv.reader(path.open())]
            clean_path = root / reference['input_files']['D0']
            clean_points = [tuple(map(float, x)) for x in csv.reader(clean_path.open())]
            if len(points) != int(r['point_count']) or len(clean_points) != block[1] or points[:block[1]] != clean_points:
                raise ValueError('control input does not preserve inlier IDs')

            tie = read_order_csv(root / r['tie_break_order_file'])
            if tie != sorted(range(len(points)), key=lambda i: (*points[i], i)):
                raise ValueError('incorrect raw-coordinate tie-break control')

        if not meta.get('controlled_frame_quantizer') or meta['bits_axis'] != bits or meta['frame_domain_half_extents'] != half or meta['hash'] != r['output_hash']:
            raise ValueError('resolved C++ quantizer mismatch')
        order = read_order_csv(root / r['order_file'])
        clean = baseline[(*block, r['algorithm_id'], r['bit_rule'], level, float(r.get('grid_shift_cells', 0)))]
        if not is_permutation_of_size(order, int(r['point_count'])) or not is_permutation_of_size(clean, block[1]):
            raise ValueError('invalid controlled point permutation')
        if 'input_file' in r:
            if not math.isclose(kendall_tau_against_clean(tie, order, len(points)), float(r['kendall_vs_raw_tie_break']), abs_tol=1e-14):
                raise ValueError('tie-break comparison mismatch')
        if not math.isclose(kendall_tau_against_clean(clean, order, block[1]), float(r['kendall_tau_clean']), abs_tol=1e-14):
            raise ValueError('inlier Kendall recomputation failed')
    return manifest, all_values, controlled


def analyze(root, output, draws=20000, artifact_root=None):
    manifest, protocols, controlled = validate(root)
    output.mkdir(parents=True, exist_ok=True)
    effects = []
    estimates = []
    rng = np.random.default_rng(20261105)
    for protocol, index in protocols.items():
        blocks = sorted({key[0] for key in index})
        contrasts = defaultdict(dict)
        for block in blocks:
            overall = []
            for d in manifest['conditions'][1:]:
                frame = {rule: index[block, FRAMES[1], rule, d] - index[block, FRAMES[0], rule, d] for rule in RULES}
                for rule, value in frame.items():
                    contrasts[f'frame:{rule}:{d}'][block] = value
                    overall.append(value)
                for rule in RULES[1:]:
                    contrasts[f'frame_x_rule:{rule}-C2:{d}'][block] = frame[rule] - frame[RULES[0]]
                    for a in FRAMES:
                        contrasts[f'rule:{a}:{rule}-C2:{d}'][block] = index[block, a, rule, d] - index[block, a, RULES[0], d]
            contrasts['frame:cloud_mean_over_rules_and_contamination'][block] = float(np.mean(overall))
        for contrast, values in contrasts.items():
            strata = defaultdict(list)
            for (g, n, seed), effect in values.items():
                strata[g, n].append(effect)
                effects.append({'protocol': protocol, 'contrast': contrast, 'geometry_id': g, 'clean_point_count': n, 'seed': seed, 'effect': effect})
            pooled = np.array(list(values.values()))
            samples = np.concatenate([rng.choice(v, size=(draws, len(v))) for _, v in sorted(strata.items())], axis=1)
            bootstrap = np.median(samples, axis=1)
            estimates.append({'protocol': protocol, 'contrast': contrast, 'n_clouds': len(pooled),
                              'median_cloud_effect': float(np.median(pooled)), 'ci95_low': float(np.quantile(bootstrap, .025)),
                              'ci95_high': float(np.quantile(bootstrap, .975)), 'bootstrap_resamples': draws,
                              'inference_scope': 'cloud resampling within fixed geometry/size strata; conditions/rules kept in cloud blocks; descriptive unadjusted intervals'})
    for name, records in [('frame_stability_effects.csv', effects), ('frame_stability_summary.csv', estimates)]:
        with (output / name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    diagnostics = []
    for r in controlled:
        counts = json.loads(r['quantization_diagnostics'])
        total = int(r['point_count'])
        record = {key: r[key] for key in ('geometry_id', 'clean_point_count', 'seed', 'algorithm_id', 'bit_rule', 'contamination_id', 'resolution', 'cell_widths', 'bits_axis', 'half_extents')}
        record['grid_shift_cells'] = r.get('grid_shift_cells', '0')
        record['kendall_vs_raw_tie_break'] = r.get('kendall_vs_raw_tie_break', '')
        record['robust_fallback_used'] = r['robust_fallback_used']
        for field in ('domain_clipped_point_count', 'duplicate_quantized_tuple_point_count', 'duplicate_hilbert_key_point_count'):
            record[field.replace('_count', '_fraction')] = counts[field] / total
        diagnostics.append(record)
    with (output / 'frame_stability_grid_diagnostics.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(diagnostics[0])); writer.writeheader(); writer.writerows(diagnostics)
    (output / 'protocol_limits.md').write_text(
        '# R2.1 stability scope\n\nNatural arms retain C2/C3/C4 adaptive policies. Matched-resolution arms are controlled interventions, '
        'not unmodified native rules. They freeze each rule\'s domain/depth across both frames and all contamination levels; '
        'all six cells share physical axis cell widths. These grid parameters are symmetric in the two frames and use the '
        'predeclared full contamination design; they are not a deployable grid estimator trained only on clean observations. '
        'Frame includes center and axes, not orientation alone. Very coarse grids, clipping, collisions and zero contrasts '
        'must be reported; predeclared depth and grid-origin sensitivities are included without changing fitted frames. Multiple rules may coincide '
        'under the intervention; this is reported, not treated as additional independent evidence. '
        'D0 baselines are recomputed under each matched quantizer. Only original inlier IDs contribute to Kendall. '
        'No frame superiority claim is justified before inspecting the actual effect estimates.\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    cols = min(4, len(protocols)); nr = math.ceil(len(protocols) / cols)
    fig, axes = plt.subplots(nr, cols, figsize=(5 * cols, 4 * nr), squeeze=False, constrained_layout=True)
    conditions = manifest['conditions'][1:]
    for ax, protocol in zip(axes.flat, protocols):
        for rule in RULES:
            selected = [next(e for e in estimates if e['protocol'] == protocol and e['contrast'] == f'frame:{rule}:{d}') for d in conditions]
            values = [e['median_cloud_effect'] for e in selected]
            # Percentile CI need not contain the sample median; draw endpoints directly.
            x = np.arange(len(conditions))
            ax.plot(x, values, marker='o', label=rule[:2])
            ax.vlines(x, [e['ci95_low'] for e in selected], [e['ci95_high'] for e in selected], alpha=.45)
        ax.axhline(0, color='black', linewidth=.7)
        ax.set_xticks(range(len(conditions)), conditions)
        ax.set_title(protocol); ax.set_ylabel('Median paired Kendall difference (RCH - PCA)'); ax.legend()
    for ax in list(axes.flat)[len(protocols):]: ax.set_visible(False)
    fig.savefig(output / 'fig_frame_stability.pdf'); plt.close(fig)
    lines = [r'\begin{tabular}{llrrr}', r'Protocol & Contrast & Effect & CI low & CI high \\', r'\hline']
    for e in estimates:
        if e['contrast'] == 'frame:cloud_mean_over_rules_and_contamination':
            lines.append(e['protocol'].replace('_', r'\_') + r' & Cloud mean contrast & ' + f"{e['median_cloud_effect']:.5f} & {e['ci95_low']:.5f} & {e['ci95_high']:.5f}" + r' \\')
    lines.append(r'\end{tabular}')
    (output / 'table_frame_stability.tex').write_text('\n'.join(lines) + '\n')
    published = {}
    if artifact_root:
        import shutil
        for folder, name in [('figures', 'fig_frame_stability.pdf'), ('tables', 'table_frame_stability.tex')]:
            (artifact_root / folder).mkdir(parents=True, exist_ok=True); shutil.copyfile(output / name, artifact_root / folder / name)
            published[str(Path(folder) / name)] = digest(artifact_root / folder / name)
    (output / 'analysis_manifest.json').write_text(json.dumps({'status': 'validated_frame_stability', 'source_manifest_sha256': digest(root / 'run_manifest.json'),
        'artifacts': {p.name: digest(p) for p in output.iterdir() if p.is_file() and p.name != 'analysis_manifest.json'},
        'published_artifacts': published}, indent=2) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root', type=Path, required=True); p.add_argument('--output-dir', type=Path)
    p.add_argument('--artifact-root', type=Path); p.add_argument('--bootstrap-resamples', type=int, default=20000)
    p.add_argument('--validate-only', action='store_true')
    a = p.parse_args()
    if a.validate_only:
        validate(a.input_root)
        if a.output_dir:
            state = json.loads((a.output_dir / 'analysis_manifest.json').read_text())
            if state['source_manifest_sha256'] != digest(a.input_root / 'run_manifest.json'):
                raise ValueError('stale stability analysis')
            for name, checksum in state['artifacts'].items():
                if digest(a.output_dir / name) != checksum: raise ValueError('stale stability artifact')
            if a.artifact_root:
                if not state['published_artifacts']: raise ValueError('published stability artifacts missing')
                for name, checksum in state['published_artifacts'].items():
                    if digest(a.artifact_root / name) != checksum: raise ValueError('stale published stability artifact')
        print('frame stability matrix, equal resolution and inlier Kendall verified')
    else:
        if a.bootstrap_resamples < 100: p.error('at least 100 bootstrap draws required')
        analyze(a.input_root, a.output_dir or a.input_root / 'analysis', a.bootstrap_resamples, a.artifact_root)


if __name__ == '__main__':
    main()
