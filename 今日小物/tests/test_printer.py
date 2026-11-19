"""Offline regression checks. Every printer transport is replaced by a replay."""

from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import itertools
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings
from zipfile import ZIP_DEFLATED, ZipFile

import printer


def ready_status():
    return {
        "command": "push_status", "gcode_state": "IDLE", "print_error": 0,
        "hms": [{"attr": 0x05000200, "code": 0x0003000A}], "aux": "1000",
        "device": {"nozzle": {"info": [{"id": 0, "diameter": "0.4", "stat": 0}]}},
        "vt_tray": {"tray_type": "PLA"},
        "ams": {
            "ams_exist_bits": "1", "tray_exist_bits": "f",
            "ams": [{"id": 0, "tray": [{"id": slot, "tray_type": "PLA"} for slot in range(4)]}],
        },
    }


def artifact_bytes(*, duplicate=False, material="PLA"):
    buffer = BytesIO()
    settings = json.dumps({
        "printer_model": "Bambu Lab P2S", "nozzle_diameter": ["0.4"],
        "filament_type": [material], "curr_bed_type": "Textured PEI Plate",
    })
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(printer.PLATE, b"G1 X10 Y10 E1\n" * 10000)
        archive.writestr("Metadata/project_settings.config", settings)
        archive.writestr("Metadata/slice_info.config", (
            '<config><plate><metadata key="outside" value="false"/>'
            '<metadata key="prediction" value="5000"/></plate></config>'
        ))
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("Metadata/project_settings.config", settings)
    return buffer.getvalue()


class ReplayClient:
    def __init__(self, snapshot=None, *, start="confirmed", after_snapshot=None):
        self.snapshot = snapshot
        self.start = start
        self.after_snapshot = after_snapshot
        self.messages = deque()
        self.commands = []

    def publish(self, topic, payload, **options):
        command = json.loads(payload)
        self.commands.append((command, options))
        if "pushing" in command and self.snapshot is not None:
            self.messages.append(deepcopy(self.snapshot))
            if self.after_snapshot:
                self.messages.append(deepcopy(self.after_snapshot))
        if "print" in command:
            task = command["print"]
            if self.start == "confirmed":
                self.messages.append({
                    "command": "push_status", "gcode_state": "PREPARE",
                    "task_id": task["task_id"], "print_error": 0,
                })
            elif self.start == "split":
                self.messages.extend((
                    {"command": "push_status", "gcode_state": "RUNNING", "task_id": "another-job"},
                    {"command": "push_status", "task_id": task["task_id"]},
                ))
            elif self.start == "identity-first":
                self.messages.extend((
                    {"command": "push_status", "task_id": task["task_id"]},
                    {"command": "push_status", "gcode_state": "PREPARE", "print_error": 0},
                ))
            elif self.start == "changed-identity":
                self.messages.extend((
                    {"command": "push_status", "subtask_name": task["subtask_name"]},
                    {"command": "push_status", "gcode_state": "RUNNING", "task_id": "another-job"},
                ))
            elif self.start == "disconnect":
                raise OSError("simulated private transport detail")
        return SimpleNamespace(rc=0)

    def loop(self, timeout=0):
        if self.messages:
            self.on_message(self, None, SimpleNamespace(
                topic="device/TEST/report", retain=False,
                payload=json.dumps({"print": self.messages.popleft()}).encode(),
            ))
        return 0


class PrinterRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.artifact = Path(self.temporary.name) / "print.gcode.3mf"
        self.bytes = artifact_bytes()
        self.artifact.write_bytes(self.bytes)

    def replay_send(self, *, source="external", start="confirmed", after_snapshot=None, upload_error=False,
                    initial=None, expected_bed=None):
        report = ready_status() if initial is None else initial
        clients = [ReplayClient(report), ReplayClient(
            report, start=start, after_snapshot=after_snapshot,
        )]
        connections = iter(printer._PrinterConnection(client, "TEST") for client in clients)

        @contextmanager
        def connect(*credentials):
            yield next(connections)

        uploads = []

        def upload(host, serial, code, remote, snapshot, size):
            if upload_error:
                raise printer.PrinterError("模拟上传失败")
            self.assertEqual(snapshot.read(), self.bytes)
            self.assertEqual(size, len(self.bytes))
            uploads.append(remote)

        clock = itertools.count(step=1)
        with (
            patch.object(printer, "_credentials", return_value=("192.168.0.1", "TEST", "TEST")),
            patch.object(printer, "_connect", side_effect=connect),
            patch.object(printer, "_upload", side_effect=upload),
            patch.object(printer, "monotonic", side_effect=lambda: next(clock)),
        ):
            error = None
            try:
                ticket = printer.send_print(self.artifact, model="P2S", source=source, expected_bed=expected_bed)
                self.assertEqual(set(ticket), {"task_id", "name"})
                self.assertTrue(printer._valid_ticket(ticket))
                self.assertEqual(ticket["task_id"], clients[1].commands[-1][0]["print"]["task_id"])
                self.assertEqual(ticket["name"] + ".gcode", clients[1].commands[-1][0]["print"]["subtask_name"])
            except printer.PrinterError as caught:
                error = caught
        starts = [command["print"] for command, _ in clients[1].commands if "print" in command]
        return error, uploads, starts

    def read_clearance(self, report):
        client = ReplayClient(report)
        @contextmanager
        def connect(*credentials):
            yield printer._PrinterConnection(client, "TEST")
        clock = itertools.count()
        with (patch.object(printer, "_credentials", return_value=("", "", "")),
              patch.object(printer, "_connect", side_effect=connect),
              patch.object(printer, "monotonic", side_effect=lambda: next(clock))):
            try:
                return printer.read_idle_bed()
            finally:
                self.assertEqual([command for command, _ in client.commands],
                                 [{"pushing": {"sequence_id": "0", "command": "pushall"}}])

    def test_clearance_rejects_an_intervening_finished_job_before_or_during_upload(self):
        first = ready_status() | {"gcode_state":"FINISH", "subtask_name":"first.gcode", "subtask_id":"123"}
        next_job = first | {"subtask_id":"124"}
        signature = self.read_clearance(first)
        self.assertRegex(signature, r"^[0-9a-f]{64}$")
        for initial, update, sent in ((next_job,None,0), (first,next_job,1)):
            error, uploads, starts = self.replay_send(initial=initial, after_snapshot=update, expected_bed=signature)
            self.assertRegex(str(error), "重新确认清盘")
            self.assertEqual(len(uploads), sent)
            self.assertFalse(starts)
        error, _, starts = self.replay_send(initial=first, expected_bed=signature)
        self.assertIsNone(error)
        self.assertEqual(len(starts),1)

    def test_new_idle_printer_uses_empty_identity_but_busy_or_unidentified_finish_cannot_confirm(self):
        empty = self.read_clearance(ready_status())
        error, _, starts = self.replay_send(expected_bed=empty)
        self.assertIsNone(error)
        self.assertEqual(len(starts),1)
        with self.assertRaises(printer.PrinterError):
            self.read_clearance(ready_status() | {"gcode_state":"RUNNING"})
        with self.assertRaises(printer.PrinterError):
            self.read_clearance(ready_status() | {"gcode_state":"FINISH"})
        finished = ready_status() | {"gcode_state":"FINISH", "subtask_name":"new.gcode"}
        error, uploads, starts = self.replay_send(initial=finished, expected_bed=empty)
        self.assertIsInstance(error,printer.PrinterError)
        self.assertFalse(uploads or starts)

    def test_usb_and_all_existing_feed_mappings_are_preserved(self):
        for source in printer.FEED_SOURCES:
            with self.subTest(source=source):
                error, uploads, starts = self.replay_send(source=source)
                self.assertIsNone(error)
                self.assertEqual(len(uploads), 1)
                self.assertEqual(len(starts), 1)
                command = starts[0]
                self.assertTrue(command["url"].startswith("ftp:///cache/mood-"))
                if source == "external":
                    self.assertFalse(command["use_ams"])
                    self.assertEqual(command["ams_mapping"], [-1])
                    self.assertEqual(command["ams_mapping2"], [{"ams_id": 255, "slot_id": 0}])
                else:
                    slot = int(source[-1]) - 1
                    self.assertTrue(command["use_ams"])
                    self.assertEqual(command["ams_mapping"], [slot])
                    self.assertEqual(command["ams_mapping2"], [{"ams_id": 0, "slot_id": slot}])

    def test_unrelated_running_report_and_later_task_id_cannot_confirm_start(self):
        error, uploads, starts = self.replay_send(start="split")
        self.assertIsInstance(error, printer.PrintStatusUnknown)
        self.assertEqual(len(uploads), 1)
        self.assertEqual(len(starts), 1)

    def test_identity_then_separate_active_status_confirms_incremental_stream(self):
        error, _, starts = self.replay_send(start="identity-first")
        self.assertIsNone(error)
        self.assertEqual(len(starts), 1)

    def test_changed_identity_cannot_reuse_previous_matching_name(self):
        error, _, starts = self.replay_send(start="changed-identity")
        self.assertIsInstance(error, printer.PrintStatusUnknown)
        self.assertEqual(len(starts), 1)

    def test_lost_dispatch_response_stays_unknown_and_is_not_retried(self):
        error, _, starts = self.replay_send(start="disconnect")
        self.assertIsInstance(error, printer.PrintStatusUnknown)
        self.assertEqual(len(starts), 1)
        self.assertNotIn("private transport detail", str(error))

    def test_queued_busy_update_after_snapshot_prevents_start(self):
        error, uploads, starts = self.replay_send(after_snapshot={
            "command": "push_status", "gcode_state": "RUNNING", "task_id": "manual-job",
        })
        self.assertIsInstance(error, printer.PrinterError)
        self.assertNotIsInstance(error, printer.PrintStatusUnknown)
        self.assertEqual(len(uploads), 1)
        self.assertFalse(starts)

    def test_failed_upload_never_sends_start(self):
        error, uploads, starts = self.replay_send(upload_error=True)
        self.assertIsInstance(error, printer.PrinterError)
        self.assertFalse(uploads)
        self.assertFalse(starts)

    def test_only_one_local_send_can_run_at_once(self):
        with printer._print_operation():
            with self.assertRaises(printer.PrinterError):
                with printer._print_operation():
                    self.fail("concurrent sender acquired the lock")
        with printer._print_operation():
            pass

    def test_incremental_device_and_ams_updates_preserve_other_fields(self):
        client = ReplayClient()
        connection = printer._PrinterConnection(client, "TEST")
        client.messages.extend((ready_status(), {
            "command": "push_status", "device": {"airduct": {"mode": 0}},
            "ams": {"tray_now": "1"},
        }))
        connection.drain()
        printer._assert_ready(connection.status, 1)
        self.assertEqual(connection.status["device"]["airduct"], {"mode": 0})
        self.assertEqual(connection.status["ams"]["tray_now"], "1")

    def test_refresh_discards_queued_snapshot_from_before_request(self):
        client = ReplayClient()
        connection = printer._PrinterConnection(client, "TEST")
        client.messages.append(ready_status())
        clock = itertools.count(step=1)
        with patch.object(printer, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaises(printer.PrinterError):
                connection.refresh()

    def test_refresh_waits_for_delayed_nozzle_and_feed_details(self):
        snapshot = ready_status()
        details = {key: snapshot.pop(key) for key in ("device", "ams", "vt_tray")}
        client = ReplayClient(snapshot, after_snapshot={"command": "push_status", **details})
        connection = printer._PrinterConnection(client, "TEST")
        printer._assert_ready(connection.refresh(slot=2), 2)

    def test_wrong_or_empty_selected_ams_slot_is_rejected(self):
        for update in ({"tray_exist_bits": "d"}, {"ams_exist_bits": "0"}):
            status = ready_status()
            status["ams"].update(update)
            with self.assertRaises(printer.PrinterError):
                printer._assert_ready(status, 1)
        status = ready_status()
        status["ams"]["ams"][0]["tray"][1]["tray_type"] = "PETG"
        with self.assertRaises(printer.PrinterError):
            printer._assert_ready(status, 1)

    def test_integer_usb_flags_override_legacy_ready_flag(self):
        with self.assertRaises(printer.PrinterError):
            printer._require_storage({"aux": 2 << 12, "sdcard": True})

    def test_artifact_is_snapshotted_and_gcode_is_hashed_in_chunks(self):
        original_read = ZipFile.read

        def read_metadata(archive, name, *args, **kwargs):
            self.assertNotEqual(name, printer.PLATE, "G-code must be streamed")
            return original_read(archive, name, *args, **kwargs)

        with patch.object(ZipFile, "read", read_metadata):
            with printer._load_artifact(self.artifact) as (snapshot, digest, size):
                self.artifact.write_bytes(b"changed after validation")
                self.assertEqual(snapshot.read(), self.bytes)
                self.assertEqual(size, len(self.bytes))
                self.assertEqual(len(digest), 32)
            self.assertTrue(snapshot.closed)

    def test_duplicate_and_wrong_material_archives_are_rejected(self):
        for data in (artifact_bytes(duplicate=True), artifact_bytes(material="PETG")):
            self.artifact.write_bytes(data)
            with self.assertRaises(printer.PrinterError):
                with printer._load_artifact(self.artifact):
                    self.fail("invalid artifact accepted")

    def test_upload_uses_the_snapshot_and_verifies_remote_size(self):
        ftp = Mock()
        ftp.size.return_value = len(self.bytes)
        uploaded = []
        ftp.storbinary.side_effect = lambda command, stream, **options: uploaded.append(stream.read())

        @contextmanager
        def ftps(*args, **kwargs):
            yield ftp

        with patch.object(printer, "_ftps", ftps):
            printer._upload("TEST", "TEST", "TEST", "/cache/test.gcode.3mf", BytesIO(self.bytes), len(self.bytes))
            self.assertEqual(uploaded, [self.bytes])
            self.assertEqual(ftp.method_calls[0].args, ("/cache",))
            self.assertEqual(ftp.method_calls[1].args, ("TYPE I",))
            self.assertEqual(ftp.method_calls[2][0], "prot_p")
            ftp.size.return_value = 0
            with self.assertRaises(printer.PrinterError):
                printer._upload("TEST", "TEST", "TEST", "/cache/test.gcode.3mf", BytesIO(self.bytes), len(self.bytes))

    def test_metadata_size_and_snapshot_creation_errors_fail_before_dispatch(self):
        with patch.object(printer, "MAX_METADATA_BYTES", 64):
            with self.assertRaises(printer.PrinterError):
                with printer._load_artifact(self.artifact):
                    self.fail("oversized metadata accepted")
        with patch.object(printer, "TemporaryFile", side_effect=OSError("simulated internal detail")):
            with self.assertRaises(printer.PrinterError) as caught:
                with printer._load_artifact(self.artifact):
                    self.fail("temporary file error ignored")
            self.assertNotIn("internal detail", str(caught.exception))


class PrintObservationTests(unittest.TestCase):
    ticket = {"task_id": "1234567", "name": "mood-123456abcdef"}

    def observe(self, reports, *, queued=None, studio=None, require_started=False):
        client = ReplayClient()
        connection = printer._PrinterConnection(client, "TEST")
        if queued:
            client.messages.extend(queued)

        def publish(topic, payload, **options):
            command = json.loads(payload)
            client.commands.append((command, options))
            self.assertEqual(command, {"pushing": {"sequence_id": "0", "command": "pushall"}})
            client.messages.extend(deepcopy(reports))
            return SimpleNamespace(rc=0)

        client.publish = publish

        @contextmanager
        def connect(*credentials):
            yield connection

        clock = itertools.count(step=1)
        with (
            patch.object(printer, "_credentials", return_value=("TEST", "TEST", "TEST")),
            patch.object(printer, "_connect", connect),
            patch.object(printer, "_upload") as upload,
            patch.object(printer, "_check_cache") as storage,
            patch.object(printer, "monotonic", side_effect=lambda: next(clock)),
        ):
            if studio:
                result = printer.observe_studio_print(*studio, require_started=require_started)
            else:
                result = printer.observe_print(self.ticket)
            upload.assert_not_called()
            storage.assert_not_called()
        self.assertEqual(len(client.commands), 1)
        self.assertEqual(client.commands[0][1], {"qos": 0, "retain": False})
        return result

    def report(self, state, **fields):
        return {"command": "push_status", "gcode_state": state, **fields}

    def test_studio_needs_same_named_artifact_in_a_fresh_machine_report(self):
        name = "Avatar-146bbad8"
        studio = (name, "146bbad8b53590ab")
        fields = dict(subtask_name=name, gcode_file="Metadata/plate_1.gcode", mc_percent=17, print_error=0)
        snapshot = self.report("RUNNING", **fields)
        self.assertEqual(self.observe([snapshot], studio=studio, require_started=True), {"state":"RUNNING", "percent":17})
        self.assertEqual(self.observe([self.report("FINISH", **fields)], studio=studio)["state"], "FINISH")
        for report in [snapshot | {"subtask_name":"other"}, snapshot | {"gcode_file":"/cache/other.gcode.3mf"},
                       {"command":"push_status", "gcode_state":"FINISH", "gcode_file":"Metadata/plate_1.gcode"},
                       snapshot | {"print_error":1}, snapshot | {"gcode_state":"FINISH"}]:
            with self.subTest(report=report):
                self.assertIsNone(self.observe([report], queued=[snapshot], studio=studio, require_started=True))
        with patch.object(printer, "_connect") as connect:
            self.assertIsNone(printer.observe_studio_print(name, "12345678ffffffff"))
            connect.assert_not_called()

    def test_receipt_ticket_is_running_and_finish_requires_explicit_finish(self):
        for state in ("PREPARE", "SLICING", "RUNNING", "PAUSE", "FAILED", "FINISH", "IDLE"):
            with self.subTest(state=state):
                result = self.observe([self.report(state, task_id=self.ticket["task_id"], mc_percent=40)])
                self.assertEqual(result, {"state": state, "percent": 40})

    def test_unique_file_and_subtask_id_can_each_identify_the_ticket(self):
        for field, value in (
            ("subtask_id", self.ticket["task_id"]),
            ("subtask_name", self.ticket["name"] + ".gcode"),
            ("gcode_file", "/cache/" + self.ticket["name"] + ".gcode.3mf"),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.observe([self.report("FINISH", **{field: value})]), {"state": "FINISH"})

    def test_unrelated_task_finishing_and_later_matching_id_is_not_completion(self):
        result = self.observe([
            self.report("FINISH", task_id="7654321", mc_percent=100),
            {"command": "push_status", "task_id": self.ticket["task_id"]},
        ])
        self.assertIsNone(result)

    def test_fresh_identity_then_later_state_is_supported(self):
        result = self.observe([
            {"command": "push_status", "task_id": self.ticket["task_id"]},
            self.report("RUNNING", mc_percent=12),
        ])
        self.assertEqual(result, {"state": "RUNNING", "percent": 12})

    def test_conflicting_id_and_matching_file_cannot_reuse_old_identity(self):
        result = self.observe([self.report(
            "FINISH", task_id="7654321", gcode_file=self.ticket["name"] + ".gcode.3mf", mc_percent=100,
        )])
        self.assertIsNone(result)

    def test_interleaved_other_job_does_not_reuse_matching_name(self):
        result = self.observe([
            {"command": "push_status", "subtask_name": self.ticket["name"] + ".gcode"},
            self.report("FINISH", task_id="7654321", mc_percent=100),
        ])
        self.assertIsNone(result)

    def test_unknown_or_identity_free_state_is_not_attributed(self):
        for report in (self.report("FINISH", mc_percent=100), self.report("UNKNOWN", task_id=self.ticket["task_id"])):
            self.assertIsNone(self.observe([report]))

    def test_queued_old_finish_is_drained_before_read_only_request(self):
        old = self.report("FINISH", task_id=self.ticket["task_id"], mc_percent=100)
        self.assertIsNone(self.observe([], queued=[old]))

    def test_percent_from_before_job_identity_is_not_reused(self):
        result = self.observe([
            {"command": "push_status", "mc_percent": 100},
            self.report("RUNNING", task_id=self.ticket["task_id"]),
        ])
        self.assertEqual(result, {"state": "RUNNING"})

    def test_invalid_progress_is_omitted_without_changing_reported_state(self):
        for percent in (-1, 101, True, "100", 0.5):
            self.assertEqual(self.observe([
                self.report("RUNNING", task_id=self.ticket["task_id"], mc_percent=percent),
            ]), {"state": "RUNNING"})

    def test_old_or_malformed_tickets_never_connect(self):
        for ticket in (None, {}, {"task_id": "0", "name": self.ticket["name"]},
                       {"task_id": "123", "name": "someone-else"},
                       {"task_id": "2147483647", "name": self.ticket["name"]}):
            with patch.object(printer, "_connect") as connect:
                self.assertIsNone(printer.observe_print(ticket))
                connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
