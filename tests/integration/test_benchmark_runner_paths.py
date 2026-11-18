"""Exercise real runner entry points with relative/absolute CLI paths on one cloud."""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    source_root = ROOT / 'experiments/outputs/independent_benchmarks'
    parent = source_root / 'frame_ablation_bit_rules/off'
    with (parent / 'frame_ablation_bit_rules.csv').open() as stream:
        records = list(csv.DictReader(stream))
    records = [r for r in records if r['geometry_id'] == 'E0' and int(r['seed']) == 0]
    inventory = json.loads((source_root / 'benchmark_manifest.json').read_text())['files_sha256']
    with tempfile.TemporaryDirectory(prefix='benchmark_paths_', dir=ROOT / 'build') as directory:
        work = Path(directory)
        fixture = work / 'input'
        destination = fixture / 'frame_ablation_bit_rules/off'
        (destination / 'data').mkdir(parents=True)
        with (destination / 'frame_ablation_bit_rules.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        hashes = {}
        for row in records:
            filename = f"{row['algorithm_id']}__{row['bit_rule']}__{row['contamination_id']}__E0__n256__s0.csv"
            relative = 'frame_ablation_bit_rules/off/data/' + filename
            shutil.copyfile(source_root / relative, fixture / relative)
            hashes[relative] = inventory[relative]
        (fixture / 'benchmark_manifest.json').write_text(json.dumps({'files_sha256': hashes}))
        results = {}
        for family, runner, binary in [
            ('clamping', 'run_clamping_ablation.py', 'rch_clamping_ablation'),
            ('cost', 'run_cost_stability_scenarios.py', 'rch_order'),
        ]:
            variants = []
            for kind in ['relative', 'absolute']:
                output = work / f'{family}_{kind}'
                command = [sys.executable, str(ROOT / 'experiments/runners' / runner)]
                for flag, path in [('--input-root', fixture), ('--output-dir', output),
                                   ('--binary', ROOT / 'build/bench/src/cli' / binary)]:
                    command += [flag, str(path.relative_to(ROOT)) if kind == 'relative' else str(path)]
                command += ['--seed-limit', '1']
                run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
                if run.returncode:
                    raise AssertionError(f'{family}/{kind}: {run.stdout}\n{run.stderr}')
                state = json.loads((output / 'run_manifest.json').read_text())
                assert state['n_clouds'] == 1
                assert all(not Path(name).is_absolute() for name in state['input_sha256'])
                variants.append(state['input_sha256'])
            assert variants[0] == variants[1]
            results[family] = {'status': 'passed', 'clouds': 1,
                               'variants': ['relative', 'absolute'],
                               'identical_input_provenance': True}
        print(json.dumps(results))


if __name__ == '__main__':
    main()
