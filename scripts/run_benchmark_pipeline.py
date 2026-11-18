#!/usr/bin/env python3
"""Plan, start, or resume benchmark measurements without discarding completed stages."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STAGES = ['bench-synthetic', 'bench-real', 'bench-independent', 'bench-cgal',
          'bench-extended', 'test-integration']
COMPLETION_STEPS = ['bench-test', 'bench-c1-resolution', 'bench-clamping-intervention', 'bench-cost-stability',
                    'app-query', 'bench-tree', 'bench-dbms', 'bench-application-cache',
                    'paper-artifacts', 'validate-extended-benchmarks', 'validate-application-cache']
# Only the failed/unrecorded substep's private outputs may be moved on resume.
STEP_OUTPUTS = {
    'bench-c1-resolution': ['c1_resolution_ablation'],
    'bench-clamping-intervention': ['clamping_intervention', 'real_clamping_checks'],
    'bench-cost-stability': ['cost_stability_scenarios'],
    'app-query': ['application_query/full_benchmark'],
    'bench-tree': ['tree_benchmark/full_benchmark'],
    'bench-dbms': ['dbms_benchmark/full_benchmark'],
    'bench-application-cache': ['application_cache/full_benchmark'],
}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stage_name(row):
    return row.get('stage') or row['command'][1]


def latest(records, target):
    return next((row for row in reversed(records) if stage_name(row) == target), None)


def pending_stages(state):
    return [target for target in STAGES
            if (latest(state['stages'], target) or {}).get('returncode') != 0]


def archive_directory(path):
    path = path.resolve()
    if not path.is_relative_to(ROOT / 'backups'):
        raise ValueError("archive must be under the repository's backups directory")
    return path


def save_state(path, state):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(path)


def run_command(target, records, state, state_file, evidence):
    attempt = 1 + sum(stage_name(row) == target for row in records)
    log = evidence / f'benchmark_run_{target}.attempt{attempt}.log'
    # Existing logs remain intact even when resuming an interrupted attempt.
    while log.exists():
        attempt += 1
        log = evidence / f'benchmark_run_{target}.attempt{attempt}.log'
    row = {'command': ['make', target], 'returncode': None,
           'log': str(log.relative_to(ROOT)), 'status': 'running'}
    records.append(row)
    save_state(state_file, state)
    print('START ' + target, flush=True)
    start = time.monotonic()
    with log.open('w') as stream:
        code = subprocess.run(row['command'], cwd=ROOT, stdout=stream,
                              stderr=subprocess.STDOUT).returncode
    row.update(returncode=code, elapsed_seconds=round(time.monotonic() - start, 2),
               status='passed' if code == 0 else 'failed')
    save_state(state_file, state)
    print(json.dumps(row), flush=True)
    return code


def archive_retry_outputs(target, state, state_file):
    archive = archive_directory(Path(state['archive_root']))
    for relative in STEP_OUTPUTS.get(target, []):
        source = ROOT / 'experiments/outputs' / relative
        if not source.exists():
            continue
        source.resolve().relative_to(ROOT)
        destination = archive / 'retry_outputs' / uuid4().hex / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Record intent before moving; no completed core matrix is in STEP_OUTPUTS.
        move = {'step': target, 'source': str(source.relative_to(ROOT)),
                'archive': str(destination), 'status': 'planned'}
        state.setdefault('retry_archives', []).append(move)
        save_state(state_file, state)
        shutil.move(str(source), str(destination))
        move['status'] = 'moved'
        save_state(state_file, state)


def run_completion(state, state_file, evidence):
    records = state.setdefault('completion_steps', [])
    group = {'stage': 'bench-extended', 'execution_mode': 'subtargets',
             'returncode': None, 'status': 'running'}
    state['stages'].append(group)
    save_state(state_file, state)
    start = time.monotonic()
    code = 0
    for target in COMPLETION_STEPS:
        if (latest(records, target) or {}).get('returncode') == 0:
            print('SKIP completed ' + target, flush=True)
            continue
        archive_retry_outputs(target, state, state_file)
        code = run_command(target, records, state, state_file, evidence)
        if code:
            break
    group.update(returncode=code, elapsed_seconds=round(time.monotonic() - start, 2),
                 status='passed' if code == 0 else 'failed')
    save_state(state_file, state)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='execute the displayed plan')
    parser.add_argument('--resume', action='store_true', help='reuse the saved stage checkpoints')
    parser.add_argument('--recheck-dependent', action='store_true',
                        help='explicitly requeue extended/application stages while keeping the four core stages')
    parser.add_argument('--restart', action='store_true', help='explicitly archive and restart an unfinished run')
    parser.add_argument('--archive-root', type=Path)
    args = parser.parse_args(argv)
    if args.resume and (args.restart or args.archive_root):
        parser.error('--resume uses the existing archive and cannot be combined with --restart/--archive-root')
    if args.recheck_dependent and not args.resume:
        parser.error('--recheck-dependent requires --resume')
    evidence = ROOT / 'experiments/logs/benchmark_pipeline'
    state_file = evidence / 'benchmark_run_results.json'
    if args.resume:
        state = json.loads(state_file.read_text())
        archive_directory(Path(state['archive_root']))
        if sha(ROOT / 'paper/manuscript.tex') != state['manuscript_sha256_before']:
            raise ValueError('manuscript differs from the saved run; inspect before resuming')
        if args.recheck_dependent:
            if any((latest(state['stages'], target) or {}).get('returncode') != 0 for target in STAGES[:4]):
                raise ValueError('the four core stages must have completed before a completion-only recheck')
            # Append history; a dry run modifies this in-memory copy only.
            reason = 'explicit completion recheck requested after application implementation change'
            for target in ['bench-extended', 'test-integration']:
                state['stages'].append({'stage': target, 'returncode': None,
                                        'status': 'recheck_requested', 'reason': reason})
            for target in COMPLETION_STEPS:
                state.setdefault('completion_steps', []).append({
                    'stage': target, 'returncode': None,
                    'status': 'recheck_requested', 'reason': reason})
    else:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        archive = archive_directory(args.archive_root or ROOT / 'backups' / f'benchmark_{stamp}')
        state = {'archive_root': str(archive), 'stages': []}
    pending = pending_stages(state)
    if not args.run:
        children = state.get('completion_steps', [])
        print(json.dumps({
            'action': 'resume plan only; no files changed' if args.resume else 'plan only; no files changed',
            'archive_root': state['archive_root'],
            'move_if_present': [] if args.resume else ['experiments/outputs', 'analysis/generated'],
            'skip_completed': [target for target in STAGES if target not in pending],
            'commands': [['make', target] for target in pending],
            'completion_substeps': [['make', target] for target in COMPLETION_STEPS
                                   if (latest(children, target) or {}).get('returncode') != 0]
                                   if 'bench-extended' in pending else [],
            'retry_outputs_if_present': [
                'experiments/outputs/' + name
                for target in COMPLETION_STEPS
                if 'bench-extended' in pending
                and (latest(children, target) or {}).get('returncode') != 0
                for name in STEP_OUTPUTS.get(target, [])
                if (ROOT / 'experiments/outputs' / name).exists()
            ] if args.resume else [],
            'manuscript_editing': False,
        }, indent=2))
        return
    if not args.resume:
        if state_file.exists() and not args.restart:
            previous = json.loads(state_file.read_text())
            if previous.get('stages') and pending_stages(previous):
                raise ValueError('unfinished run exists; use --run --resume (make resume-benchmarks), or explicitly --restart')
        archive = Path(state['archive_root'])
        if archive.exists():
            raise ValueError('archive destination already exists')
        archive.mkdir(parents=True)
        evidence.mkdir(parents=True, exist_ok=True)
        if state_file.exists():
            shutil.copyfile(state_file, archive / 'previous_rerun_results.json')
        state['manuscript_sha256_before'] = sha(ROOT / 'paper/manuscript.tex')
        save_state(state_file, state)
        for relative in ['experiments/outputs', 'analysis/generated']:
            source = ROOT / relative
            if source.exists():
                shutil.move(str(source), str(archive / relative.replace('/', '_')))
    for target in STAGES:
        if target not in pending:
            print('SKIP completed ' + target, flush=True)
            continue
        if target == 'bench-extended':
            code = run_completion(state, state_file, evidence)
        else:
            code = run_command(target, state['stages'], state, state_file, evidence)
        if code:
            raise SystemExit(code)
    state['manuscript_sha256_after'] = sha(ROOT / 'paper/manuscript.tex')
    state['manuscript_unchanged'] = state['manuscript_sha256_after'] == state['manuscript_sha256_before']
    save_state(state_file, state)
    if not state['manuscript_unchanged']:
        raise RuntimeError('manuscript changed during the run; inspect before using results')
    print('All measurement/artifact gates passed. Inspect benchmark_run_results.json and refreshed reports.', flush=True)


if __name__ == '__main__':
    main()
