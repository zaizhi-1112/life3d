"""Send checked, single-spool Bambu Lab P2S jobs over its LAN Developer Mode."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from ftplib import FTP, FTP_TLS, all_errors, error_perm
from hashlib import file_digest, md5, sha256
from ipaddress import IPv4Address, IPv4Network
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
from tempfile import TemporaryFile
from threading import Lock
from time import monotonic
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


PLATE = "Metadata/plate_1.gcode"
UPLOAD_DIR = "/cache"
FEED_SOURCES = ("external", "ams-a1", "ams-a2", "ams-a3", "ams-a4")
STUDIO_CA = Path("/Applications/BambuStudio.app/Contents/Resources/cert/printer.cer")
LAN_NETWORKS = tuple(
    IPv4Network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
PRINTER_ENV = ("BAMBU_IP", "BAMBU_SERIAL", "BAMBU_ACCESS_CODE")
JOB_FIELDS = ("task_id", "subtask_id", "subtask_name", "gcode_file")
_PRINT_LOCK = Lock()

# BBL Device CA N7-V2, published by SpoolEase at core/src/certs/bambulab_p2s.pem.
# The intermediate was verified against the certificate bundle shipped by Bambu Studio.
P2S_INTERMEDIATE = """-----BEGIN CERTIFICATE-----
MIIFiDCCA3CgAwIBAgIUaOxODRrxHIIZlHAod5eOwyG3BJkwDQYJKoZIhvcNAQEL
BQAwRjELMAkGA1UEBhMCQ04xITAfBgNVBAoMGEJCTCBUZWNobm9sb2dpZXMgQ28u
IEx0ZDEUMBIGA1UEAwwLQkJMIENBMiBSU0EwHhcNMjUwNjI2MDgzMDU0WhcNNDAw
NjI2MDgzMDU0WjBOMQswCQYDVQQGEwJDTjEhMB8GA1UECgwYQkJMIFRlY2hub2xv
Z2llcyBDby4gTHRkMRwwGgYDVQQDDBNCQkwgRGV2aWNlIENBIE43LVYyMIICIjAN
BgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA1q/fVvmynVm4D1QtzktdXv5SknS+
v/VuCM0odWHaQ8FhliXuaFUD5sHtN6gSUDU15KdcvfeS850SPd79F/N48AIWFhDq
Za0nJnk2+Gv79ITkISaa8lBbpqwvDHd/k8beDQLN72pZFMWcekhCTl12B6vPgxxw
PQtsqaFjpA0Ye+a/NkNtEPBEt0ZUlv/2H4masB/YaVf3Pfkmcsz8toGAYQCx99os
Gz9S6OJvF2WYDrhQwGXCT9Ebeqhdf2A8bTRqMXh2Eusfxs8Vwnex+HMZ0fGD24MK
wxMvRJJ0ThwPRmEYDiR5EhoPuWdyFmZ+Cazg7AeNLo7FjTetsHNBuo61FSolrP+X
rzRkdbJrxa2vbuyAApFK71WeK98MlUCO5b4mkMkenBDVLqSIyw5Q/aAB4PqDscAs
ixlOgE91fUlA3p0ZN3BK5BTi/oNue2v6/+krqYV5gBUcnx4ixYz5joaokCFrWM/O
s7Fjo8iMVv/XGwH/UDa1VGV9wN5FU6TyuUYSl00SGpEt4/1jAqriqBU3B1dC+BhZ
8huhCW19xI2kWsZDGcmEhxnoZfYmpD4AdMYoF/daUVPP3F4CSrjqLzXABUHBOMZJ
g5KAEb92j34ZycVnQfOB4SB1hKSoHcuT3UAjmR9FE13apfwwvynoCJzohW1szwKN
5YzBBv/szamiQS0CAwEAAaNmMGQwEgYDVR0TAQH/BAgwBgEB/wIBADAOBgNVHQ8B
Af8EBAMCAQYwHQYDVR0OBBYEFKz7LDkKuUzML/DZxB17wptduym6MB8GA1UdIwQY
MBaAFNVJgQad1sNTN0jxVkwbJ/XM1an1MA0GCSqGSIb3DQEBCwUAA4ICAQBqWtA9
c0ttQ1u/3DHsgOpP2eNZjMCTdK8ee/5szdV4fMR/+ZrF1ao4fP0Oc8qcRnmQsZ1S
Mx727aQm+X87Hh5GU+2aJUfROLjiWEVE3zT8F+wYmojm/rR9Ai0CY3TWDiF3hspQ
0aPeME1ZvMSAFvSeWUdj8RbRMUSTneyPOk6dosNJZd4fpGr0uV2xCsL2Ykw/e6W8
5WzQSDoLbW08wa+N4SuDzto+IxX4Fg+IgQ4fc2x1cWUEN5Q5Mch8dOlJJUFK+jHh
muhAWM3pCcJAR1Fi9cEkkpgHILLonng/xJTzpaX/bvzpyoSLqlvF0Wizr+2CxvHg
lHf80fw6w+TVmnubTPk1JAzEn/KXxQFOXz7zy6MB3luK64C8L7XwlUJk4sCmbD0N
slsUN7s5thgZM+o4zAj1G6KOMH3lcpBw0SiLVOB3qLFANMT0pnKDYMMnTVMKv3CB
GVqbFPAUn2vLScaZG5jiuBsSaIY9WAfGrae02Lp+KYbt2aRQ1SM4llkbdHYbIx53
n3+9BCScDy/3Gy7c3o8avUGI2AKGi+5teciOaLbmzkz2iFWjiUz4CB6Bm1VePRru
UZkPxKr9W3Y20kZwOalGQDrcms+WCpp54zd200CgYF6A6IkgmMtdh1K+lnRMCao5
v09+U4m1fOSvF0We4MPCYt+z/E/br+uZ1pIBcg==
-----END CERTIFICATE-----
"""


class PrinterError(RuntimeError):
    """The printer operation could not be completed."""


class PrintStatusUnknown(PrinterError):
    """A start may already have been accepted. Verify on the printer before retrying."""


class PrinterUnreachable(PrinterError):
    """This Mac is not on the printer's LAN, so nothing was sent."""


class ColorChanged(PrinterError):
    """The selected spool or the reviewed slice changed before dispatch."""


def _credentials():
    host, serial, code = (os.environ.get(key, "").strip() for key in PRINTER_ENV)
    try:
        address = IPv4Address(host)
    except ValueError:
        raise PrinterError("请在本机配置 P2S 的局域网 IP、序列号和访问码。") from None
    if not any(address in network for network in LAN_NETWORKS):
        raise PrinterError("打印机地址须为本地局域网 IPv4 地址。")
    if not re.fullmatch(r"22E[A-Z0-9]{8,24}", serial) or not re.fullmatch(r"[A-Za-z0-9]{8}", code):
        raise PrinterError("请检查本机配置里的 P2S 序列号和访问码。")
    return str(address), serial, code


def _tls_context(serial, *, ftps=False):
    # The LAN TCP destination is an IP, but the certificate identifies the serial.
    class PrinterTLS(ssl.SSLContext):
        def wrap_socket(self, sock, *args, server_hostname=None, **kwargs):
            return super().wrap_socket(sock, *args, server_hostname=serial, **kwargs)

    context = PrinterTLS(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(STUDIO_CA), cadata=P2S_INTERMEDIATE)
    # P2S FTPS requires data-channel TLS session reuse.
    if ftps:
        context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


class _ImplicitFTPS(FTP_TLS):
    def open(self, host):
        self.host = host
        with socket.create_connection((host, 990), timeout=self.timeout) as sock:
            self.sock = self.context.wrap_socket(sock, server_hostname=host)
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.getresp()

    def ntransfercmd(self, command, rest=None):
        # FTP.ntransfercmd waits for 150 before we start the protected data channel.
        sock, size = FTP.ntransfercmd(self, command, rest)
        try:
            connection = self.context.wrap_socket(sock, server_hostname=self.host, session=self.sock.session)
        except OSError:
            sock.close()
            raise
        return connection, size


@contextmanager
def _ftps(host, serial, code, *, timeout):
    context = _tls_context(serial, ftps=True)
    with _ImplicitFTPS(context=context, timeout=timeout) as ftp:
        ftp.open(host)
        ftp.login("bblp", code)
        yield ftp


def _require_cache(ftp):
    try:
        ftp.cwd(UPLOAD_DIR)
    except error_perm:
        raise PrinterError("打印机的任务目录不可用。请在 P2S 屏幕检查 U 盘是否已识别、可写。") from None


def _check_cache(host, serial, code):
    try:
        with _ftps(host, serial, code, timeout=8) as ftp:
            _require_cache(ftp)
    except all_errors:
        raise _unreachable(host, "无法访问 P2S 的文件传输服务。请检查局域网和开发者模式。") from None


def _upload(host, serial, code, remote_path, source, size):
    try:
        with _ftps(host, serial, code, timeout=45) as ftp:
            _require_cache(ftp)
            ftp.voidcmd("TYPE I")
            ftp.prot_p()
            source.seek(0)
            ftp.storbinary(f"STOR {remote_path}", source, blocksize=CHUNK_BYTES)
            if ftp.size(remote_path) != size:
                raise PrinterError("打印机上的文件大小不一致，未启动。")
    except all_errors:
        raise PrinterError("上传失败。请检查 P2S 的开发者模式、局域网连接和 U 盘。") from None


@contextmanager
def _load_artifact(artifact):
    """Keep one checked byte snapshot on disk through the upload."""
    try:
        snapshot = TemporaryFile()
    except OSError:
        raise PrinterError("无法暂存 P2S 切片文件，请检查本机剩余空间。") from None
    with snapshot:
        try:
            size = 0
            with Path(artifact).open("rb") as source:
                while chunk := source.read(CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_ARTIFACT_BYTES:
                        raise PrinterError("切片文件超出本地打印上传的大小限制。")
                    snapshot.write(chunk)
            snapshot.seek(0)
            digest = _inspect_artifact(snapshot)
        except OSError:
            raise PrinterError("无法读取或暂存 P2S 切片文件。") from None
        snapshot.seek(0)
        yield snapshot, digest, size


def _inspect_artifact(source):
    try:
        with ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise PrinterError("切片文件包含重复的配置或模型条目。")
            plate_files = [name for name in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", name)]
            if plate_files != [PLATE]:
                raise PrinterError("请使用应用为 P2S 切片生成的单盘文件。")
            for name in (PLATE, "Metadata/project_settings.config", "Metadata/slice_info.config"):
                info = archive.getinfo(name)
                limit = MAX_ARTIFACT_BYTES if name == PLATE else MAX_METADATA_BYTES
                if info.flag_bits & 1 or not 0 < info.file_size <= limit:
                    raise PrinterError("切片文件的内容大小或加密标记无效。")
            project = json.loads(archive.read("Metadata/project_settings.config"))
            info = ElementTree.fromstring(archive.read("Metadata/slice_info.config"))
            plate = info.find("plate")
            metadata = {item.get("key"): item.get("value") for item in plate.findall("metadata")}
            if (
                project["printer_model"] != "Bambu Lab P2S"
                or project["nozzle_diameter"] != ["0.4"]
                or project["filament_type"] != ["PLA"]
                or project["curr_bed_type"] != "Textured PEI Plate"
                or metadata["outside"] != "false"
                or len(info.findall("plate")) != 1
                or not 0 < int(metadata["prediction"]) <= 180 * 60
            ):
                raise PrinterError("只发送 0.4 mm 喷嘴、单色 PLA、预计 3 小时以内的 P2S 切片。")
            digest = md5(usedforsecurity=False)
            with archive.open(PLATE) as gcode:
                while chunk := gcode.read(CHUNK_BYTES):
                    digest.update(chunk)
    except (OSError, BadZipFile, ElementTree.ParseError, KeyError, TypeError, AttributeError, ValueError):
        raise PrinterError("无法验证 P2S 切片文件。") from None
    return digest.hexdigest()


def _merge_report(target, update):
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_report(target[key], value)
        else:
            target[key] = value


class _PrinterConnection:
    def __init__(self, client, serial):
        self.client = client
        self.report = f"device/{serial}/report"
        self.request = f"device/{serial}/request"
        self.subscribed = False
        self.status = {}
        self.report_number = 0
        self.field_numbers = {}
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason, properties):
        if not reason.is_failure:
            client.subscribe(self.report)

    def _on_subscribe(self, client, userdata, mid, reasons, properties):
        self.subscribed = bool(reasons) and not any(reason.is_failure for reason in reasons)

    def _on_message(self, client, userdata, message):
        if message.topic != self.report or message.retain:
            return
        try:
            report = json.loads(message.payload).get("print")
        except (AttributeError, ValueError):
            return
        if isinstance(report, dict) and report.get("command") == "push_status":
            self.report_number += 1
            self.field_numbers.update((field, self.report_number) for field in report)
            _merge_report(self.status, report)

    def publish(self, payload):
        if self.client.publish(self.request, json.dumps(payload), qos=0, retain=False).rc != 0:
            raise PrinterError("打印机连接已中断。")

    def wait(self, condition, seconds, *, missing_ok=False):
        deadline = monotonic() + seconds
        while not condition():
            remaining = deadline - monotonic()
            if remaining <= 0:
                if missing_ok:
                    return False
                raise PrinterError("没有收到 P2S 的实时状态，请检查打印机连接。")
            if self.client.loop(timeout=min(remaining, 1.0)) != 0:
                raise PrinterError("打印机连接已中断。")
        return True

    def drain(self):
        # Process queued status before a fresh read or an irreversible command.
        for _ in range(100):
            previous = self.report_number
            if self.client.loop(timeout=0) != 0:
                raise PrinterError("打印机连接已中断。")
            if self.report_number == previous:
                return
        raise PrinterError("打印机状态更新过于密集，请稍后检查。")

    def request_status(self):
        self.drain()
        self.status.clear()
        self.field_numbers.clear()
        self.publish({"pushing": {"sequence_id": "0", "command": "pushall"}})

    def refresh(self, *, slot=None):
        self.request_status()
        self.wait(lambda: _status_complete(self.status, slot), 8)
        return self.status


def _local_address(host):
    """The address this Mac would use to reach the printer, without sending anything."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((host, 8883))
            return probe.getsockname()[0]
    except OSError:
        return None


def _away_message(host):
    # A proxy's virtual interface can accept the TCP connection and then fail
    # TLS, which used to surface as a misleading certificate error.
    local = _local_address(host)
    if local and local.split(".")[:3] == host.split(".")[:3]:
        return None
    return (f"连不上 P2S：这台 Mac 现在不在打印机所在的局域网（打印机 {host}）。"
            "连回同一个 Wi-Fi，或让代理软件绕过局域网地址，工作台会自动重试。")


def _unreachable(host, otherwise):
    away = _away_message(host)
    return PrinterUnreachable(away) if away else PrinterError(otherwise)


@contextmanager
def _connect(host, serial, code):
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:
        raise PrinterError("局域网打印需要在应用的 Python 环境安装 paho-mqtt 2.x。") from None

    client = mqtt.Client(CallbackAPIVersion.VERSION2, reconnect_on_failure=False)
    client.username_pw_set("bblp", code)
    client.connect_timeout = 8
    connection = _PrinterConnection(client, serial)
    try:
        client.tls_set_context(_tls_context(serial))
        if client.connect(host, 8883, keepalive=30) != 0:
            raise PrinterError("无法连接 P2S。")
        connection.wait(lambda: connection.subscribed, 8)
        yield connection
    except ssl.SSLError:
        raise _unreachable(host, "无法验证 P2S 的局域网证书，请检查序列号与 Bambu Studio 安装。") from None
    except OSError:
        raise _unreachable(host, "无法访问或验证 P2S。请检查局域网、序列号、访问码和开发者模式。") from None
    finally:
        with suppress(OSError):
            client.disconnect()


def _state(status):
    state = status.get("gcode_state")
    if state in ("IDLE", "FINISH", "PREPARE", "SLICING", "RUNNING", "PAUSE", "FAILED"):
        return state
    return "UNKNOWN"


def _status_complete(status, slot):
    if not all(key in status for key in ("gcode_state", "print_error", "hms")):
        return False
    if _state(status) not in ("IDLE", "FINISH"):
        return True
    device = status.get("device")
    nozzle = device.get("nozzle") if isinstance(device, dict) else None
    has_nozzle = "nozzle_diameter" in status or isinstance(nozzle, dict) and "info" in nozzle
    if slot is None:
        has_filament = "vt_tray" in status or "vir_slot" in status
    else:
        ams = status.get("ams")
        has_filament = isinstance(ams, dict) and all(
            key in ams for key in ("ams_exist_bits", "tray_exist_bits", "ams")
        )
    return has_nozzle and has_filament


def _identity(status):
    return (status.get("subtask_name"), status.get("task_id"), status.get("gcode_file"))


def _bed_job_fields(status):
    # Some firmware reports numeric IDs as strings and uses zero for no job.
    return ["" if status.get(key) in (None, "", 0, "0") else str(status[key])
            for key in (*JOB_FIELDS, "gcode_start_time")]


def _bed_signature(connection):
    status = connection.status
    connection.wait(lambda: _state(status) != "UNKNOWN" and "print_error" in status and "hms" in status, 8)
    if _state(status) in ("IDLE", "FINISH") and not any(_bed_job_fields(status)):
        # A fresh printer can explicitly report IDLE with no previous job.
        # Allow a separate identity packet to arrive after the status packet.
        connection.wait(lambda: any(_bed_job_fields(status)) or _state(status) not in ("IDLE", "FINISH"),
                        2, missing_ok=True)
    connection.drain()
    state = _state(status)
    if state not in ("IDLE", "FINISH"):
        raise PrinterError("P2S 尚未空闲。请在当前任务结束、取下成品后重新确认清盘。")
    fields = _bed_job_fields(status)
    if state == "FINISH" and not any(fields):
        raise PrinterError("P2S 尚未报告上一件任务的身份，请稍后重新确认清盘。")
    return sha256(json.dumps(fields).encode()).hexdigest()


def read_idle_bed():
    """Return only a fingerprint of the last task on the currently idle printer."""
    with _connect(*_credentials()) as connection:
        connection.request_status()
        return _bed_signature(connection)


def _check_cleared_bed(connection, expected):
    if expected is not None and _bed_signature(connection) != expected:
        raise PrinterError("清盘后 P2S 又接过其他任务。请取下成品，重新确认清盘。")


def _informational_notice(notice):
    # Bambu Studio DevHMS: common (3) and informational (4) are nonfatal.
    code = notice.get("code") if isinstance(notice, dict) else None
    return type(code) is int and (code >> 16) in (3, 4)


def _feed_slot(source):
    if source not in FEED_SOURCES:
        raise PrinterError("请选择外置料架或 AMS 的 A1 至 A4 料槽。")
    if source == "external":
        return None
    return int(source[-1]) - 1


def _hex_flags(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]+", value):
        return int(value, 16)
    return 0


def _by_id(entries, entry_id):
    if not isinstance(entries, list):
        return {}
    matches = [item for item in entries if isinstance(item, dict) and str(item.get("id")) == str(entry_id)]
    return matches[0] if len(matches) == 1 else {}


def _require_pla(status, slot):
    if slot is not None:
        ams = status.get("ams")
        ams = ams if isinstance(ams, dict) else {}
        unit = _by_id(ams.get("ams"), 0)
        tray = _by_id(unit.get("tray"), slot)
        if (
            not _hex_flags(ams.get("ams_exist_bits")) & 1
            or not _hex_flags(ams.get("tray_exist_bits")) & (1 << slot)
            or str(tray.get("tray_type", "")).strip().upper() != "PLA"
        ):
            raise PrinterError(f"请检查 AMS 的 A{slot + 1} 料槽已装 PLA，并且打印机正确识别了耗材。")
        return tray

    external = status.get("vt_tray")
    slots = status.get("vir_slot")
    if isinstance(slots, list) and slots:
        if len(slots) != 1 or not isinstance(slots[0], dict) or str(slots[0].get("id")) not in ("254", "255"):
            raise PrinterError("打印机没有报告唯一的外置料架。")
        external = slots[0]
    if not isinstance(external, dict) or str(external.get("tray_type", "")).strip().upper() != "PLA":
        raise PrinterError("请确认外置料架已装 PLA，并在打印机上把外置耗材设为 PLA。")
    return external


_SWATCHES = {
    "黑色":"202020", "灰色":"858585", "白色":"FFFFFF", "奶油色":"F7E6CC",
    "棕色":"785239", "红色":"D73535", "粉色":"F0A0B5", "橙色":"EB832A",
    "黄色":"F0CF3E", "绿色":"52A85E", "墨绿色":"235B43", "蓝色":"447FCA",
    "浅蓝色":"A3D9EA", "青色":"35B5AC", "紫色":"9557AA", "深蓝色":"26375D",
}


def _spool(status, source):
    tray = _require_pla(status, _feed_slot(source))
    rgba = str(tray.get("tray_color", "")).upper()
    if not re.fullmatch(r"[0-9A-F]{8}", rgba) or len(set(tray.get("cols") or [])) > 1:
        raise PrinterError("P2S 尚未报告这卷 PLA 的单一颜色，请在机身核对耗材。")
    rgb = bytes.fromhex(rgba[:6])
    name = min(_SWATCHES, key=lambda key: sum((a-b)**2 for a,b in zip(rgb, bytes.fromhex(_SWATCHES[key]))))
    slot_name = "外置" if source == "external" else source[-2:].upper()
    return {"source": source, "label": f"{slot_name} · {name} PLA", "color": "#" + rgba[:6], "rgba": rgba}


def available_spools():
    with _connect(*_credentials()) as connection:
        connection.request_status()
        def reported():
            status = connection.status
            ams = status.get("ams") or {}
            return (all(key in ams for key in ("ams_exist_bits", "tray_exist_bits", "ams"))
                    and ("vir_slot" in status or "vt_tray" in status))
        # Wait for the full inventory when both reports are available. Some firmware
        # versions only report one source, so still offer the verified subset.
        connection.wait(reported, 8, missing_ok=True)
        choices = []
        for source in FEED_SOURCES:
            with suppress(PrinterError):
                choices.append(_spool(connection.status, source))
    if not choices:
        raise PrinterError("P2S 尚未报告可选颜色，请在机身设置 PLA 的颜色后重试。")
    return choices


def _check_spool(status, source, expected):
    if expected is None:
        return
    try:
        spool = _spool(status, source)
    except PrinterError:
        spool = {}
    if spool.get("rgba") != expected:
        raise ColorChanged("选中的料槽或颜色已变更。请在飞书重新选色。")


def _require_storage(status):
    # DevStorage handles legacy sdcard/home_flag and DeviceManager handles newer aux.
    aux = status.get("aux")
    home = status.get("home_flag")
    card = status.get("sdcard")
    state = None
    if (
        type(aux) is int and aux >= 0
        or isinstance(aux, str) and re.fullmatch(r"[0-9a-fA-F]+", aux)
    ):
        state = (_hex_flags(aux) >> 12) & 3
    elif type(home) is int:
        state = (home >> 8) & 3
    elif type(card) is bool:
        state = int(card)
    if state == 0:
        raise PrinterError("P2S 未识别到 U 盘。请插入 U 盘并在打印机屏幕确认存储可用。")
    if state in (2, 3):
        raise PrinterError("P2S 报告 U 盘异常或只读。请在打印机屏幕检查存储。")


def _assert_ready(status, slot=None):
    if _state(status) not in ("IDLE", "FINISH"):
        raise PrinterError("打印机当前没有就绪。")
    notices = status.get("hms")
    if (
        status.get("print_error") not in (0, "0")
        or not isinstance(notices, list)
        or not all(_informational_notice(notice) for notice in notices)
    ):
        raise PrinterError("打印机有未处理的状态提示，请在机器上检查。")
    device = status.get("device")
    device = device if isinstance(device, dict) else {}
    nozzle_system = device.get("nozzle")
    nozzles = nozzle_system.get("info") if isinstance(nozzle_system, dict) else None
    nozzle = {}
    if isinstance(nozzles, list):
        active = [entry for entry in nozzles if isinstance(entry, dict) and str(entry.get("id")) == "0"]
        if len(active) != 1:
            raise PrinterError("打印机未报告唯一的活动喷嘴。")
        nozzle = active[0]
    diameter = nozzle.get("diameter", status.get("nozzle_diameter"))
    try:
        status_bits = int(nozzle.get("stat", 0))
        trusted_diameter = status_bits >= 0 and (
            status_bits & 7 == 0 or (status_bits & 7 == 1 and nozzle.get("sn") == "N/A")
        )
        diameter_matches = float(diameter) == 0.4 and trusted_diameter
    except (TypeError, ValueError):
        diameter_matches = False
    if not diameter_matches:
        raise PrinterError("打印机未报告正常的 0.4 mm 喷嘴。")
    _require_pla(status, slot)


def printer_status(*, source: str = "external"):
    """Return a current, sanitized P2S state without uploading or starting a job."""
    slot = _feed_slot(source)
    credentials = _credentials()
    with _connect(*credentials) as connection:
        status = connection.refresh(slot=slot)
    result = {"model": "P2S", "state": _state(status), "source": source, "ready": True, "storage_ready": True}
    try:
        _assert_ready(status, slot)
    except PrinterError as error:
        result.update(ready=False, reason=str(error))
    try:
        _require_storage(status)
        _check_cache(*credentials)
    except PrinterError as error:
        result.update(ready=False, storage_ready=False, storage_reason=str(error))
        result.setdefault("reason", str(error))
    return result


@contextmanager
def _print_operation():
    if not _PRINT_LOCK.acquire(blocking=False):
        raise PrinterError("正在向打印机发送任务，请等当前发送结束。")
    try:
        yield
    finally:
        _PRINT_LOCK.release()


def _confirmed_start(connection, submission, name, after):
    report = connection.status
    names = (f"{name}.gcode", f"{name}.gcode.3mf", name)
    matches = (
        str(report.get("task_id")) == submission,
        str(report.get("subtask_id")) == submission,
        report.get("subtask_name") in names,
        Path(str(report.get("gcode_file", ""))).name in names,
    )
    matching_number = max(
        (connection.field_numbers.get(field, 0) for field, match in zip(JOB_FIELDS, matches) if match),
        default=0,
    )
    latest_identity = max(connection.field_numbers.get(field, 0) for field in JOB_FIELDS)
    state_number = connection.field_numbers.get("gcode_state", 0)
    # The identity must precede (or accompany) the active-state observation.
    # A later identity-only packet cannot reuse another job's active state.
    return (
        after < matching_number <= state_number
        and matching_number >= latest_identity
        and _state(report) in ("PREPARE", "SLICING", "RUNNING")
        and report.get("print_error") in (0, "0")
    )


def send_print(artifact: Path, *, model: str, source: str = "external", expected_rgba=None, expected_slice=None,
               expected_bed=None) -> dict:
    """Upload once and verify this job's identity before its active-state report."""
    if model.strip().upper() != "P2S":
        raise PrinterError("局域网自动打印目前只适配 P2S。")
    slot = _feed_slot(source)
    host, serial, code = _credentials()
    with _print_operation(), _load_artifact(artifact) as (snapshot, digest, size):
        if expected_slice is not None:
            if file_digest(snapshot, "sha256").hexdigest() != expected_slice:
                raise ColorChanged("切片已更新。请按新尺寸和预计耗时在飞书重新确认。")
            snapshot.seek(0)
        submission = str(secrets.randbelow(2**31 - 2) + 1)
        name = f"mood-{secrets.token_hex(6)}"
        remote_path = f"{UPLOAD_DIR}/{name}.gcode.3mf"

        with _connect(host, serial, code) as connection:
            status = connection.refresh(slot=slot)
            _check_cleared_bed(connection, expected_bed)
            _check_spool(status, source, expected_rgba)
            _assert_ready(status, slot)
            _require_storage(status)
            previous_job = _identity(status)

        _upload(host, serial, code, remote_path, snapshot, size)
        with _connect(host, serial, code) as connection:
            status = connection.refresh(slot=slot)
            _assert_ready(status, slot)
            _require_storage(status)
            # A queued update can arrive after refresh's complete snapshot.
            connection.drain()
            _check_cleared_bed(connection, expected_bed)
            _check_spool(status, source, expected_rgba)
            _assert_ready(status, slot)
            _require_storage(status)
            if previous_job != _identity(status):
                raise PrinterError("上传期间打印机任务有变化，请检查打印板。")

            command = {"print": {
                "command": "project_file", "sequence_id": "0", "param": PLATE,
                "url": f"ftp://{remote_path}", "file": Path(remote_path).name, "md5": digest,
                "subtask_name": f"{name}.gcode", "profile_id": "0", "project_id": submission,
                "task_id": submission, "subtask_id": submission, "bed_type": "auto",
                "bed_leveling": 1, "auto_bed_leveling": 1, "layer_inspect": 1,
                "timelapse": 0, "vibration_cali": 0, "flow_cali": 0,
                "cfg": "0", "extrude_cali_flag": 0, "extrude_cali_manual_mode": 0,
                "nozzle_offset_cali": 0,
                "use_ams": slot is not None, "ams_mapping": [-1 if slot is None else slot],
                "ams_mapping2": [{"ams_id": 255 if slot is None else 0, "slot_id": 0 if slot is None else slot}],
            }}
            dispatch_number = connection.report_number

            def started():
                return _confirmed_start(connection, submission, name, dispatch_number)

            # QoS 0 and no reconnect avoid resending after an ambiguous dispatch.
            try:
                connection.publish(command)
                connection.wait(started, 60)
            except (PrinterError, OSError):
                raise PrintStatusUnknown(
                    "开打指令已尝试发送，尚未确认结果。请在 P2S 屏幕上查看任务，避免重复打印。"
                ) from None
            return {"task_id": submission, "name": name}


def _valid_ticket(ticket):
    if not isinstance(ticket, dict):
        return False
    task_id, name = ticket.get("task_id"), ticket.get("name")
    return (
        isinstance(task_id, str) and re.fullmatch(r"[1-9][0-9]{0,9}", task_id) is not None
        and int(task_id) < 2**31 - 1
        and isinstance(name, str) and re.fullmatch(r"mood-[a-f0-9]{12}", name) is not None
    )


def _observed_ticket(connection, ticket):
    report = connection.status
    if _state(report) == "UNKNOWN":
        return None
    names = (ticket["name"], ticket["name"] + ".gcode", ticket["name"] + ".gcode.3mf")
    matching_numbers = []
    for field in JOB_FIELDS:
        value = report.get(field)
        if value in (None, "", 0, "0"):
            continue
        if field in ("task_id", "subtask_id"):
            matches = str(value) == ticket["task_id"]
        else:
            matches = isinstance(value, str) and Path(value).name in names
        # A mixed report naming another job cannot reuse a matching old field.
        if not matches:
            return None
        matching_numbers.append(connection.field_numbers.get(field, 0))
    matched_at = max(matching_numbers, default=0)
    if not 0 < matched_at <= connection.field_numbers.get("gcode_state", 0):
        return None
    result = {"state": _state(report)}
    percent = report.get("mc_percent")
    if (
        type(percent) is int and 0 <= percent <= 100
        and connection.field_numbers.get("mc_percent", 0) >= matched_at
    ):
        result["percent"] = percent
    return result


def observe_print(ticket: dict) -> dict | None:
    """Read only this ticket's live state. Acceptance alone never implies FINISH."""
    if not _valid_ticket(ticket):
        return None
    return _read_observation(lambda connection: _observed_ticket(connection, ticket))


def valid_studio_name(name, artifact_version):
    """A Studio receipt must explicitly link a unique display name to a mesh revision."""
    return (
        isinstance(artifact_version, str) and re.fullmatch(r"[a-f0-9]{16}", artifact_version) is not None
        and isinstance(name, str) and 8 <= len(name) <= 160 and name.isprintable()
        and "/" not in name and "\\" not in name and artifact_version[:8] in name.lower()
    )


def observe_studio_print(name, artifact_version, *, require_started=False):
    if not valid_studio_name(name, artifact_version):
        return None

    def match(connection):
        report = connection.status
        state = _state(report)
        if state in {"UNKNOWN", "IDLE"}:
            return None
        if require_started and (state not in {"PREPARE", "RUNNING", "SLICING"} or report.get("print_error") not in (0, "0")):
            return None
        matching = []
        for field in ("subtask_name", "gcode_file"):
            raw = report.get(field)
            if raw in (None, ""):
                continue
            if not isinstance(raw, str):
                return None
            basename = Path(raw).name
            stem = re.sub(r"(\.gcode\.3mf|\.gcode|\.3mf)$", "", basename, flags=re.I)
            if re.fullmatch(r"plate_\d+|print", stem, re.I):
                continue  # The archive's inner plate does not identify a job.
            if stem != name:
                return None
            matching.append(connection.field_numbers.get(field, 0))
        named_at = max(matching, default=0)
        latest_identity = max(connection.field_numbers.get(field, 0) for field in JOB_FIELDS)
        if not named_at or named_at < latest_identity or named_at > connection.field_numbers.get("gcode_state", 0):
            return None
        progress = {"state": state}
        percent = report.get("mc_percent")
        if type(percent) is int and 0 <= percent <= 100 and connection.field_numbers.get("mc_percent", 0) >= named_at:
            progress["percent"] = percent
        return progress

    return _read_observation(match)


def _read_observation(match):
    with _connect(*_credentials()) as connection:
        connection.request_status()
        result = None

        def matched():
            nonlocal result
            result = match(connection)
            return result is not None

        connection.wait(matched, 8, missing_ok=True)
        return result
