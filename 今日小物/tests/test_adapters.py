"""Offline regressions for recovery of paid Aholo jobs."""

import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import lux3d
import print_prep


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}


def glb(chunks):
    return struct.pack("<4sII", b"glTF", 2, len(chunks) + 12) + chunks


class AholoRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        environment = patch.dict(lux3d.os.environ, {"LUX3D_API_KEY": "offline"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        factory = patch.object(lux3d, "build_opener")
        self.opener = factory.start().return_value
        self.addCleanup(factory.stop)

    def test_existing_job_recovers_from_interrupted_query_and_broken_cached_chunk(self):
        # Both headers declare the correct file size, but the cached chunk is truncated.
        (self.folder / "model.glb").write_bytes(glb(struct.pack("<I4s", 64, b"JSON") + b"{}  "))
        body = b'{"asset":{"version":"2.0"}} '
        model_bytes = glb(struct.pack("<I4s", len(body), b"JSON") + body)
        url = "https://assets.aholo3d.cn/model.glb"
        detail = {"c": "0", "d": {"taskId": 123, "status": 3, "outputs": [{}, {"content": url}]}}
        self.opener.open.side_effect = [
            URLError("disconnected"),
            HTTPError("query", 503, "busy", {}, io.BytesIO()),
            Response(json.dumps(detail).encode()),
            Response(model_bytes),
        ]
        with patch.object(lux3d.time, "sleep") as sleep:
            path = lux3d.generate_model("", self.folder, job={"lux3d_task_id": 123}, checkpoint=self.fail)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(path.read_bytes(), model_bytes)
        requests = [call.args[0] for call in self.opener.open.call_args_list]
        self.assertEqual([request.get_method() for request in requests], ["GET"] * 4)
        self.assertEqual(len({request.full_url for request in requests[:3]}), 1)
        self.assertNotIn("Authorization", requests[-1].headers)

    def test_uncertain_paid_creation_is_never_reposted(self):
        self.opener.open.side_effect = URLError("disconnected")
        job = {}
        checkpoints = []
        for _ in range(2):
            with self.assertRaisesRegex(lux3d.Lux3DError, "可能已接单"):
                lux3d.generate_model("小水獭", self.folder, job=job,
                                     checkpoint=lambda: checkpoints.append(dict(job)),
                                     concept_prompt="单色参考图")
        self.assertTrue(checkpoints[0]["lux3d_concept_create_pending"])
        self.assertEqual(self.opener.open.call_count, 1)
        self.assertEqual(self.opener.open.call_args.args[0].get_method(), "POST")

    def test_permanent_query_failure_returns_without_waiting(self):
        self.opener.open.side_effect = HTTPError("query", 401, "unauthorized", {}, io.BytesIO())
        with patch.object(lux3d.time, "sleep") as sleep:
            with self.assertRaisesRegex(lux3d.Lux3DError, "HTTP 401"):
                lux3d.generate_model("", self.folder, job={"lux3d_task_id": 123}, checkpoint=self.fail)
        sleep.assert_not_called()
        self.assertEqual(self.opener.open.call_count, 1)


class PrintPreflightTests(unittest.TestCase):
    def test_large_binary_stl_is_stopped_before_launching_blender(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "many-faces.stl"
            count = print_prep.MAX_TRIANGLES + 1
            with source.open("wb") as file:
                file.seek(80)
                file.write(struct.pack("<I", count))
                file.truncate(84 + 50 * count)
            with patch.object(print_prep, "_run_blender") as blender:
                with self.assertRaisesRegex(print_prep.PreparationError, "50 万"):
                    print_prep.prepare_print(source, folder, model="P2S")
            blender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
