#!/usr/bin/env python3
"""Count recorded estimator/axis fallbacks without rerunning or changing orderings."""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAME_METHODS = {'rch', 'pca_compact_hilbert', 'robust_frame_morton'}
NON_FRAME_METHODS = {'input', 'lexicographic', 'morton', 'isotropic_hilbert',
                     'compact_hilbert_aabb', 'external_cgal_spatial_sort'}
ROBUST_ESTIMATORS = {'det_mcd', 'mrcd', 'ogk'}
MODES = {'principal_eigenframe', 'canonical_axes_fallback'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_csv(path, records):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def classify(metadata):
    """Missing telemetry is unknown; canonical axes do not imply estimator failure."""
    method = metadata.get('method', 'unknown')
    if method not in FRAME_METHODS | NON_FRAME_METHODS:
        raise ValueError('unrecognized ordering method: ' + str(method))
    estimator = metadata.get('frame_estimator', 'unknown')
    fitted = metadata.get('fitted_frame_diagnostics')
    applicable = method in FRAME_METHODS or isinstance(fitted, dict)
    if not applicable:
        return {'frame_applicable': False, 'estimator': estimator,
                'robust_attempt': False, 'estimator_fallback': None, 'frame_mode': 'not_applicable'}
    flag = metadata.get('robust_fallback_used')
    if flag is not None and not isinstance(flag, bool):
        raise ValueError('robust_fallback_used must be boolean or unknown')
    mode = fitted.get('mode') if isinstance(fitted, dict) else None
    if mode is not None and mode not in MODES:
        raise ValueError('unrecognized frame mode: ' + str(mode))
    return {'frame_applicable': True, 'estimator': estimator,
            'robust_attempt': True if estimator in ROBUST_ESTIMATORS else
                              False if estimator in {'sample', 'sample_covariance'} else None,
            'estimator_fallback': flag, 'frame_mode': mode or 'unknown'}


def summarize(records):
    groups = collections.defaultdict(list)
    for row in records:
        if row['frame_applicable']:
            groups[row['family'], row['estimator']].append(row)
    result = []
    for (family, estimator), members in sorted(groups.items()):
        robust = [row for row in members if row['robust_attempt']]
        known = [row for row in robust if row['estimator_fallback'] is not None]
        frames = [row for row in members if row['frame_mode'] in MODES]
        result.append({
            'family': family, 'estimator': estimator, 'frame_records': len(members),
            'robust_attempt_records': len(robust), 'estimator_flag_known': len(known),
            'estimator_applicability_unknown': sum(row['robust_attempt'] is None for row in members),
            'estimator_fallback_records': sum(row['estimator_fallback'] is True for row in known),
            'estimator_flag_unknown': len(robust) - len(known),
            'frame_mode_known': len(frames),
            'canonical_axes_records': sum(row['frame_mode'] == 'canonical_axes_fallback' for row in frames),
            'frame_mode_unknown': len(members) - len(frames),
            'both_fallbacks_records': sum(row['estimator_fallback'] is True and
                                           row['frame_mode'] == 'canonical_axes_fallback' for row in robust),
            'scope': 'saved manifest counts; repeated configurations are not independent clouds',
        })
    return result


def checked_path(base, relative):
    path = (base / relative).resolve()
    path.relative_to(base.resolve())
    return path


def validate(output, artifact_root):
    state = read(output / 'analysis_manifest.json')
    if state['analyzer_sha256'] != digest(Path(__file__)):
        raise ValueError('fallback analyzer changed; regenerate evidence')
    for name, expected in state['sources_sha256'].items():
        if digest(checked_path(ROOT, name)) != expected:
            raise ValueError('fallback source changed: ' + name)
    for name, expected in state['artifacts'].items():
        if digest(checked_path(output, name)) != expected:
            raise ValueError('fallback artifact changed: ' + name)
    for name, expected in state.get('published_artifacts', {}).items():
        if digest(checked_path(artifact_root, name)) != expected:
            raise ValueError('published fallback artifact changed: ' + name)
    return {'status': 'passed', 'sources_checked': len(state['sources_sha256']),
            'records': state['manifest_records'], 'frame_records': state['frame_records']}


def analyze(args):
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources, records, seen = {}, [], set()

    def pin(path):
        path = path.resolve()
        sources[str(path.relative_to(ROOT))] = digest(path)
        return path

    def add(path, family, expected=None):
        path = path.resolve()
        if path in seen:
            raise ValueError('manifest was scheduled twice: ' + str(path))
        seen.add(path)
        pin(path)
        if expected is not None and sources[str(path.relative_to(ROOT))] != expected:
            raise ValueError('manifest checksum differs from inventory: ' + str(path))
        metadata = read(path)
        if metadata.get('status') != 'ok':
            raise ValueError('unsuccessful or unrecognized ordering manifest: ' + str(path))
        records.append({'family': family, 'manifest': str(path.relative_to(ROOT)),
                        'method': metadata.get('method', 'unknown'),
                        'refinement': metadata.get('refinement', 'unknown'),
                        'point_count': metadata.get('point_count', ''), **classify(metadata)})

    for family, base in [('synthetic', args.synthetic_root), ('real', args.real_root)]:
        for arm in ['off', 'all']:
            paths = sorted((base / arm / 'manifests').glob('*.manifest.json'))
            if not paths:
                raise ValueError(f'no {family}/{arm} ordering manifests')
            for path in paths:
                add(path, family + '/' + arm)
    inventory_path = pin(args.independent_root / 'benchmark_manifest.json')
    inventory = read(inventory_path)['files_sha256']
    for name, expected in sorted(inventory.items()):
        if '/manifests/' in name and name.endswith('.manifest.json'):
            add(checked_path(args.independent_root, name), 'independent/' + name.split('/')[0], expected)
    app_path = pin(args.application_root / 'run_manifest.json')
    app = read(app_path)
    for name, expected in app.get('source_sha256', {}).items():
        if digest(checked_path(ROOT, name)) != expected:
            raise ValueError('application source changed: ' + name)
        pin(checked_path(ROOT, name))
    for dataset in app['datasets']:
        for layout, entry in dataset['order_files'].items():
            # A0 layouts have Python-written metadata without frame telemetry.
            if layout.startswith('A0_'):
                continue
            add(checked_path(ROOT, entry['manifest_path']), 'application', entry['manifest_sha256'])
    cost_manifest = pin(args.cost_root / 'run_manifest.json')
    cost = read(cost_manifest)
    for name, expected in cost.get('source_sha256', {}).items():
        if digest(checked_path(ROOT, name)) != expected:
            raise ValueError('cost experiment source changed: ' + name)
        pin(checked_path(ROOT, name))
    for name, expected in sorted(cost['files_sha256'].items()):
        if name.startswith('orders/') and name.endswith('.json'):
            add(checked_path(args.cost_root, name), 'cost_stability', expected)
    summary = summarize(records)
    if not summary:
        raise ValueError('no applicable frame records')
    write_csv(output / 'fallback_records.csv', records)
    write_csv(output / 'fallback_summary.csv', summary)
    lines = ['# Recorded fallback evidence', '',
             'Counts are saved ordering manifests, not independent clouds or scene-level event rates.',
             'Repeated rules, contamination conditions, off/all arms and timing repetitions must not be pooled as independent trials.',
             'The estimator fallback flag and canonical-axis mode are separate mechanisms. Missing fields remain unknown.',
             'A false estimator fallback flag does not imply an exact/global MCD solution or absence of regularization.',
             'Exact estimator policy/reason and eigensolver-failure reason are not serialized by these CLI manifests; they cannot be inferred from the counts.',
             'Synthetic/real manifest filenames can be reused across runlists; counts describe unique saved paths, not every CSV row.',
             'Coverage: all saved *.manifest.json in the synthetic/real off/all manifest directories; inventoried independent manifests; application curve manifests; cost-stability order metadata.',
             'Native clamping helpers serialize a different diagnostics format without frame mode. They are outside this manifest table; no zero canonical rate is assigned to them.', '',
             '| Family | Estimator | Frame records | Estimator fallback / known | Canonical axes / known | Unknown applicability / flag / mode |',
             '|---|---|---:|---:|---:|---:|']
    for row in summary:
        estimator_count = (f"{row['estimator_fallback_records']}/{row['estimator_flag_known']}"
                           if row['estimator_flag_known'] else 'unknown' if row['robust_attempt_records'] or row['estimator_applicability_unknown'] else 'n/a')
        frame_count = (f"{row['canonical_axes_records']}/{row['frame_mode_known']}"
                       if row['frame_mode_known'] else 'unknown')
        lines.append(f"| {row['family']} | {row['estimator']} | {row['frame_records']} | {estimator_count} | {frame_count} | {row['estimator_applicability_unknown']}/{row['estimator_flag_unknown']}/{row['frame_mode_unknown']} |")
    (output / 'scope_and_results.md').write_text('\n'.join(lines) + '\n')
    tex = [r'\begin{tabular}{llrrr}', r'Family & Estimator & Records & Estimator fallback & Canonical axes \\', r'\hline']
    for row in summary:
        label = row['family'].replace('_', r'\_')
        estimator = row['estimator'].replace('_', r'\_')
        estimator_count = (f"{row['estimator_fallback_records']}/{row['estimator_flag_known']}"
                           if row['estimator_flag_known'] else 'unknown' if row['robust_attempt_records'] or row['estimator_applicability_unknown'] else 'n/a')
        frame_count = (f"{row['canonical_axes_records']}/{row['frame_mode_known']}"
                       if row['frame_mode_known'] else 'unknown')
        tex.append(f"{label} & {estimator} & {row['frame_records']} & {estimator_count} & {frame_count} " + r'\\')
    tex.append(r'\end{tabular}')
    (output / 'table_fallback_frequency.tex').write_text('\n'.join(tex) + '\n')
    published = {}
    if args.artifact_root:
        target = args.artifact_root / 'tables/table_fallback_frequency.tex'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((output / target.name).read_bytes())
        published[str(target.relative_to(args.artifact_root))] = digest(target)
    artifacts = {name: digest(output / name) for name in
                 ['fallback_records.csv', 'fallback_summary.csv', 'scope_and_results.md', 'table_fallback_frequency.tex']}
    state = {'schema': 'rch.fallback_evidence', 'analyzer_sha256': digest(Path(__file__)),
             'sources_sha256': sources, 'manifest_records': len(records),
             'frame_records': sum(row['frame_applicable'] for row in records),
             'artifacts': artifacts, 'published_artifacts': published,
             'native_clamping_frame_mode': 'not recorded in helper diagnostics; not included in this manifest census'}
    (output / 'analysis_manifest.json').write_text(json.dumps(state, indent=2) + '\n')
    return {'status': 'generated', 'manifest_records': len(records), 'summary_rows': len(summary)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic-root', type=Path, default=ROOT / 'experiments/outputs/synthetic_dataset')
    parser.add_argument('--real-root', type=Path, default=ROOT / 'experiments/outputs/real_dataset')
    parser.add_argument('--independent-root', type=Path, default=ROOT / 'experiments/outputs/independent_benchmarks')
    parser.add_argument('--application-root', type=Path, default=ROOT / 'experiments/outputs/application_query/full_benchmark')
    parser.add_argument('--cost-root', type=Path, default=ROOT / 'experiments/outputs/cost_stability_scenarios')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'analysis/generated/outputs/fallback_evidence')
    parser.add_argument('--artifact-root', type=Path, default=ROOT / 'analysis/generated')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    for name in vars(args):
        if isinstance(getattr(args, name), Path):
            setattr(args, name, getattr(args, name).resolve())
    print(json.dumps(validate(args.output_dir, args.artifact_root) if args.validate_only else analyze(args)))


if __name__ == '__main__':
    main()
