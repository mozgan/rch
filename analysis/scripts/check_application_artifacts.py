#!/usr/bin/env python3
"""Check that generated application artifacts belong to the current run."""

import argparse
import json
from pathlib import Path

from analyze_application_query_metrics import digest

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--input-root", type=Path, required=True)
p.add_argument("--output-root", type=Path, default=Path("analysis/generated"))
a = p.parse_args()
state = json.loads(
    (a.output_root / "stats/application_artifacts_manifest.json").read_text()
)
source = a.input_root / "run_manifest.json"
if source.exists():
    if state["status"] != "validated_full_matrix" or state[
        "source_manifest_sha256"
    ] != digest(source):
        raise ValueError("application artifacts are stale or unavailable")
    source_manifest = json.loads(source.read_text())
    from experiments.application_layouts import expected_layouts

    layouts = expected_layouts(source_manifest)
    repository = Path(__file__).resolve().parents[2]
    for name, checksum in source_manifest.get("source_sha256", {}).items():
        path = (repository / name).resolve()
        path.relative_to(repository)
        if digest(path) != checksum:
            raise ValueError(f"application source changed: {name}; rerun make app-query")

    report = json.loads(
        (a.output_root / "outputs/application_query/summary.json").read_text()
    )
    if report.get("layouts") != list(layouts) or report.get(
        "input_manifest_sha256"
    ) != digest(source):
        raise ValueError("native application artifact layout/source mismatch")
    expected = {
        (d["dataset_id"], layout)
        for d in source_manifest["datasets"]
        for layout in layouts
    }
    observed = [(r["dataset_id"], r["layout_id"]) for r in report["summaries"]]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("native application summary matrix incomplete")
    if state["generator_sha256"] != digest(
        Path(__file__).with_name("make_application_artifacts.py")
    ):
        raise ValueError("native artifact renderer changed; regenerate artifacts")
    for path, checksum in state["artifacts"].items():
        if digest(a.output_root / path) != checksum:
            raise ValueError(f"artifact checksum mismatch: {path}")
else:
    if state["status"] != "unavailable_full_matrix":
        raise ValueError("source is missing for measured artifacts")
print("application artifact status and checksums verified")
