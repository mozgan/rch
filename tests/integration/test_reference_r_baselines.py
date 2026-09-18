"""Smoke tests for R baseline oracle generators."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class ReferenceRBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rscript = shutil.which("Rscript")
        if self.rscript is None:
            self.skipTest("Rscript is not installed")

    def run_r(
        self, expression: str, cwd: Path = REPO_ROOT
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.rscript, "-e", expression],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def has_r_package(self, package: str) -> bool:
        result = subprocess.run(
            [
                self.rscript,
                "-e",
                f"quit(status = if (requireNamespace('{package}', quietly = TRUE)) 0 else 1)",
            ],
            cwd=REPO_ROOT,
        )
        return result.returncode == 0

    def test_mcd_h_formula_and_synthetic_cloud(self) -> None:
        script = r'''
source("baselines/reference_r/covmcd_reference.R")
stopifnot(identical(as.integer(h_alpha_n(0.5, 50, 3)), 27L))
stopifnot(identical(as.integer(h_alpha_n(0.5, 100, 3)), 52L))
stopifnot(identical(as.integer(h_alpha_n(0.5, 200, 3)), 102L))
stopifnot(identical(as.integer(h_alpha_n(0.75, 10, 3)), 8L))
stopifnot(inherits(try(h_alpha_n(0.49, 50, 3), silent = TRUE), "try-error"))
stopifnot(inherits(try(h_alpha_n(0.5, 2, 3), silent = TRUE), "try-error"))
stopifnot(inherits(try(make_covmcd_synthetic_cloud(50, p = 2), silent = TRUE), "try-error"))
x <- make_covmcd_synthetic_cloud(50)
stopifnot(all.equal(x[1, ], c(-0.32, -0.19, -0.14), tolerance = 1e-15))
stopifnot(all.equal(x[28, ], c(21, -17, 13), tolerance = 1e-15))
'''
        self.run_r(script)

    def test_mrcd_h_formula_matches_mcd_formula(self) -> None:
        script = r'''
source("baselines/reference_r/covmcd_reference.R")
source("baselines/reference_r/mrcd_reference.R")
cases <- list(
  c(0.5, 50, 3),
  c(0.5, 100, 3),
  c(0.5, 200, 3),
  c(0.75, 10, 3),
  c(1.0, 13, 4)
)
for (case in cases) {
  alpha <- case[[1]]
  n <- case[[2]]
  p <- case[[3]]
  stopifnot(identical(h_alpha_n_mrcd(alpha, n, p), h_alpha_n(alpha, n, p)))
}
stopifnot(inherits(try(h_alpha_n_mrcd(0.49, 50, 3), silent = TRUE), "try-error"))
stopifnot(inherits(try(h_alpha_n_mrcd(0.5, 2, 3), silent = TRUE), "try-error"))
'''
        self.run_r(script)

    def test_json_helpers_emit_strict_json_tokens(self) -> None:
        script = r'''
source("baselines/reference_r/generate_oracles.R")
cat(json_array(c(1, NA_real_, 2.5)), "\n")
cat(json_matrix(matrix(numeric(0), nrow = 0, ncol = 3)), "\n")
cat(json_string("a\\b\"c\n\t"), "\n")
stopifnot(inherits(try(json_array(c("not numeric")), silent = TRUE), "try-error"))
stopifnot(inherits(try(json_array(c(Inf)), silent = TRUE), "try-error"))
'''
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "det.jsonl"
            result = subprocess.run(
                [self.rscript, "-e", script, str(output_path)],
                cwd=REPO_ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        lines = result.stdout.strip().splitlines()
        self.assertEqual(json.loads(lines[-3]), [1.0, None, 2.5])
        self.assertEqual(json.loads(lines[-2]), [])
        self.assertEqual(json.loads(lines[-1]), 'a\\b"c\n\t')

    def test_generate_mrcd_and_ogk_oracles_are_valid_jsonl(self) -> None:
        missing = [
            package
            for package in ("robustbase", "rrcov")
            if not self.has_r_package(package)
        ]
        if missing:
            self.skipTest(f"required R package(s) are not installed: {', '.join(missing)}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            det_path = tmp_path / "det_mcd.jsonl"
            mrcd_path = tmp_path / "mrcd.jsonl"
            ogk_path = tmp_path / "ogk.jsonl"
            subprocess.run(
                [
                    self.rscript,
                    "baselines/reference_r/generate_oracles.R",
                    str(det_path),
                    str(mrcd_path),
                    str(ogk_path),
                ],
                cwd=REPO_ROOT,
                check=True,
                text=True,
            )

            for output_path in (mrcd_path, ogk_path):
                rows = [json.loads(line) for line in output_path.read_text().splitlines()]
                self.assertEqual([row["h"] for row in rows], [27, 52, 102])
                for row in rows:
                    self.assertEqual(len(row["points"]), row["n"])
                    self.assertEqual(len(row["center"]), 3)
                    self.assertEqual(len(row["scatter"]), 3)
                    self.assertTrue(all(len(scatter_row) == 3 for scatter_row in row["scatter"]))
                    for lhs in range(3):
                        for rhs in range(3):
                            self.assertAlmostEqual(
                                row["scatter"][lhs][rhs],
                                row["scatter"][rhs][lhs],
                                delta=1.0e-12,
                            )

            mrcd_rows = [json.loads(line) for line in mrcd_path.read_text().splitlines()]
            self.assertTrue(all("rho" in row for row in mrcd_rows))

    def test_generate_oracles_helpers_can_be_sourced_from_other_cwd(self) -> None:
        script_path = REPO_ROOT / "baselines/reference_r/generate_oracles.R"
        script = f'''
source("{script_path.as_posix()}")
stopifnot(is_sourced())
cat(json_string("portable\\npath"), "\\n")
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_r(script, cwd=Path(tmp))

        self.assertEqual(json.loads(result.stdout.strip()), "portable\npath")

    def test_generate_det_mcd_oracles_are_valid_jsonl(self) -> None:
        if not self.has_r_package("robustbase"):
            self.skipTest("robustbase is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "det_mcd.jsonl"
            subprocess.run(
                [
                    self.rscript,
                    "baselines/reference_r/generate_oracles.R",
                    str(output_path),
                ],
                cwd=REPO_ROOT,
                check=True,
                text=True,
            )
            rows = [json.loads(line) for line in output_path.read_text().splitlines()]

        self.assertEqual([row["h"] for row in rows], [27, 52, 102])
        for row in rows:
            self.assertEqual(len(row["center"]), 3)
            self.assertEqual(len(row["scatter"]), 3)
            self.assertTrue(all(len(scatter_row) == 3 for scatter_row in row["scatter"]))

    def test_generate_det_mcd_oracles_runs_from_other_cwd(self) -> None:
        if not self.has_r_package("robustbase"):
            self.skipTest("robustbase is not installed")

        script_path = REPO_ROOT / "baselines/reference_r/generate_oracles.R"
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "det_mcd.jsonl"
            subprocess.run(
                [self.rscript, str(script_path), str(output_path)],
                cwd=Path(tmp),
                check=True,
                text=True,
            )
            rows = [json.loads(line) for line in output_path.read_text().splitlines()]

        self.assertEqual(
            [row["case"] for row in rows],
            ["synthetic_n50", "synthetic_n100", "synthetic_n200"],
        )

    def test_hardin_rocke_helper_contract(self) -> None:
        script = r'''
source("baselines/reference_r/hardin_rocke_reference.R")
stopifnot(is_sourced())
if (requireNamespace("MAINT.Data", quietly = TRUE)) {
  cutoff <- hardin_rocke_reference(0.975, 50, 3, 27, TRUE)
  stopifnot(is.numeric(cutoff), length(cutoff) == 1L, is.finite(cutoff), cutoff > 0)
} else {
  err <- try(hardin_rocke_reference(0.975, 50, 3, 27, TRUE), silent = TRUE)
  stopifnot(inherits(err, "try-error"))
  stopifnot(grepl(
    "MAINT.Data package is required",
    conditionMessage(attr(err, "condition")),
    fixed = TRUE
  ))
}
'''
        self.run_r(script)


if __name__ == "__main__":
    unittest.main()
