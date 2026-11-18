#!/usr/bin/env python3
"""Refresh legacy interpretation labels only; no metrics, tests or figures run."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from analysis.scripts.legacy_claims import CLAIM_CAPTION, annotate_legacy_statistics, claim_status_rows
from analysis.scripts.make_paper_artifacts import write_table_bundle


def refresh(generated: Path) -> None:
    stats_path = generated / 'stats/synthetic_statistics.json'
    stats = json.loads(stats_path.read_text())
    original_values = json.dumps({key: stats.get(key) for key in ('hypotheses', 'stratified_by_bit_rule')}, sort_keys=True)
    annotate_legacy_statistics(stats)
    stats_path.write_text(json.dumps(stats, indent=2) + '\n')
    tables = generated / 'tables'
    real = json.loads((generated / 'stats/real_statistics.json').read_text())
    claim_meta = write_table_bundle(tables, 'table_mixed_claim_status.tex',
        claim_status_rows(stats, real), ['claim', 'status', 'evidence'], CLAIM_CAPTION, 'tab:claim_status')
    for name, caption in (
        ('table_synthetic_hypothesis_tests', 'Legacy synthetic analysis: nominal p-values and intervals; shared inputs not fully preserved'),
        ('table_synthetic_hypothesis_tests_by_bit_rule', 'Legacy per-rule summaries: nominal p-values; shared inputs remain dependent')):
        bundle_path = tables / (name + '.json')
        if bundle_path.exists():
            bundle = json.loads(bundle_path.read_text())
            write_table_bundle(tables, name + '.tex', bundle['rows'], bundle['columns'], caption, bundle['label'])
    manifest_path = generated / 'stats/paper_artifacts_manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest.setdefault('tables', {})['table_mixed_claim_status.tex'] = claim_meta
        manifest.setdefault('interpretation_updates', {})['legacy_statistics'] = dict(
            status='labels_only_no_numerical_reanalysis',
            previous_hypotheses_sha256=hashlib.sha256(original_values.encode()).hexdigest(),
            statistics_sha256=hashlib.sha256(stats_path.read_bytes()).hexdigest())
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated-root', type=Path, default=ROOT / 'analysis/generated')
    refresh(parser.parse_args().generated_root.resolve())
    print('Updated descriptive legacy labels; numerical results and benchmark files were preserved')


if __name__ == '__main__':
    main()
