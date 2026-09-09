from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import threading
import time


class AdbCameraError(RuntimeError):
    """An actionable ADB/camera failure."""


@dataclass(frozen=True)
class MediaImage:
    media_id: int
    display_name: str
    date_added: int = 0
    data_path: str = ""

    @property
    def uri(self) -> str:
        return f"content://media/external/images/media/{self.media_id}"


def parse_media_rows(text: str) -> list[MediaImage]:
    """Parse Android's ``content query`` output without depending on column order."""
    images: list[MediaImage] = []
    for line in text.splitlines():
        if "_id=" not in line:
            continue
        fields: dict[str, str] = {}
        # Values may contain spaces. A comma only starts a new field when it is
        # followed by another Android column name and '='.
        body = re.sub(r"^Row:\s*\d+\s+", "", line.strip())
        for part in re.split(r",\s*(?=[A-Za-z_][A-Za-z0-9_]*=)", body):
            key, sep, value = part.partition("=")
            if sep:
                fields[key.strip()] = value.strip()
        try:
            media_id = int(fields["_id"])
        except (KeyError, ValueError):
            continue
        try:
            date_added = int(fields.get("date_added", "0") or 0)
        except ValueError:
            date_added = 0
        images.append(MediaImage(
            media_id=media_id,
            display_name=fields.get("_display_name", f"image_{media_id}.jpg"),
            date_added=date_added,
            data_path=fields.get("_data", ""),
        ))
    return images


class AdbCamera:
    CAMERA_INTENT = "android.media.action.STILL_IMAGE_CAMERA"
    _sort_support: dict[str, bool] = {}

    def __init__(self, adb: str = "adb", serial: str = "", timeout: float = 15.0,
                 cancel_event: threading.Event | None = None) -> None:
        self.adb = str(adb)
        self.serial = serial.strip()
        self.timeout = timeout
        self.cancel_event = cancel_event

    def _command(self, *args: str) -> list[str]:
        command = [self.adb]
        if self.serial:
            command += ["-s", self.serial]
        command += list(args)
        return command

    def _run(self, *args: str, binary: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        limit = timeout or self.timeout
        process = None
        try:
            if self.cancel_event and self.cancel_event.is_set():
                raise AdbCameraError("ADB 操作已取消")
            process = subprocess.Popen(
                self._command(*args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=not binary,
                encoding=None if binary else "utf-8",
                errors=None if binary else "replace",
                creationflags=creationflags,
            )
            deadline = time.monotonic() + limit
            while True:
                if self.cancel_event and self.cancel_event.is_set():
                    process.terminate()
                    try: process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired: process.kill()
                    raise AdbCameraError("ADB 操作已取消")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.communicate()
                    raise AdbCameraError(f"ADB 命令超时（{limit:g} 秒）")
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except FileNotFoundError as exc:
            raise AdbCameraError(f"找不到 adb：{self.adb}") from exc
        if result.returncode != 0:
            stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", "replace")
            stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8", "replace")
            detail = (stderr or stdout).strip() or f"exit {result.returncode}"
            raise AdbCameraError(detail)
        return result

    @staticmethod
    def list_devices(adb: str = "adb", timeout: float = 8.0) -> list[tuple[str, str]]:
        client = AdbCamera(adb=adb, timeout=timeout)
        output = client._run("devices", "-l", timeout=timeout).stdout
        devices: list[tuple[str, str]] = []
        for line in output.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
        return devices

    def ensure_ready(self) -> str:
        devices = self.list_devices(self.adb, self.timeout)
        if self.serial:
            matching = [state for serial, state in devices if serial == self.serial]
            if not matching:
                raise AdbCameraError(f"没有找到手机 {self.serial}")
            state = matching[0]
        else:
            ready = [(serial, state) for serial, state in devices if state == "device"]
            if len(ready) != 1:
                raise AdbCameraError("请连接且只选择一台处于 device 状态的手机")
            self.serial, state = ready[0]
        if state == "unauthorized":
            raise AdbCameraError("手机尚未授权；请解锁手机并允许这台电脑进行 USB 调试")
        if state != "device":
            raise AdbCameraError(f"手机状态为 {state}，不是 device")
        return self.serial

    def open_camera(self) -> None:
        self.ensure_ready()
        self._run("shell", "am", "start", "-a", self.CAMERA_INTENT)

    def latest_image(self) -> MediaImage | None:
        args = (
            "shell", "content", "query",
            "--uri", "content://media/external/images/media",
            "--projection", "_id:_display_name:date_added:_data",
            "--sort", "_id DESC",
        )
        rows: list[MediaImage] = []
        support_key = self.serial or "<default>"
        if self._sort_support.get(support_key, True):
            try:
                output = self._run(*args).stdout
            except AdbCameraError:
                output = ""
            rows = parse_media_rows(output)
            self._sort_support[support_key] = bool(rows)
        # Some Xiaomi/vendor builds print usage and still return exit code 0
        # when --sort is unsupported. Treat an unparseable response exactly
        # like a failed sorted query and retry without that option.
        if not rows:
            output = self._run(*args[:-2]).stdout
            rows = parse_media_rows(output)
        return max(rows, key=lambda row: row.media_id, default=None)

    def trigger_shutter(self, tap: tuple[int, int] | None = None) -> None:
        if tap is None:
            self._run("shell", "input", "keyevent", "27")
        else:
            self._run("shell", "input", "tap", str(tap[0]), str(tap[1]))

    def wait_for_new_image(self, previous_id: int, timeout: float = 15.0) -> MediaImage:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.cancel_event and self.cancel_event.is_set():
                raise AdbCameraError("ADB 操作已取消")
            image = self.latest_image()
            if image and image.media_id != previous_id:
                return image
            if self.cancel_event:
                if self.cancel_event.wait(0.35):
                    raise AdbCameraError("ADB 操作已取消")
            else:
                time.sleep(0.35)
        raise AdbCameraError(
            "按下快门后没有发现新照片。请确认相机在前台，并尝试在手机相机设置中启用音量键拍照。"
        )

    def export_image(self, image: MediaImage, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        try:
            result = self._run("exec-out", "content", "read", "--uri", image.uri,
                               binary=True, timeout=30.0)
            payload = result.stdout
            if not payload or len(payload) < 128:
                raise AdbCameraError("手机返回的照片为空或不完整")
            temporary.write_bytes(payload)
        except AdbCameraError:
            # Older vendor builds may support MediaStore queries but not
            # ``content read``. The legacy _data path remains a useful fallback.
            if not image.data_path:
                raise
            self._run("pull", image.data_path, str(temporary), timeout=30.0)
        if not temporary.is_file() or temporary.stat().st_size < 128:
            raise AdbCameraError("回传后的照片为空或不完整")
        temporary.replace(destination)
        return destination

    def capture(self, destination: Path, tap: tuple[int, int] | None = None,
                save_timeout: float = 15.0) -> tuple[Path, MediaImage]:
        self.ensure_ready()
        before = self.latest_image()
        self.trigger_shutter(tap)
        image = self.wait_for_new_image(before.media_id if before else -1, save_timeout)
        suffix = Path(image.display_name).suffix.lower()
        if suffix and destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)
        return self.export_image(image, destination), image
