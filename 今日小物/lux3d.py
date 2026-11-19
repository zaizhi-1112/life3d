"""Resume Lux3D concept image and model jobs and download their results."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import struct
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_GATEWAY = "https://api.aholo.cn"
GATEWAYS = {DEFAULT_GATEWAY, "https://api.aholo3d.cn"}
ARTIFACT_DOMAINS = ("kujiale.com", "aholo.cn", "aholo3d.cn", "aholo.ai")
MAX_API_BYTES = 1 << 20
MAX_MODEL_BYTES = 96 << 20
MAX_CONCEPT_BYTES = 16 << 20
POLL_LIMIT_SECONDS = 20 * 60
DOWNLOAD_LIMIT_SECONDS = 3 * 60
CREATE_UNKNOWN = "Lux3D 可能已接单。请先在 Aholo 的任务历史中核对，再恢复这个任务。"
G1_OPTIONS = {"version": "G1", "outputFormat": ["zip", "glb"], "aiPredictSize": False}


class Lux3DError(RuntimeError):
    """A message safe to display to the user."""


class _ResponseError(Lux3DError):
    def __init__(self, action: str, status: int):
        self.status = status
        super().__init__(f"Lux3D {action}失败（HTTP {status}）。")


class _ConnectionError(Lux3DError):
    """A request whose response was lost during transport."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _task_id(value):
    return type(value) is int and 0 < value < 2**63


def _send(opener, request: Request, action: str):
    try:
        with opener.open(request, timeout=30) as response:
            payload = response.read(MAX_API_BYTES + 1)
        if len(payload) > MAX_API_BYTES:
            raise Lux3DError(f"Lux3D {action}返回的数据超过预期大小。")
        result = json.loads(payload)
    except HTTPError as error:
        error.close()
        raise _ResponseError(action, error.code) from None
    except (OSError, URLError, http.client.HTTPException):
        raise _ConnectionError(f"Lux3D {action}时连接中断。") from None
    except ValueError:
        raise Lux3DError(f"Lux3D {action}未收到可用回复。") from None
    if not isinstance(result, dict):
        raise Lux3DError(f"Lux3D {action}返回了无法识别的数据。")
    return result


def _create(opener, gateway, api_key, endpoint, payload, job, checkpoint):
    is_concept = endpoint == "multimodal-to-image"
    id_field = "lux3d_concept_task_id" if is_concept else "lux3d_task_id"
    pending_field = "lux3d_concept_create_pending" if is_concept else "lux3d_create_pending"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        gateway + f"/lux3d/v1/generate/{endpoint}/task/create",
        data=data,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
    )
    job["lux3d_gateway"] = gateway
    job[pending_field] = True
    checkpoint()
    try:
        result = _send(opener, request, "提交任务")
    except _ResponseError as error:
        if error.status != 401:
            raise Lux3DError(CREATE_UNKNOWN) from None
        job[pending_field] = False
        checkpoint()
        raise Lux3DError("Lux3D 未通过鉴权。请核对中国区 API Key。") from None
    except Lux3DError:
        raise Lux3DError(CREATE_UNKNOWN) from None

    code = result.get("c")
    task_id = result.get("d")
    if code == "0" and _task_id(task_id):
        job[id_field] = task_id
        job[pending_field] = False
        checkpoint()
        return task_id
    if task_id is None and code in ("-1", "GENERATION_CONCURRENCY_LIMIT_EXCEEDED"):
        job[pending_field] = False
        checkpoint()
        if code == "-1":
            raise Lux3DError("Lux3D 拒绝了生成请求。请核对账户额度和生成参数。")
        raise Lux3DError("Lux3D 并发任务已满。等其他任务结束后可以重试。")
    raise Lux3DError(CREATE_UNKNOWN)


def _poll(opener, gateway, api_key, task_id, *, index, artifact):
    request = Request(
        gateway + f"/lux3d/v1/generate/task/get?taskid={task_id}",
        headers={"Authorization": api_key},
    )
    deadline = time.monotonic() + POLL_LIMIT_SECONDS
    failures = 0
    while time.monotonic() < deadline:
        try:
            result = _send(opener, request, "查询任务")
        except (_ConnectionError, _ResponseError) as error:
            # Only queries about an existing task can be repeated automatically.
            temporary = isinstance(error, _ConnectionError) or error.status in (408, 429, 500, 502, 503, 504)
            if not temporary or failures >= 2:
                raise Lux3DError(f"{error}重试会继续查询原任务。") from None
            failures += 1
            time.sleep(min(5 * failures, max(0, deadline - time.monotonic())))
            continue
        failures = 0
        task = result.get("d")
        if result.get("c") != "0" or not isinstance(task, dict):
            raise Lux3DError("Lux3D 暂未返回任务详情。重试会继续查询原任务。")
        if task.get("taskId", task_id) != task_id:
            raise Lux3DError("Lux3D 返回的任务编号与本地记录不一致。")
        status = task.get("status")
        if status == 3:
            outputs = task.get("outputs")
            if isinstance(outputs, list) and len(outputs) > index and isinstance(outputs[index], dict):
                return _artifact_url(outputs[index].get("content"))
            raise Lux3DError(f"Lux3D 已完成任务，回复中缺少{artifact}。")
        if status in (4, 6):
            raise Lux3DError("Lux3D 生成失败或任务已取消。可在 Aholo 的任务历史中核对。")
        if status not in (0, 1):
            raise Lux3DError("Lux3D 返回了无法识别的任务状态。")
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise Lux3DError("Lux3D 仍在生成。重试会继续查询原任务。")


def _artifact_url(value):
    if not isinstance(value, str) or any(char.isspace() or char == "\\" or ord(char) < 32 for char in value):
        raise Lux3DError("Lux3D 未返回可用的下载地址。")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise Lux3DError("Lux3D 未返回可用的下载地址。") from None
    host = url.hostname or ""
    trusted = any(host == domain or host.endswith("." + domain) for domain in ARTIFACT_DOMAINS)
    if url.scheme != "https" or not trusted or url.username is not None or port not in (None, 443) or url.fragment:
        raise Lux3DError("Lux3D 下载地址不属于受信任的 HTTPS 域名。")
    return value


def _is_glb(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if not 20 < size <= MAX_MODEL_BYTES:
            return False
        with path.open("rb") as model:
            magic, version, byte_count = struct.unpack("<4sII", model.read(12))
            if magic != b"glTF" or version != 2 or byte_count != size:
                return False
            while model.tell() < size:
                first = model.tell() == 12
                length, kind = struct.unpack("<I4s", model.read(8))
                if first and (kind != b"JSON" or not length):
                    return False
                if length % 4 or length > size - model.tell():
                    return False
                model.seek(length, os.SEEK_CUR)
            return True
    except (OSError, struct.error):
        return False


def _concept_format(path: Path):
    try:
        if not 24 < path.stat().st_size <= MAX_CONCEPT_BYTES:
            return None
        with path.open("rb") as file:
            header = file.read(24)
            if header.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"):
                width, height = struct.unpack(">II", header[16:24])
                file.seek(-12, os.SEEK_END)
                if 0 < width <= 8192 and 0 < height <= 8192 and file.read() == b"\0\0\0\0IEND\xaeB`\x82":
                    return ".png"
            if header.startswith(b"\xff\xd8\xff"):
                file.seek(-2, os.SEEK_END)
                if file.read() == b"\xff\xd9":
                    return ".jpg"
    except OSError:
        pass
    return None


def _download(opener, url, temporary: Path, *, byte_limit, artifact):
    request = Request(url)
    deadline = time.monotonic() + DOWNLOAD_LIMIT_SECONDS
    try:
        with opener.open(request, timeout=30) as response:
            content_length = response.headers.get("Content-Length")
            size = int(content_length) if content_length is not None else None
            if size is not None and not 0 < size <= byte_limit:
                raise Lux3DError(f"Lux3D {artifact}大小超过限制，无法继续处理。")
            received = 0
            with temporary.open("wb") as file:
                while chunk := response.read(256 * 1024):
                    received += len(chunk)
                    if received > byte_limit:
                        raise Lux3DError(f"Lux3D {artifact}大小超过限制，无法继续处理。")
                    if time.monotonic() >= deadline:
                        raise Lux3DError(f"Lux3D {artifact}下载超时。重试会继续使用原任务。")
                    file.write(chunk)
        if size is not None and size != received:
            raise Lux3DError(f"Lux3D {artifact}未下载完整。重试会继续使用原任务。")
    except HTTPError as error:
        error.close()
        raise Lux3DError(f"Lux3D {artifact}下载失败（HTTP {error.code}）。重试会继续使用原任务。") from None
    except (OSError, URLError, http.client.HTTPException, ValueError):
        raise Lux3DError(f"Lux3D {artifact}下载或保存失败。重试会继续使用原任务。") from None


def _concept_url(opener, gateway, api_key, prompt, output_dir, job, checkpoint):
    task_id = job.get("lux3d_concept_task_id")
    if task_id is None:
        task_id = _create(opener, gateway, api_key, "multimodal-to-image", {"prompt": prompt}, job, checkpoint)
    url = _poll(opener, gateway, api_key, task_id, index=0, artifact="参考图")
    filename = job.get("lux3d_concept_filename")
    if filename in ("concept.png", "concept.jpg") and _concept_format(output_dir / filename):
        return url
    temporary = output_dir / "concept.part"
    _download(opener, url, temporary, byte_limit=MAX_CONCEPT_BYTES, artifact="参考图")
    extension = _concept_format(temporary)
    if extension is None:
        raise Lux3DError("Lux3D 下载的参考图不符合 PNG 或 JPEG 格式，或未下载完整。")
    filename = "concept" + extension
    temporary.replace(output_dir / filename)
    job["lux3d_concept_filename"] = filename
    checkpoint()
    return url


def generate_model(
    prompt: str,
    output_dir: Path,
    *,
    job: dict,
    checkpoint: Callable[[], None],
    concept_prompt: str | None = None,
) -> Path:
    """Generate one model per job. The caller serializes jobs and persists checkpoints atomically."""
    task_id = job.get("lux3d_task_id")
    if task_id is not None and not _task_id(task_id):
        raise Lux3DError("本地保存的 Lux3D 任务编号无效。请先核对任务历史。")
    if task_id is None and job.get("lux3d_create_pending"):
        raise Lux3DError(CREATE_UNKNOWN)
    concept_id = job.get("lux3d_concept_task_id")
    if task_id is None and concept_id is not None and not _task_id(concept_id):
        raise Lux3DError("本地保存的 Lux3D 参考图任务编号无效。请先核对任务历史。")
    if task_id is None and concept_id is None and job.get("lux3d_concept_create_pending"):
        raise Lux3DError(CREATE_UNKNOWN)
    output_dir.mkdir(parents=True, exist_ok=True)
    model = output_dir / "model.glb"
    if task_id is not None and _is_glb(model):
        return model

    gateway = os.environ.get("LUX3D_BASE_URL", DEFAULT_GATEWAY).rstrip("/")
    if gateway not in GATEWAYS:
        raise Lux3DError("LUX3D_BASE_URL 需要填写 Aholo 官方中国区网关。")
    if (task_id is not None or concept_id is not None) and job.get("lux3d_gateway", gateway) != gateway:
        raise Lux3DError("请使用创建任务时的 Lux3D 网关继续查询。")
    api_key = os.environ.get("LUX3D_API_KEY", "").strip()
    if not api_key or any(not 33 <= ord(char) <= 126 for char in api_key):
        raise Lux3DError("请在本机配置有效的 LUX3D_API_KEY。")

    opener = build_opener(_NoRedirect())
    if task_id is None:
        if concept_prompt is not None or concept_id is not None:
            if concept_id is None and not concept_prompt.strip():
                raise Lux3DError("请提供参考图造型描述。")
            url = _concept_url(opener, gateway, api_key, concept_prompt, output_dir, job, checkpoint)
            task_id = _create(opener, gateway, api_key, "img-to-3d", {"img": url, **G1_OPTIONS}, job, checkpoint)
        else:
            if not prompt.strip():
                raise Lux3DError("请提供摆件造型描述。")
            payload = {"prompt": prompt, "style": "photorealistic", **G1_OPTIONS}
            task_id = _create(opener, gateway, api_key, "text-to-3d", payload, job, checkpoint)
    # G1 always returns the ZIP in slot 1 and the GLB in slot 2.
    model_url = _poll(opener, gateway, api_key, task_id, index=1, artifact="GLB 模型")
    temporary = model.with_suffix(".glb.part")
    _download(opener, model_url, temporary, byte_limit=MAX_MODEL_BYTES, artifact="模型")
    if not _is_glb(temporary):
        raise Lux3DError("Lux3D 下载的文件不符合 GLB 格式或未下载完整。")
    temporary.replace(model)
    return model
