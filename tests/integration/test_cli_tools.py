"""Smoke tests for developer CLI tools."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def _load_simple_algorithm_yaml(path: Path) -> dict[str, object]:
    """Parse the small scalar/list subset used by algorithm config YAML files."""

    data: dict[str, object] = {}
    active_list: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            if active_list is None:
                raise AssertionError(f"{path} contains a list item outside a list")
            cast_list = data[active_list]
            if not isinstance(cast_list, list):
                raise AssertionError(f"{path} has inconsistent YAML list state")
            cast_list.append(line[2:].strip())
            continue
        if ":" not in line:
            continue

        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if not value:
            data[key] = []
            active_list = key
        else:
            active_list = None
            if value == "true":
                data[key] = True
            elif value == "false":
                data[key] = False
            else:
                try:
                    data[key] = float(value) if "." in value else int(value)
                except ValueError:
                    data[key] = value

    return data


class CliToolsSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rch_order = os.environ.get("RCH_ORDER_BIN")
        self.compare = os.environ.get("RCH_COMPARE_ORDERS_BIN")
        self.block_probe = os.environ.get("RCH_BLOCK_READ_PROBE_BIN")
        if not all((self.rch_order, self.compare, self.block_probe)):
            self.skipTest("CLI tool paths are not provided by CMake")

    def test_order_compare_and_block_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = root / "points.xyz"
            order = root / "order.csv"
            manifest = root / "manifest.json"
            points.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n", encoding="utf-8")

            subprocess.run(
                [
                    self.rch_order,
                    "--input",
                    str(points),
                    "--method",
                    "rch",
                    "--output",
                    str(order),
                    "--manifest",
                    str(manifest),
                    "--bit-allocator",
                    "frame_core_occupancy",
                    "--timing-repeats",
                    "3",
                ],
                check=True,
            )

            rows = order.read_text(encoding="utf-8").splitlines()
            self.assertEqual(rows[0], "rank,raw_index,key")
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "ok")
            self.assertEqual(metadata["method"], "rch")
            self.assertEqual(metadata["bit_allocator"], "frame_core_occupancy")
            self.assertEqual(metadata["bit_allocation_model"], "robust_core_occupancy")
            self.assertEqual(metadata["bit_budget_projection"], "minimax_worst_cell_edge")
            self.assertEqual(metadata["point_count"], 4)

            subprocess.run(
                [self.compare, str(order), str(order)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            checksum = subprocess.check_output(
                [self.block_probe, "--points", str(points), "--order", str(order), "--block-size", "2"],
                text=True,
            )
            self.assertAlmostEqual(float(checksum), 1.75)

    def test_sample_count_uniform_allocator_is_manifested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = root / "points.xyz"
            order = root / "order.csv"
            manifest = root / "manifest.json"
            points.write_text(
                "\n".join(f"{i % 5} {(i // 5) % 5} {i // 25}" for i in range(65)) + "\n",
                encoding="utf-8",
            )

            subprocess.run(
                [
                    self.rch_order,
                    "--input",
                    str(points),
                    "--method",
                    "isotropic_hilbert",
                    "--output",
                    str(order),
                    "--manifest",
                    str(manifest),
                    "--bit-allocator",
                    "sample_count_uniform",
                    "--uniform-bits",
                    "2",
                ],
                check=True,
            )

            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "ok")
            self.assertEqual(metadata["method"], "isotropic_hilbert")
            self.assertEqual(metadata["bit_allocator"], "sample_count_uniform")
            self.assertEqual(metadata["bit_allocation_model"], "sample_count_equal_depth")
            self.assertEqual(metadata["bit_budget_projection"], "equal_depth_axis_cap")
            self.assertEqual(metadata["point_count"], 65)
            self.assertEqual(metadata["bits_axis"], [3, 3, 3])

    def test_malformed_order_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = root / "points.xyz"
            bad = root / "bad_order.csv"
            points.write_text("0 0 0\n1 0 0\n", encoding="utf-8")
            bad.write_text("rank,raw_index,key\n0,1foo,99\n", encoding="utf-8")

            self.assertNotEqual(
                subprocess.run(
                    [self.compare, str(bad), str(bad)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).returncode,
                0,
            )
            self.assertNotEqual(
                subprocess.run(
                    [self.block_probe, "--points", str(points), "--order", str(bad)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).returncode,
                0,
            )

    def test_malformed_ply_headers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "missing_magic.ply": (
                    "format ascii 1.0\n"
                    "element vertex 1\n"
                    "property double x\n"
                    "property double y\n"
                    "property double z\n"
                    "end_header\n"
                    "0 0 0\n"
                ),
                "bad_vertex_count.ply": (
                    "ply\n"
                    "format ascii 1.0\n"
                    "element vertex 1x\n"
                    "property double x\n"
                    "property double y\n"
                    "property double z\n"
                    "end_header\n"
                    "0 0 0\n"
                ),
            }
            for name, payload in cases.items():
                points = root / name
                points.write_text(payload, encoding="utf-8")
                result = subprocess.run(
                    [
                        self.rch_order,
                        "--input",
                        str(points),
                        "--method",
                        "input",
                        "--output",
                        str(root / f"{name}.csv"),
                        "--manifest",
                        str(root / f"{name}.json"),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, name)


if __name__ == "__main__":
    unittest.main()
