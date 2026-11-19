import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import print_prep as prep


def write_triangle(path):
    data = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 30, 0, 0, 0, 60, 0, 0)
    path.write_bytes(bytes(80) + struct.pack("<I", 1) + data)


class PrintSizingTests(unittest.TestCase):
    def test_scale_preserves_header_faces_normals_and_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source, target = folder / "source.stl", folder / "scaled.stl"
            write_triangle(source)
            before = source.read_bytes()
            prep._scale_prepared_stl(source, target, 1.2)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(target.read_bytes()[:84], before[:84])
            coords = struct.unpack("<12fH", target.read_bytes()[84:])
            self.assertEqual(coords, (0, 0, 1, 0, 0, 0, 36, 0, 0, 0, 72, 0, 0))

    def test_returns_largest_verified_candidate_and_reuses_complete_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "input.stl"
            out = folder / "out"
            write_triangle(source)

            def normalize(args, directory, stage, timeout):
                args[1].write_bytes(source.read_bytes())
                (directory / "dimensions.json").write_text("[30, 60, 10]")

            def slice_stl(stl, directory, machine):
                (directory / "print.gcode.3mf").write_bytes(stl.read_bytes())
                (directory / "preview.png").write_bytes(b"image")
                return "P2S", "HQ", "PLA"

            def inspect(directory, machine, process, material):
                height = struct.unpack("<12fH", (directory / "model.stl").read_bytes()[84:])[10]
                return {"estimated_seconds": 9000 + int((height - 60) * 210), "filament_grams": 20}

            with (patch.object(prep, "BLENDER", source), patch.object(prep, "SLICER", source),
                  patch.object(prep, "_run_blender", side_effect=normalize) as blender,
                  patch.object(prep, "_slice", side_effect=slice_stl),
                  patch.object(prep, "_inspect_slice", side_effect=inspect),
                  patch.object(prep, "render_model_preview", return_value=None)):
                report = prep.prepare_print(source, out, model="P2S")
                self.assertEqual(report["dimensions_mm"], [34, 68, 11.33])
                self.assertLessEqual(report["estimated_seconds"], 10800)
                self.assertTrue(any(t["estimated_seconds"] > 10800 for t in report["sizing"]["trials"]))
                self.assertEqual((out / "model.stl").read_bytes(), (out / "print.gcode.3mf").read_bytes())
                self.assertEqual(prep.prepare_print(source, out, model="P2S"), report)
                self.assertEqual(blender.call_count, 1)
                original = (out / "print.gcode.3mf").read_bytes()
                with self.assertRaisesRegex(prep.PreparationError, "已有可打印切片"):
                    prep.prepare_print(source, out, model="P2S", max_minutes=120)
                self.assertEqual((out / "print.gcode.3mf").read_bytes(), original)

    def test_legacy_output_and_unusable_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "input.stl"
            write_triangle(source)
            (folder / "print.gcode.3mf").write_bytes(b"existing")
            with patch.object(prep, "BLENDER", source), patch.object(prep, "SLICER", source):
                with self.assertRaisesRegex(prep.PreparationError, "已有可打印切片"):
                    prep.prepare_print(source, folder, model="P2S")
            self.assertEqual((folder / "print.gcode.3mf").read_bytes(), b"existing")
        self.assertIn("多 0.6 厘米", prep.size_comparison([39.87, 39.72, 60]))
        self.assertIn("约等于", prep.size_comparison([40, 40, 54]))
        self.assertIn("少 0.4 厘米", prep.size_comparison([40, 40, 50]))
        for bad in (None, [1, 2], [40, 40, float("inf")], [40, True, 50]):
            self.assertEqual(prep.size_comparison(bad), "")
