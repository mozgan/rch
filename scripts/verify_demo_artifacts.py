#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# verify_demo_artifacts.py — demo artifact layout verifier.
#
# References:
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Verify the Makefile demo benchmark artifact layout.

Algorithm: load generated CSV/JSON/YAML artifacts, require expected tables,
algorithm/bit-rule coverage, finite metric fields, portable relative paths,
and a snapshot file count consistent with the copied output tree.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

import yaml

SYNTHETIC_TABLES = (
    "table_3_locality",
    "table_4_outlier",
    "table_5_runtime",
)
REAL_TABLES = ("table_2_dataset_summary",)
MODES = ("off", "all")
TEXT_SUFFIXES = {".csv", ".json", ".yaml", ".yml"}
REQUIRED_TABLE_CSVS = (
    "table_synthetic_locality_summary.csv",
    "table_synthetic_contamination_stability.csv",
    "table_synthetic_runtime_summary.csv",
    "table_synthetic_hypothesis_tests.csv",
    "table_synthetic_hypothesis_tests_by_bit_rule.csv",
    "table_real_dataset_summary.csv",
    "table_real_directional_h1_comparisons.csv",
)


def load_yaml_mapping(path: Path) -> dict[str, object]:
    """Load a YAML file that must contain a mapping."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise AssertionError(f"{path} must contain a YAML mapping")
    return data


def load_algorithm_configs(config_dir: Path) -> dict[str, dict[str, object]]:
    """Load algorithm configs used to derive verifier expectations."""
    algorithms: dict[str, dict[str, object]] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        data = load_yaml_mapping(path)
        algorithm_id = data.get("id")
        if not isinstance(algorithm_id, str) or not algorithm_id:
            raise AssertionError(f"{path} has no algorithm id")
        algorithms[algorithm_id] = data
    if not algorithms:
        raise AssertionError(f"no algorithm configs found in {config_dir}")
    return algorithms


def expected_supported_bit_rules(
    runlist: dict[str, object], algorithms: dict[str, dict[str, object]]
) -> dict[str, tuple[str, ...]]:
    """Return algorithm -> expected bit-rule ids after runner support filtering."""
    bit_rules = runlist.get("bit_rules")
    algorithm_ids = runlist.get("algorithm_ids")
    if not isinstance(bit_rules, list) or not bit_rules:
        raise AssertionError("runlist requires a non-empty bit_rules list")
    if not isinstance(algorithm_ids, list) or not algorithm_ids:
        raise AssertionError("runlist requires a non-empty algorithm_ids list")

    runlist_rules: list[str] = []
    for rule in bit_rules:
        if not isinstance(rule, dict):
            raise AssertionError("runlist bit_rules entries must be mappings")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise AssertionError("runlist bit_rules entries must have string ids")
        runlist_rules.append(rule_id)
    expected: dict[str, tuple[str, ...]] = {}
    for algorithm_id in [str(item) for item in algorithm_ids]:
        if algorithm_id not in algorithms:
            raise AssertionError(f"runlist references unknown algorithm: {algorithm_id}")
        supported = algorithms[algorithm_id].get("supported_bit_rules")
        if isinstance(supported, list):
            supported_set = {str(item) for item in supported}
            rules = tuple(rule for rule in runlist_rules if rule in supported_set)
        else:
            rules = tuple(runlist_rules)
        if not rules:
            raise AssertionError(
                f"runlist leaves {algorithm_id} with no supported bit-rule variants"
            )
        expected[algorithm_id] = rules
    return expected


def expected_algorithms(
    expected_rules_by_table: dict[str, dict[str, tuple[str, ...]]]
) -> set[str]:
    """Return algorithms expected in at least one checked runlist."""
    return {
        algorithm_id
        for expected_rules in expected_rules_by_table.values()
        for algorithm_id in expected_rules
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a non-empty CSV table into dictionaries."""
    if not path.exists():
        raise AssertionError(f"missing CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AssertionError(f"empty CSV: {path}")
    return rows


def check_required_table_csvs(tables_dir: Path) -> None:
    """Require every demo CSV emitted by the synthetic and real table builders."""
    for filename in REQUIRED_TABLE_CSVS:
        read_csv(tables_dir / filename)


def require(path: Path) -> None:
    """Require that an expected artifact path exists."""
    if not path.exists():
        raise AssertionError(f"missing path: {path}")


def require_absent(path: Path) -> None:
    """Require that stale heavyweight artifact subtrees are absent."""
    if path.exists():
        raise AssertionError(f"unexpected stale path: {path}")


def assert_no_full_paths(paths: list[Path], repo_root: Path) -> None:
    repo_prefix = str(repo_root.resolve())
    absolute_path = re.compile(r"(^|[,\"':\\s])/(home|work|tmp|var|usr|opt)/")
    offenders: list[str] = []
    for root in paths:
        if root.is_file():
            candidates = [root]
        elif root.exists():
            candidates = [
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix in TEXT_SUFFIXES
            ]
        else:
            candidates = []
        for path in candidates:
            text = path.read_text(encoding="utf-8")
            if repo_prefix in text or "file://" in text or absolute_path.search(text):
                offenders.append(str(path))
    if offenders:
        raise AssertionError(
            "generated CSV/JSON/YAML files contain full paths: "
            + ", ".join(offenders[:20])
        )


def finite_values(rows: list[dict[str, str]], field: str) -> int:
    """Count rows whose selected field parses to a finite float."""
    count = 0
    for row in rows:
        value = row.get(field, "")
        if not value:
            continue
        number = float(value)
        if math.isfinite(number):
            count += 1
    return count


def nullish_locations(value: object, label: str) -> list[str]:
    if value is None:
        return [label]
    if isinstance(value, float) and not math.isfinite(value):
        return [label]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.extend(nullish_locations(item, f"{label}.{key}"))
        return out
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            out.extend(nullish_locations(item, f"{label}[{index}]"))
        return out
    return []


def check_no_nullish_stats(stats_dir: Path) -> None:
    offenders: list[str] = []
    for name in ("synthetic_statistics.json", "real_statistics.json"):
        path = stats_dir / name
        require(path)
        offenders.extend(
            nullish_locations(json.loads(path.read_text(encoding="utf-8")), name)
        )
    if offenders:
        raise AssertionError(
            "demo statistics contain null/NaN values: " + ", ".join(offenders[:20])
        )


def expected_refinement_for_row(row: dict[str, str], expected_refinement: str) -> str:
    """Return the required refinement tag for one demo result row."""
    algorithm_id = row.get("algorithm_id", "")
    if algorithm_id == "A7_cgal_spatial_sort":
        return "external"
    if algorithm_id == "A0_input":
        return "off"
    return expected_refinement


def check_mode_rows(
    base: Path,
    mode: str,
    table_names: tuple[str, ...],
    expected_refinement: str,
    expected_rules_by_table: dict[str, dict[str, tuple[str, ...]]],
) -> list[dict[str, str]]:
    all_rows: list[dict[str, str]] = []
    for table in table_names:
        rows = read_csv(base / mode / f"{table}.csv")
        manifest_path = base / mode / f"{table}.manifest.json"
        require(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(row.get("algorithm_id") == "A7_cgal_spatial_sort" for row in rows):
            if not manifest.get("cgal_adapter"):
                raise AssertionError(f"{manifest_path} has empty cgal_adapter")
        bad_refinements = [
            row
            for row in rows
            if row.get("refinement", "")
            != expected_refinement_for_row(row, expected_refinement)
        ]
        if bad_refinements:
            raise AssertionError(
                f"{base / mode / (table + '.csv')} has inconsistent refinement tags"
            )
        check_variant_coverage(
            rows,
            f"{base / mode / (table + '.csv')}",
            expected_rules_by_table[table],
        )
        all_rows.extend(rows)
    return all_rows


def check_algorithm_coverage(
    rows: list[dict[str, str]], label: str, expected: set[str]
) -> None:
    present = {row.get("algorithm_id", "") for row in rows}
    missing = sorted(expected - present)
    if missing:
        raise AssertionError(f"{label} is missing algorithms: {', '.join(missing)}")


def check_variant_coverage(
    rows: list[dict[str, str]],
    label: str,
    expected_supported: dict[str, tuple[str, ...]],
) -> None:
    contaminations = sorted({row.get("contamination_id", "") for row in rows})
    for algorithm_id, expected_rules in expected_supported.items():
        expected_set = set(expected_rules)
        for contamination_id in contaminations:
            present = {
                row.get("bit_rule", "")
                for row in rows
                if row.get("algorithm_id") == algorithm_id
                and row.get("contamination_id") == contamination_id
            }
            missing = sorted(expected_set - present)
            extra = sorted(present - expected_set)
            if missing:
                raise AssertionError(
                    f"{label} is missing {algorithm_id} variants for "
                    f"{contamination_id}: {', '.join(missing)}"
                )
            if extra:
                raise AssertionError(
                    f"{label} has unsupported {algorithm_id} variants for "
                    f"{contamination_id}: {', '.join(extra)}"
                )


def check_snapshot_tree(base: Path, tree: str, modes: tuple[str, ...]) -> int:
    tree_dir = base / tree
    require(tree_dir)
    for mode in modes:
        require(tree_dir / mode)
        require_absent(tree_dir / mode / "orders")
        require_absent(tree_dir / mode / "data")
        require_absent(tree_dir / mode / "manifests")
    return sum(1 for path in tree_dir.rglob("*") if path.is_file())


def verify(args: argparse.Namespace) -> dict[str, int]:
    """Verify the complete demo artifact bundle and return row/file counts."""
    for mode in MODES:
        require(args.synthetic_dir / mode)
        require(args.real_dir / mode)

    algorithms = load_algorithm_configs(
        args.repo_root / "experiments/configs/algorithms"
    )
    synthetic_expected_rules = {
        table: expected_supported_bit_rules(
            load_yaml_mapping(args.runlist_dir / f"{table}.yaml"), algorithms
        )
        for table in SYNTHETIC_TABLES
    }
    real_expected_rules = {
        table: expected_supported_bit_rules(
            load_yaml_mapping(args.runlist_dir / f"{table}.yaml"), algorithms
        )
        for table in REAL_TABLES
    }

    synthetic_result_rows = [
        row
        for mode in MODES
        for row in check_mode_rows(
            args.synthetic_dir,
            mode,
            SYNTHETIC_TABLES,
            mode,
            synthetic_expected_rules,
        )
    ]
    real_result_rows = [
        row
        for mode in MODES
        for row in check_mode_rows(
            args.real_dir,
            mode,
            REAL_TABLES,
            mode,
            real_expected_rules,
        )
    ]
    check_algorithm_coverage(
        synthetic_result_rows,
        "demo synthetic results",
        expected_algorithms(synthetic_expected_rules),
    )
    check_algorithm_coverage(
        real_result_rows,
        "demo real results",
        expected_algorithms(real_expected_rules),
    )

    runtime_rows = read_csv(args.synthetic_dir / "off" / "table_5_runtime.csv")
    if finite_values(runtime_rows, "cache_miss_rate") == 0:
        raise AssertionError("demo synthetic runtime rows have no finite cache_miss_rate")

    require(args.stats_dir / "synthetic_refinement_effects.csv")
    synthetic_effects = read_csv(args.stats_dir / "synthetic_refinement_effects.csv")
    require(args.stats_dir / "real_refinement_effects.csv")
    real_effects = read_csv(args.stats_dir / "real_refinement_effects.csv")
    if finite_values(synthetic_effects, "miad_all_minus_off") == 0:
        raise AssertionError("synthetic refinement effects were not calculated")
    if finite_values(real_effects, "miad_all_minus_off") == 0:
        raise AssertionError("real refinement effects were not calculated")

    check_required_table_csvs(args.tables_dir)
    determinism_rows = read_csv(args.tables_dir / "table_meta_determinism_by_preset.csv")
    if any(row.get("preset") == "no logs" for row in determinism_rows):
        raise AssertionError("demo determinism table fell back to no logs")
    require(args.outputs_dir / "output_snapshot_manifest.json")
    snapshot = json.loads(
        (args.outputs_dir / "output_snapshot_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot_files = check_snapshot_tree(args.outputs_dir, "synthetic_dataset", MODES)
    snapshot_files += check_snapshot_tree(args.outputs_dir, "real_dataset", MODES)
    require(args.outputs_dir / "a7_cgal_appendix" / "a7_cgal_spatial_sort.csv")
    a7_manifest = json.loads(
        (args.outputs_dir / "a7_cgal_appendix" / "a7_cgal_spatial_sort.manifest.json")
        .read_text(encoding="utf-8")
    )
    if not a7_manifest.get("adapter"):
        raise AssertionError("demo A7 appendix manifest has empty adapter")
    paper_manifest_path = args.stats_dir / "paper_artifacts_manifest.json"
    require(paper_manifest_path)
    paper_manifest = json.loads(paper_manifest_path.read_text(encoding="utf-8"))
    if int(paper_manifest["inputs"].get("test_logs", 0)) < 1:
        raise AssertionError("paper artifact manifest did not see demo test logs")
    unavailable_figures = [
        name
        for name, entry in paper_manifest.get("figures", {}).items()
        if "not_available" in str(entry.get("status", ""))
    ]
    if unavailable_figures:
        raise AssertionError(
            "demo paper figures are placeholders: " + ", ".join(unavailable_figures)
        )
    check_no_nullish_stats(args.stats_dir)
    require_absent(args.outputs_dir / "synthetic_refinement")
    require_absent(args.outputs_dir / "real_refinement")
    if int(snapshot["summary"]["file_count"]) != snapshot_files + 2:
        raise AssertionError("snapshot manifest file_count disagrees with copied files")

    assert_no_full_paths(
        [
            args.synthetic_dir,
            args.real_dir,
            args.outputs_dir,
            args.tables_dir,
            args.stats_dir,
            args.manifest,
            args.real_catalog,
            args.runlist_dir,
            args.logs_dir,
        ],
        args.repo_root,
    )

    return {
        "synthetic_rows": len(synthetic_result_rows),
        "real_rows": len(real_result_rows),
        "synthetic_effect_rows": len(synthetic_effects),
        "real_effect_rows": len(real_effects),
        "snapshot_files": snapshot_files + 2,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-dir", type=Path, required=True)
    parser.add_argument("--real-dir", type=Path, required=True)
    parser.add_argument("--outputs-dir", type=Path, required=True)
    parser.add_argument("--tables-dir", type=Path, required=True)
    parser.add_argument("--stats-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--real-catalog", type=Path, required=True)
    parser.add_argument("--runlist-dir", type=Path, required=True)
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    result = verify(parse_args())
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
