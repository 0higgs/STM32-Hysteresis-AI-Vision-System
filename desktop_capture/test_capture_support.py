from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from adb_camera import AdbCamera, AdbCameraError, MediaImage, parse_media_rows
from dataset_manifest import append_manifest, successful_shots
from main import build_apply_commands, build_setall_command


class MediaStoreParsingTests(unittest.TestCase):
    def test_parses_reordered_vendor_fields_and_spaces(self) -> None:
        output = (
            "Row: 0 _display_name=IMG 20260813.jpg, _id=401, "
            "_data=/storage/emulated/0/DCIM/Camera/IMG 20260813.jpg, date_added=1786611000\n"
            "Row: 1 _id=400, _display_name=old.jpg, date_added=1786610000, _data=/sdcard/DCIM/old.jpg\n"
        )
        rows = parse_media_rows(output)
        self.assertEqual([row.media_id for row in rows], [401, 400])
        self.assertEqual(rows[0].display_name, "IMG 20260813.jpg")
        self.assertTrue(rows[0].data_path.endswith("IMG 20260813.jpg"))

    def test_ignores_malformed_rows(self) -> None:
        self.assertEqual(parse_media_rows("No result found.\nRow: 0 _id=null"), [])

    def test_export_falls_back_to_adb_pull(self) -> None:
        class LegacyCamera(AdbCamera):
            def _run(self, *args, **kwargs):
                if args[0] == "exec-out":
                    raise AdbCameraError("content read unsupported")
                Path(args[-1]).write_bytes(b"x" * 256)
                return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "capture.jpg"
            image = MediaImage(42, "IMG.jpg", data_path="/sdcard/DCIM/Camera/IMG.jpg")
            self.assertEqual(LegacyCamera().export_image(image, destination), destination)
            self.assertEqual(destination.stat().st_size, 256)

    def test_latest_image_retries_when_vendor_sort_prints_usage_with_success(self) -> None:
        class XiaomiCamera(AdbCamera):
            calls = 0

            def _run(self, *args, **kwargs):
                self.calls += 1
                if "--sort" in args:
                    return subprocess.CompletedProcess(args, 0, "usage: adb shell content", "")
                output = "Row: 0 _id=41, _display_name=old.jpg, date_added=1\nRow: 1 _id=42, _display_name=new.jpg, date_added=2\n"
                return subprocess.CompletedProcess(args, 0, output, "")

        XiaomiCamera._sort_support.clear()
        camera = XiaomiCamera()
        image = camera.latest_image()
        self.assertIsNotNone(image)
        self.assertEqual(image.media_id, 42)
        self.assertEqual(camera.calls, 2)
        camera.latest_image()
        self.assertEqual(camera.calls, 3)

    def test_cancel_event_stops_wait_without_timeout(self) -> None:
        stopped = threading.Event()
        stopped.set()
        camera = AdbCamera(cancel_event=stopped)
        started = time.monotonic()
        with self.assertRaisesRegex(AdbCameraError, "已取消"):
            camera.wait_for_new_image(-1, timeout=15.0)
        self.assertLess(time.monotonic() - started, 0.2)


class ManifestTests(unittest.TestCase):
    def test_append_and_resume_only_existing_successes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "images" / "HYS_1.jpg"
            image.parent.mkdir()
            image.write_bytes(b"jpeg")
            manifest = root / "manifest.csv"
            append_manifest(manifest, {"sample_id": "HYS_1", "shot": 1, "status": "ok",
                                       "image": "images/HYS_1.jpg", "HMAX": 100})
            append_manifest(manifest, {"sample_id": "HYS_2", "shot": 1, "status": "error",
                                       "error": "camera timeout"})
            self.assertEqual(successful_shots(manifest, root), {"HYS_1": {1}})
            raw = manifest.read_bytes()
            self.assertEqual(raw.count(b"\xef\xbb\xbf"), 1)


class ParameterTransitionTests(unittest.TestCase):
    def test_setall_is_one_atomic_line_that_fits_firmware_buffer(self) -> None:
        values = {
            "HMAX": 500.0, "HC": 99.99999, "BR": 1.49999, "BS": 1.99999,
            "LOOP_HZ": 400.0, "X_GAIN": 1.99999, "Y_GAIN": 1.99999,
            "X_OFFSET": -0.79999, "Y_OFFSET": -0.79999,
            "XY_COUPLING": -0.49999, "ASYMMETRY": -0.29999,
            "AMPLITUDE": 1900.0,
        }
        command = build_setall_command(values)
        self.assertTrue(command.startswith("SETALL "))
        self.assertLess(len(command), 128)
        self.assertNotIn("\n", command)

    def test_stages_relational_bounds_before_target_values(self) -> None:
        values = {
            "HMAX": 20.0, "HC": 19.0, "BR": 1.49, "BS": 1.50,
            "LOOP_HZ": 100.0, "X_GAIN": 1.0, "Y_GAIN": 1.0,
            "X_OFFSET": 0.0, "Y_OFFSET": 0.0, "XY_COUPLING": 0.0,
            "ASYMMETRY": 0.0, "AMPLITUDE": 1500.0,
        }
        commands = build_apply_commands(values)
        self.assertEqual(commands[:2], ["SET HMAX 500.00000", "SET BS 2.00000"])
        self.assertLess(commands.index("SET HC 19.00000"), commands.index("SET HMAX 20.00000"))
        self.assertLess(commands.index("SET BR 1.49000"), commands.index("SET BS 1.50000"))
        self.assertEqual(commands[-1], "APPLY")

    def test_transaction_watchdog_retries_when_no_status_arrives(self) -> None:
        from pathlib import Path
        import main

        app = main.HysteresisUI()
        try:
            app.update_idletasks()
            app.table_rows = app.read_parameter_table(Path("capture_parameters_500.csv"))
            app.table_index = 165
            app.table_waiting = True
            app.table_apply_attempts = 1
            app.ser = object()
            reapplied = []
            app.apply_expected_table_row = lambda: reapplied.append(True)
            app.tx_queue.put(b"stale command")
            app._apply_watchdog_expired(165)
            self.assertEqual(reapplied, [True])
            self.assertTrue(app.tx_queue.empty())
            self.assertEqual(app.table_apply_attempts, 2)
        finally:
            app.ser = None
            app.table_waiting = False
            app.destroy()

    def test_bad_status_never_overwrites_table_target_for_retry(self) -> None:
        from pathlib import Path
        import main

        app = main.HysteresisUI()
        try:
            app.update_idletasks()
            app.table_rows = app.read_parameter_table(Path("capture_parameters_500.csv"))
            app.table_index = 183
            item = app.table_rows[183]
            target = float(item["X_OFFSET"])
            self.assertAlmostEqual(target, 0.0397)
            for key, default in main.DEFAULTS.items():
                app.vars[key].set(float(item.get(key, default)))
            app.table_waiting = True
            app.consume_status(
                "STATUS HMAX=54.592 HC=6.681 BR=0.215 BS=0.831 LOOP_HZ=154.245 "
                "X_GAIN=0.964 Y_GAIN=0.956 X_OFFSET=0.000 Y_OFFSET=-0.041 "
                "XY_COUPLING=-0.030 ASYMMETRY=0.000 AMPLITUDE=1469"
            )
            self.assertAlmostEqual(app.vars["X_OFFSET"].get(), target)
            commands = []
            app.send_batch = lambda lines: commands.extend(lines)
            app._arm_apply_watchdog = lambda _index: None
            app.apply_expected_table_row()
            self.assertIn("SET X_OFFSET 0.03970", commands)
            self.assertNotIn("SET X_OFFSET 0.00000", commands)
            if app.status_retry_job:
                app.after_cancel(app.status_retry_job)
                app.status_retry_job = None
        finally:
            app.ser = None
            app.table_waiting = False
            app.destroy()

    def test_device_err_schedules_recovery_without_status(self) -> None:
        from pathlib import Path
        import main

        app = main.HysteresisUI()
        try:
            app.update_idletasks()
            app.table_rows = app.read_parameter_table(Path("capture_parameters_500.csv"))
            app.table_index = 165
            app.table_waiting = True
            app.ser = object()
            app.tx_queue.put(b"stale command")
            app._recover_from_device_error("ERR COMMAND")
            self.assertIsNotNone(app.status_retry_job)
            self.assertTrue(app.tx_queue.empty())
            app.after_cancel(app.status_retry_job)
            app.status_retry_job = None
        finally:
            app.ser = None
            app.table_waiting = False
            app.destroy()


if __name__ == "__main__":
    unittest.main()
