#!/usr/bin/env python3
"""Validate full paired permutations and map MIAD/stability on fixed geometry strata."""

from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import shutil
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/runners"))
from run_matrix import read_order_csv, kendall_tau_against_clean, is_permutation_of_size

ALGORITHMS = ("A3_isotropic_hilbert", "A5_pca_compact_hilbert", "A6_rch")
METRICS = ("miad_all", "miad_inlier", "kendall_tau_clean")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write(path, rows):
    if not rows:
        raise ValueError("no regime observations to write")
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def miad(points, order):
    if len(order) < 2:
        return 0.0
    selected = points[np.asarray(order, dtype=np.int64)]
    return float(np.linalg.norm(np.diff(selected, axis=0), axis=1).mean())


def descriptors(points):
    eigen = np.linalg.eigvalsh(np.cov(points, rowvar=False))[::-1]
    if eigen[0] <= 0:
        raise ValueError("zero covariance scale")
    return dict(
        sample_axis_aspect=math.sqrt(eigen[0] / eigen[2]) if eigen[2] > 0 else None,
        sample_rank_deficient=bool(eigen[2] <= 0),
        gap12=float((eigen[0] - eigen[1]) / eigen[0]),
        gap23=float((eigen[1] - eigen[2]) / eigen[0]),
        linearity=float((eigen[0] - eigen[1]) / eigen[0]),
        planarity=float((eigen[1] - eigen[2]) / eigen[0]),
        scattering=float(eigen[2] / eigen[0]),
    )


def validate(root):
    manifest = json.loads((root / "run_manifest.json").read_text())
    if manifest["schema"] != "rch.regime_benchmarks.v1":
        raise ValueError("invalid regime schema")
    for relative, checksum in manifest["files_sha256"].items():
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        if digest(path) != checksum:
            raise ValueError("regime inventory mismatch: " + relative)
    measured = []
    primary_clouds = set()
    for label in ("primary", "size_sensitivity"):
        spec = yaml.safe_load((root / (label + ".yaml")).read_text())
        if not all(
            spec[k] for k in ("geometry_ids", "point_counts", "seeds", "bit_rules")
        ) or any(n < 2 for n in spec["point_counts"]):
            raise ValueError("empty or invalid regime design")
        if not spec["independent_sampling"] or spec["contamination_ids"][0] != "D0":
            raise ValueError("independent clean baseline required")
        cloud_ids = {(g, seed) for g in spec["geometry_ids"] for seed in spec["seeds"]}
        if label == "primary":
            primary_clouds = cloud_ids
        elif primary_clouds & cloud_ids:
            raise ValueError("size sensitivity must use different cloud seeds")
        geometries = {g["id"]: g for g in spec["additional_geometries"]}
        cells = read(root / label / (spec["name"] + ".csv"))
        index = {}
        for row in cells:
            key = (
                row["geometry_id"],
                int(row["clean_point_count"]),
                int(row["seed"]),
                row["bit_rule"],
                row["algorithm_id"],
                row["contamination_id"],
            )
            if key in index:
                raise ValueError("duplicate regime cell")
            index[key] = row
        expected = {
            (g, n, s, r["id"], alg, d)
            for g in spec["geometry_ids"]
            for n in spec["point_counts"]
            for s in spec["seeds"]
            for r in spec["bit_rules"]
            for alg in ALGORITHMS
            for d in spec["contamination_ids"]
        }
        if set(index) != expected:
            raise ValueError("incomplete regime matrix")
        clean_orders, clean_points, input_hashes = {}, {}, {}
        for key, row in sorted(index.items()):
            g, n, s, rule, alg, d = key
            stem = f"{alg}__{rule}__{d}__{g}__n{n}__s{s}"

            def artifact(folder, suffix):
                relative = f"{label}/{folder}/{stem}{suffix}"
                if relative not in manifest["files_sha256"]:
                    raise ValueError("missing source inventory member")
                return root / relative

            path = artifact("data", ".csv")
            points = np.loadtxt(path, delimiter=",", ndmin=2)
            meta = json.loads(artifact("manifests", ".manifest.json").read_text())
            order = read_order_csv(artifact("orders", ".order.csv"))
            count = int(row["point_count"])
            if (
                points.shape != (count, 3)
                or not np.isfinite(points).all()
                or not is_permutation_of_size(order, count)
            ):
                raise ValueError("invalid points/permutation")
            if (
                int(meta["point_count"]) != count
                or meta["bits_axis"] != list(map(int, row["bits_axis"].split()))
                or meta["method"] != row["method"]
            ):
                raise ValueError("native CSV and manifest disagree")
            if (
                row["refinement"] != "off"
                or row["output_hash"] != meta["hash"]
                or meta.get("controlled_frame_quantizer")
                or meta["status"] != "ok"
            ):
                raise ValueError(
                    "regime must use successful unmodified native policies"
                )
            pair = g, n, s, d
            checksum = digest(path)
            if input_hashes.setdefault(pair, checksum) != checksum:
                raise ValueError("unpaired regime input")
            baseline_key = g, n, s, rule, alg
            cloud = g, n, s
            if d == "D0":
                clean_orders[baseline_key] = order
                if cloud in clean_points and not np.array_equal(
                    clean_points[cloud], points
                ):
                    raise ValueError("different clean points across methods/rules")
                clean_points[cloud] = points
            if baseline_key not in clean_orders or not np.array_equal(
                points[:n], clean_points[cloud]
            ):
                raise ValueError("inlier IDs not preserved")
            tau = kendall_tau_against_clean(clean_orders[baseline_key], order, n)
            full = miad(points, order)
            if not math.isclose(
                tau, float(row["kendall_tau_clean"]), abs_tol=1e-12
            ) or not math.isclose(
                full, float(row["miad"]), rel_tol=1e-10, abs_tol=1e-12
            ):
                raise ValueError("recomputed MIAD/Kendall mismatch")
            diag = meta["quantization_diagnostics"]
            record = dict(
                study=label,
                geometry_id=g,
                family=geometries[g]["family"],
                shape=geometries[g]["shape"],
                clean_point_count=n,
                seed=s,
                bit_rule=rule,
                algorithm_id=alg,
                contamination_id=d,
                miad_all=full,
                miad_inlier=miad(points, [i for i in order if i < n]),
                kendall_tau_clean=tau,
                clipped_fraction=diag["domain_clipped_point_count"] / count,
                duplicate_key_fraction=diag["duplicate_hilbert_key_point_count"]
                / count,
                fallback=meta["robust_fallback_used"],
                bits_axis=json.dumps(meta["bits_axis"]),
            )
            fitted = meta.get("fitted_frame_diagnostics") or {}
            record.update(
                frame_mode=fitted.get("mode", "not_applicable"),
                fitted_gap12=fitted.get("gap12"),
                fitted_gap23=fitted.get("gap23"),
            )
            record.update(
                {"clean_" + k: v for k, v in descriptors(clean_points[cloud]).items()}
            )
            record.update({"observed_" + k: v for k, v in descriptors(points).items()})
            measured.append(record)
    return manifest, measured


def analyze(root, output, draws, artifact_root=None):
    _, measured = validate(root)
    output.mkdir(parents=True, exist_ok=True)
    write(output / "cloud_metrics.csv", measured)
    index = {
        (
            r["study"],
            r["geometry_id"],
            r["clean_point_count"],
            r["seed"],
            r["bit_rule"],
            r["contamination_id"],
            r["algorithm_id"],
        ): r
        for r in measured
    }
    paired, groups = [], defaultdict(list)
    for key, row in index.items():
        if key[-1] != "A6_rch":
            continue
        for reference in ALGORITHMS[:2]:
            baseline = index[(*key[:-1], reference)]
            for metric in METRICS:
                effect = row[metric] - baseline[metric]
                rec = {
                    k: row[k]
                    for k in (
                        "study",
                        "geometry_id",
                        "family",
                        "shape",
                        "clean_point_count",
                        "seed",
                        "bit_rule",
                        "contamination_id",
                    )
                }
                rec.update(reference=reference, metric=metric, effect=effect)
                paired.append(rec)
                group = tuple(rec[k] for k in rec if k not in ("seed", "effect"))
                groups[group].append(rec)
    write(output / "paired_effects.csv", paired)
    rng = np.random.default_rng(20261106)
    summary = []
    resampling = {}
    for records in groups.values():
        records = sorted(records, key=lambda r: r["seed"])
        row = {k: v for k, v in records[0].items() if k not in ("seed", "effect")}
        values = np.asarray([r["effect"] for r in records])
        block_key = row["study"], row["geometry_id"], row["clean_point_count"]
        if block_key not in resampling:
            resampling[block_key] = rng.integers(
                0, len(values), size=(draws, len(values))
            )
        boot = np.median(values[resampling[block_key]], axis=1)
        row.update(
            n_clouds=len(values),
            median_effect=float(np.median(values)),
            ci95_low=float(np.quantile(boot, 0.025)),
            ci95_high=float(np.quantile(boot, 0.975)),
            bootstrap_resamples=draws,
            interval_scope="pointwise descriptive; no multiplicity correction or validated selection threshold",
        )
        summary.append(row)
    write(output / "regime_summary.csv", summary)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    selected = [
        r
        for r in summary
        if r["study"] == "primary" and r["reference"] == "A3_isotropic_hilbert"
    ]
    rules = sorted({r["bit_rule"] for r in selected})
    geometries = sorted({r["geometry_id"] for r in selected})
    conditions = sorted({r["contamination_id"] for r in selected})
    fig, axes = plt.subplots(
        len(rules), 2, figsize=(13, 5 * len(rules)), squeeze=False, layout="constrained"
    )
    for row_index, rule in enumerate(rules):
        for col, metric in enumerate(("miad_inlier", "kendall_tau_clean")):
            ax = axes[row_index, col]
            matrix = np.array(
                [
                    [
                        next(
                            r["median_effect"]
                            for r in selected
                            if r["geometry_id"] == g
                            and r["contamination_id"] == d
                            and r["bit_rule"] == rule
                            and r["metric"] == metric
                        )
                        for d in conditions
                    ]
                    for g in geometries
                ]
            )
            limit = max(float(np.max(np.abs(matrix))), 1e-12)
            artist = ax.imshow(
                matrix, aspect="auto", cmap="coolwarm", vmin=-limit, vmax=limit
            )
            ax.set_xticks(range(len(conditions)), conditions)
            ax.set_yticks(
                range(len(geometries)),
                [g.removeprefix("R_") for g in geometries],
                fontsize=7,
            )
            ax.set_title(f"{rule[:2]}: Δ {metric}; RCH − fixed Hilbert")
            bar = fig.colorbar(artist, ax=ax)
            bar.set_label(
                "Negative favours RCH"
                if metric == "miad_inlier"
                else "Positive favours RCH"
            )
    counts = sorted({r["n_clouds"] for r in selected})
    fig.suptitle(f"Observed paired medians; clouds per stratum: {counts}; descriptive")
    fig.savefig(output / "fig_regime_map.pdf", metadata={"CreationDate": None})
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for d in conditions:
        selected_pairs = [
            r
            for r in paired
            if r["study"] == "primary"
            and r["reference"] == "A3_isotropic_hilbert"
            and r["metric"] == "miad_inlier"
            and r["bit_rule"].startswith("C3")
            and r["contamination_id"] == d
        ]
        cloud = [
            index[
                (
                    r["study"],
                    r["geometry_id"],
                    r["clean_point_count"],
                    r["seed"],
                    r["bit_rule"],
                    d,
                    "A6_rch",
                )
            ]
            for r in selected_pairs
        ]
        for ax, key in zip(axes, ("clean_sample_axis_aspect", "clean_gap12")):
            ax.scatter(
                [r[key] if r[key] is not None else np.nan for r in cloud],
                [r["effect"] for r in selected_pairs],
                s=8,
                alpha=0.4,
                label=d,
            )
            ax.axhline(0, color="black", linewidth=0.5)
            ax.set_xlabel(key)
            ax.set_ylabel("Inlier MIAD(RCH/C3) − MIAD(A3)")
    axes[0].legend()
    fig.savefig(
        output / "fig_regime_shape_diagnostics.pdf", metadata={"CreationDate": None}
    )
    plt.close(fig)
    text = [
        "# Regime map scope",
        "",
        "Exploratory fixed-stratum effects; no learned selector or unseen-site validation.",
        "Each CI resamples independent cloud seeds within one geometry/size cell. Rules, metrics and contamination are repeated observations, not new clouds.",
        "Intervals are pointwise descriptive and unadjusted. Heatmap colours show signed median differences, not significance or recommendations.",
        "MIAD lower and Kendall higher are preferable. Full-point and inlier-only MIAD are separate; raw MIAD scales across strata need not be comparable.",
        "Affine design scales and empirical covariance descriptors are different. A parameter-sphere surface is not area-uniform on an ellipsoid.",
        f"Observed sizes by study: { {label: sorted({r['clean_point_count'] for r in measured if r['study'] == label}) for label in ('primary', 'size_sensitivity')} }. The sensitivity is not a full sample-size factorial; exact runlists are frozen.",
    ]
    (output / "scope.md").write_text("\n\n".join(text) + "\n")
    tex = [
        r"\begin{tabular}{lrrr}",
        r"Geometry & D0 $\Delta$MIAD & D4 $\Delta$MIAD & D4 $\Delta\tau$ \\",
        r"\hline",
    ]
    for g in geometries:

        def get(d, metric):
            candidates = [
                r
                for r in selected
                if r["geometry_id"] == g
                and r["bit_rule"].startswith("C3")
                and r["contamination_id"] == d
                and r["metric"] == metric
            ]
            return f"{candidates[0]['median_effect']:.5f}" if candidates else "--"

        tex.append(
            g.replace("_", r"\_")
            + " & "
            + get("D0", "miad_inlier")
            + " & "
            + get("D4", "miad_inlier")
            + " & "
            + get("D4", "kendall_tau_clean")
            + r" \\"
        )
    tex.append(r"\end{tabular}")
    (output / "table_regime_map.tex").write_text("\n".join(tex) + "\n")
    names = [
        "cloud_metrics.csv",
        "paired_effects.csv",
        "regime_summary.csv",
        "fig_regime_map.pdf",
        "fig_regime_shape_diagnostics.pdf",
        "table_regime_map.tex",
        "scope.md",
    ]
    published = {}
    if artifact_root:
        for folder, name in [
            ("figures", "fig_regime_map.pdf"),
            ("figures", "fig_regime_shape_diagnostics.pdf"),
            ("tables", "table_regime_map.tex"),
        ]:
            dst = artifact_root / folder / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output / name, dst)
            published[str(dst.relative_to(artifact_root))] = digest(dst)
    (output / "analysis_manifest.json").write_text(
        json.dumps(
            dict(
                analysis_code_sha256=digest(Path(__file__)),
                source_manifest_sha256=digest(root / "run_manifest.json"),
                artifacts={name: digest(output / name) for name in names},
                published_artifacts=published,
            ),
            indent=2,
        )
        + "\n"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--artifact-root", type=Path)
    p.add_argument("--bootstrap-resamples", type=int, default=5000)
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args()
    if a.bootstrap_resamples < 100:
        p.error("at least 100 draws required")
    if a.validate_only:
        validate(a.input_root)
        if not (a.output_dir / "analysis_manifest.json").is_file():
            raise ValueError(
                "analysis manifest missing; generate regime artifacts first"
            )
        m = json.loads((a.output_dir / "analysis_manifest.json").read_text())
        if m["analysis_code_sha256"] != digest(Path(__file__)):
            raise ValueError("regime analyzer changed; regenerate artifacts")
        if m["source_manifest_sha256"] != digest(a.input_root / "run_manifest.json"):
            raise ValueError("stale regime analysis")
        for name, checksum in m["artifacts"].items():
            if digest(a.output_dir / name) != checksum:
                raise ValueError("stale regime artifact")
        if a.artifact_root:
            if not m["published_artifacts"]:
                raise ValueError("regime published artifacts missing")
            for name, checksum in m["published_artifacts"].items():
                if digest(a.artifact_root / name) != checksum:
                    raise ValueError("stale published regime artifact")
        print(
            "Regime inventory, paired inputs, permutations, full/inlier MIAD and Kendall verified"
        )
    else:
        analyze(a.input_root, a.output_dir, a.bootstrap_resamples, a.artifact_root)


if __name__ == "__main__":
    main()
