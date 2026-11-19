"""Prepare one small decorative model with local Blender and Bambu Studio."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
SLICER = Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")
PROFILE_DIR = SLICER.parents[1] / "Resources" / "profiles"
PROFILES = {
    "P2S": ("0.12mm High Quality @BBL P2S", "Generic PLA @BBL P2S"),
    "P1S": ("0.12mm Fine @BBL X1C", "Bambu PLA Basic @BBL P1S 0.4 nozzle"),
}
BASELINE_SIDE_MM = 60
DESKTOP_SIDE_MM = 80
SIZE_STEP_MM = 2
MAX_TRIANGLES = 500_000
FORMATS = {".glb", ".stl"}
MODEL_PREVIEW = "model-preview.png"


class PreparationError(RuntimeError):
    pass


@lru_cache(maxsize=96)
def _legacy_usage(path, modified, size):
    with ZipFile(path) as archive:
        member = archive.getinfo("Metadata/slice_info.config")
        if member.file_size > 256 * 1024:
            return None
        plate = ElementTree.fromstring(archive.read(member)).find("plate")
        fields = {item.get("key"): item.get("value") for item in plate.findall("metadata")}
        return int(fields["prediction"]), float(fields["weight"])


def with_filament_usage(report, directory):
    if "filament_grams" in report or report.get("artifact") != "print.gcode.3mf":
        return report
    path = directory / "print.gcode.3mf"
    try:
        stat = path.stat()
        seconds, grams = _legacy_usage(path, stat.st_mtime_ns, stat.st_size)
        if seconds == report.get("estimated_seconds") and math.isfinite(grams) and grams > 0:
            return report | {"filament_grams": grams}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, BadZipFile, ElementTree.ParseError):
        pass
    return report


def size_comparison(dimensions_mm) -> str:
    """Describe the width, depth and height of a finished mesh in ordinary units."""
    if not isinstance(dimensions_mm, (list, tuple)) or len(dimensions_mm) != 3:
        return ""
    if any(type(n) not in (float, int) or not 0 < n <= 10000 for n in dimensions_mm):
        return ""
    width, depth, height = (n / 10 for n in dimensions_mm)
    delta = round(height - 5.4, 1)
    if abs(delta) < 0.1:
        reference = "高度约等于银行卡的短边（5.4 厘米）"
    else:
        direction = "多" if delta > 0 else "少"
        reference = f"高度比银行卡短边（约 5.4 厘米）{direction} {abs(delta):.1f} 厘米"
    return f"宽 {width:.1f} × 深 {depth:.1f} × 高 {height:.1f} 厘米，{reference}"


def _run(args, directory, stage, timeout):
    try:
        environment = {key: value for key, value in os.environ.items() if not key.startswith(("LUX3D_", "BAMBU_"))}
        completed = subprocess.run(
            args, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", timeout=timeout, check=False, env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise PreparationError(f"{stage}超时") from error
    except OSError as error:
        raise PreparationError(f"无法运行{stage}工具") from error
    if completed.returncode:
        log_lines = completed.stdout.strip().splitlines()
        detail = next(
            (line.partition("PreparationError: ")[2] for line in reversed(log_lines)
             if "PreparationError: " in line),
            "\n".join(log_lines[-5:]),
        )
        raise PreparationError(f"{stage}失败。{detail}")


def _run_blender(args, directory, stage, timeout):
    _run(
        [
            BLENDER, "--background", "--factory-startup", "--offline-mode",
            "--disable-autoexec", "--python-exit-code", "1",
            "--python", Path(__file__).resolve(), "--", *args,
        ],
        directory, stage, timeout,
    )


def render_model_preview(stl: Path, output_dir: Path) -> str | None:
    """Render front and three-quarter views of a prepared STL, if available."""
    stl = Path(stl).resolve()
    output_dir = Path(output_dir).resolve()
    if not stl.is_file() or stl.suffix.lower() != ".stl" or not BLENDER.is_file():
        return None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".render-", dir=output_dir) as temporary:
            directory = Path(temporary)
            preview = directory / MODEL_PREVIEW
            _run_blender(["preview", stl, preview], directory, "Blender 模型预览", 45)
            preview.replace(output_dir / MODEL_PREVIEW)
    except (OSError, PreparationError):
        return None
    return MODEL_PREVIEW


def _profile_index():
    catalog = json.loads((PROFILE_DIR / "BBL.json").read_text())
    entries = ("machine_list", "process_list", "filament_list")
    return {
        item["name"]: PROFILE_DIR / "BBL" / item["sub_path"]
        for entry in entries for item in catalog[entry]
    }


def _expand_profile(name, profiles):
    preset = json.loads(profiles[name].read_text())
    parent = preset.pop("inherits", "")
    merged = _expand_profile(parent, profiles) if parent else {}
    for include in preset.pop("include", []):
        template = _expand_profile(include, profiles)
        template.pop("name", None)
        template.pop("instantiation", None)
        merged.update(template)
    merged.update(preset)
    return merged


def _slice(stl, directory, model):
    machine_model = f"Bambu Lab {model}"
    machine_name = f"{machine_model} 0.4 nozzle"
    process_name, material_name = PROFILES[model]
    try:
        profiles = _profile_index()
        machine = _expand_profile(machine_name, profiles)
        process = _expand_profile(process_name, profiles)
        material = _expand_profile(material_name, profiles)
    except (OSError, KeyError, ValueError) as error:
        raise PreparationError("无法读取 Bambu Studio 的内置机型或耗材预设") from error

    process["curr_bed_type"] = "Textured PEI Plate"
    process["enable_support"] = "1"
    process["support_type"] = "tree(auto)"
    for name, preset in (("machine", machine), ("process", process), ("material", material)):
        (directory / f"{name}.json").write_text(json.dumps(preset))

    _run(
        [
            SLICER, "--debug", "2", "--datadir", directory / "settings",
            "--load-settings", "machine.json;process.json",
            "--load-filaments", "material.json", "--check-preset",
            "--outputdir", directory, "--arrange", "1", "--slice", "0",
            "--export-3mf", "print.gcode.3mf", stl,
        ],
        directory, "Bambu Studio 切片", 180,
    )
    return machine_model, process_name, material_name


def _inspect_slice(directory, machine_model, process_name, material):
    try:
        result = json.loads((directory / "result.json").read_text())
        if result["return_code"] != 0 or len(result["sliced_plates"]) != 1:
            raise PreparationError("切片没有产生一张可用的打印板")
        warning = result["sliced_plates"][0]["warning_message"]
        if warning:
            raise PreparationError(f"切片需要检查。{warning}")

        with ZipFile(directory / "print.gcode.3mf") as archive:
            project = json.loads(archive.read("Metadata/project_settings.config"))
            slice_info = ElementTree.fromstring(archive.read("Metadata/slice_info.config"))
            plates = slice_info.findall("./plate")
            if len(plates) != 1:
                raise PreparationError("切片没有产生一张可用的打印板")
            metadata = {item.attrib["key"]: item.attrib["value"] for item in plates[0].findall("metadata")}
            if (
                metadata["outside"] != "false"
                or project["printer_model"] != machine_model
                or project["print_settings_id"] != process_name
                or project["filament_settings_id"] != [material]
                or project["nozzle_diameter"] != ["0.4"]
                or project["curr_bed_type"] != "Textured PEI Plate"
                or str(project["enable_support"]) != "1"
                or project["support_type"] != "tree(auto)"
                or not project["machine_start_gcode"] or not project["machine_end_gcode"]
                or archive.getinfo("Metadata/plate_1.gcode").file_size == 0
            ):
                raise PreparationError("切片产物缺少正确的打印机配置或 G-code")

            layer_height = float(result["layer_height"])
            if not math.isclose(layer_height, 0.12, abs_tol=0.001):
                raise PreparationError("切片没有采用 0.12 mm 层高预设")
            seconds = int(metadata["prediction"])
            if seconds <= 0:
                raise PreparationError("切片缺少有效的时长估算")
            grams = sum(float(f.attrib["used_g"]) for f in plates[0].findall("filament"))
            if not math.isfinite(grams) or grams <= 0:
                raise PreparationError("切片缺少有效的耗材估算")
            with archive.open("Metadata/plate_1.gcode") as gcode:
                fingerprint = hashlib.file_digest(gcode, "md5").hexdigest()
            if fingerprint != archive.read("Metadata/plate_1.gcode.md5").decode("ascii").strip().lower():
                raise PreparationError("切片的 G-code 校验值不匹配")

            (directory / "preview.png").write_bytes(archive.read("Metadata/plate_1.png"))
            first_layer_area = _first_layer_area(archive)
    except (KeyError, OSError, ValueError, BadZipFile, ElementTree.ParseError) as error:
        raise PreparationError("无法读取或验证切片产物") from error

    result = {
        "estimated_seconds": seconds,
        "estimated_minutes": round(seconds / 60, 1),
        "filament_grams": round(grams, 2),
        "gcode_md5": fingerprint,
        "layer_height_mm": round(layer_height, 2),
        "support_used": metadata["support_used"] == "true",
        "bed_type": project["curr_bed_type"],
    }
    if first_layer_area is not None:
        result["first_layer_area_mm2"] = first_layer_area
    return result


def _scale_prepared_stl(source, target, scale):
    """Uniformly scale just the vertex positions in Blender's checked binary STL."""
    face = struct.Struct("<12fH")
    with source.open("rb") as src, target.open("xb") as dest:
        header = src.read(84)
        if len(header) != 84:
            raise PreparationError("无法缩放准备好的 STL")
        count, = struct.unpack_from("<I", header, 80)
        if source.stat().st_size != 84 + count * face.size:
            raise PreparationError("无法缩放准备好的 STL")
        dest.write(header)
        for block in iter(lambda: src.read(face.size * 4096), b""):
            scaled = bytearray(len(block))
            for index, values in enumerate(face.iter_unpack(block)):
                vertices = (coord * scale for coord in values[3:12])
                face.pack_into(scaled, index * face.size, *values[:3], *vertices, values[12])
            dest.write(scaled)


def _fit_print(baseline_stl, directory, model, dimensions, max_minutes):
    """Keep the largest tested desktop size whose validated slice fits the time limit."""
    longest = max(dimensions)
    targets = [float(longest)]
    targets.extend(range((math.floor(round(longest, 2) / SIZE_STEP_MM) + 1) * SIZE_STEP_MM,
                         DESKTOP_SIDE_MM + 1, SIZE_STEP_MM))
    trials = []

    def try_size(index):
        target = targets[index]
        scale = target / longest
        folder = directory / f"size-{index}"
        folder.mkdir()
        mesh = folder / "model.stl"
        if index == 0:
            os.link(baseline_stl, mesh)
        else:
            _scale_prepared_stl(baseline_stl, mesh, scale)
        started = time.monotonic()
        machine, process, material = _slice(mesh, folder, model)
        elapsed = round(time.monotonic() - started, 2)
        checked = _inspect_slice(folder, machine, process, material)
        trial_dimensions = [round(value * scale, 2) for value in dimensions]
        trials.append({
            "dimensions_mm": trial_dimensions, "estimated_seconds": checked["estimated_seconds"],
            "filament_grams": checked["filament_grams"], "slice_elapsed_seconds": elapsed,
        })
        return folder, {
            **checked, "dimensions_mm": trial_dimensions, "material": material,
            "slice_elapsed_seconds": elapsed,
        }

    best_folder, best = try_size(0)
    baseline_seconds = best["estimated_seconds"]
    limit = max_minutes * 60
    if baseline_seconds > limit:
        raise PreparationError(f"基础尺寸预计需要 {math.ceil(baseline_seconds / 60)} 分钟，超过 {max_minutes} 分钟上限")
    low, high = 1, len(targets) - 1
    while low <= high:
        index = (low + high) // 2
        try:
            folder, candidate = try_size(index)
        except PreparationError as error:
            trials.append({"dimensions_mm": [round(v * targets[index] / longest, 2) for v in dimensions],
                           "error": str(error)})
            high = index - 1
            continue
        if candidate["estimated_seconds"] <= limit:
            best_folder, best = folder, candidate
            low = index + 1
        else:
            high = index - 1
    best["sizing"] = {
        "baseline_dimensions_mm": trials[0]["dimensions_mm"], "baseline_estimated_seconds": baseline_seconds,
        "scale_factor": round(max(best["dimensions_mm"]) / longest, 5), "max_minutes": max_minutes,
        "trials": trials,
    }
    return best_folder, best


def _sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _completed_print(output_dir, request):
    if not (output_dir / "print.gcode.3mf").exists():
        return None
    try:
        receipt = json.loads((output_dir / "print-prep.json").read_text())
        if receipt["request"] == request and receipt["print"]["artifact"] == "print.gcode.3mf":
            files = receipt["sha256"]
            if ({"model.stl", "print.gcode.3mf", "preview.png"} <= files.keys()
                    <= {"model.stl", "print.gcode.3mf", "preview.png", MODEL_PREVIEW}
                    and all(_sha256(output_dir / name) == digest for name, digest in files.items())):
                return receipt["print"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    raise PreparationError("此目录已有可打印切片。新版本需要单独的目录。")


@contextmanager
def _publication_lock(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _first_layer_area(archive):
    try:
        objects = json.loads(archive.read("Metadata/plate_1.json"))["bbox_objects"]
        area = objects[0]["area"]
        if len(objects) == 1 and type(area) in (float, int) and math.isfinite(area) and area > 0:
            return round(area, 2)
    except (KeyError, ValueError, TypeError, IndexError, OverflowError, BadZipFile):
        pass
    return None


def prepare_print(source: Path, output_dir: Path, *, model: str, max_minutes: int = 180) -> dict:
    """Write normalized STL, sliced project and plate PNG after preflight succeeds."""
    source = Path(source).resolve()
    output_dir = Path(output_dir).resolve()
    model = model.strip().upper()
    if model not in PROFILES:
        raise PreparationError("切片目前支持拓竹 P1S 或 P2S 的 0.4 mm 喷嘴预设")
    if type(max_minutes) is not int or not 1 <= max_minutes <= 180:
        raise PreparationError("打印时长上限应为 1 至 180 的整数分钟")
    if not source.is_file() or source.suffix.lower() not in FORMATS:
        raise PreparationError("请选择本地 STL 或 GLB 模型文件")
    file_size = source.stat().st_size
    if file_size > 100 * 1024 * 1024:
        raise PreparationError("模型超过 100 MB")
    # Binary STL has one fixed-size record per triangle. Leave ASCII STL to Blender.
    if source.suffix.lower() == ".stl" and file_size > 84 + 50 * MAX_TRIANGLES:
        with source.open("rb") as handle:
            handle.seek(80)
            count, = struct.unpack("<I", handle.read(4))
        if file_size == 84 + 50 * count:
            raise PreparationError("模型超过 50 万个三角面，请使用较低面数的模型")
    output_dir.mkdir(parents=True, exist_ok=True)
    request = {"source_sha256": _sha256(source), "model": model, "max_minutes": max_minutes}
    existing = _completed_print(output_dir, request)
    if existing is not None:
        return existing
    if source == output_dir / "model.stl":
        raise PreparationError("请为切片选择单独的输出目录，以保留原始 STL 模型。")
    if not BLENDER.is_file() or not SLICER.is_file():
        raise PreparationError("需要在此 Mac 安装 Blender 和 Bambu Studio")
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=output_dir) as temporary:
        directory = Path(temporary)
        stl = directory / "model.stl"
        _run_blender([source, stl], directory, "Blender 模型检查", 150)
        dimensions = json.loads((directory / "dimensions.json").read_text())
        chosen, slice_data = _fit_print(stl, directory, model, dimensions, max_minutes)
        files = {"mesh": stl.name, "artifact": "print.gcode.3mf", "preview": "preview.png"}
        preview = render_model_preview(chosen / stl.name, chosen)
        if preview:
            files["model_preview"] = preview
        report = {"model": model, **slice_data, **files}
        fingerprints = {name: _sha256(chosen / name) for name in files.values()}
        report["slice_sha256"] = fingerprints[files["artifact"]]
        receipt = {"request": request, "print": report, "sha256": fingerprints}
        (chosen / "print-prep.json").write_text(json.dumps(receipt, ensure_ascii=False))
        with _publication_lock(output_dir):
            existing = _completed_print(output_dir, request)
            if existing is not None:
                return existing
            for key, name in files.items():
                if key != "artifact":
                    (chosen / name).replace(output_dir / name)
            (chosen / "print-prep.json").replace(output_dir / "print-prep.json")
            os.link(chosen / files["artifact"], output_dir / files["artifact"])
    return report


def _normalize_in_blender(source, stl):
    import bmesh
    import bpy
    from mathutils import Matrix, Vector

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    is_glb = source.suffix.lower() == ".glb"
    if is_glb:
        bpy.ops.import_scene.gltf(filepath=str(source), merge_vertices=True)
    else:
        bpy.ops.wm.stl_import(filepath=str(source))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.data.polygons]
    if not objects:
        raise PreparationError("文件里没有可切片的三维网格")

    triangle_count = sum(len(obj.data.loops) - 2 * len(obj.data.polygons) for obj in objects)
    if triangle_count > MAX_TRIANGLES:
        raise PreparationError("模型超过 50 万个三角面，请使用较低面数的模型")

    # Collect transformed instances directly in Blender's native mesh storage.
    # Shared meshes need a private copy because each instance has its own transform.
    mesh = bmesh.new()
    for obj in objects:
        data = obj.data.copy() if obj.data.users > 1 else obj.data
        data.transform(obj.matrix_world)
        mesh.from_mesh(data)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.data.orphans_purge(do_recursive=True)

    low = [math.inf] * 3
    high = [-math.inf] * 3
    for vertex in mesh.verts:
        for axis, value in enumerate(vertex.co):
            if not math.isfinite(value):
                raise PreparationError("模型包含异常坐标")
            low[axis] = min(low[axis], value)
            high[axis] = max(high[axis], value)
    low, high = Vector(low), Vector(high)
    size = high - low
    if min(size) <= 0:
        raise PreparationError("模型缺少三维厚度")
    scale = min(1000 if is_glb else 1, BASELINE_SIDE_MM / max(size))
    dimensions = [axis * scale for axis in size]
    if min(dimensions) < 3:
        raise PreparationError("模型尺寸过薄，请用更厚的底座或主体")

    center = (low + high) / 2
    center.z = low.z
    mesh.transform(Matrix.Translation(-center))
    mesh.transform(Matrix.Scale(scale, 4))
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=0.0001)
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    if not mesh.faces or any(not edge.is_manifold or not edge.is_contiguous for edge in mesh.edges):
        raise PreparationError("网格存在开口、重叠边或破面，需要重新生成")

    for face in mesh.faces:
        face.tag = False
    first = next(iter(mesh.faces))
    first.tag = True
    remaining = [first]
    visited = 0
    while remaining:
        face = remaining.pop()
        visited += 1
        for loop in face.loops:
            neighbor = loop.link_loop_radial_next.face
            if not neighbor.tag:
                neighbor.tag = True
                remaining.append(neighbor)
    if visited != len(mesh.faces) or mesh.calc_volume() < 1:
        raise PreparationError("小物件需要是一个连在一起的立体模型")

    data = bpy.data.meshes.new("Print mesh")
    mesh.to_mesh(data)
    mesh.free()
    obj = bpy.data.objects.new("Print model", data)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.stl_export(filepath=str(stl), export_selected_objects=True)
    stl.with_name("dimensions.json").write_text(json.dumps(dimensions))


def _render_in_blender(stl, output):
    import bpy
    from mathutils import Matrix, Vector

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.wm.stl_import(filepath=str(stl))
    front = bpy.context.selected_objects[0]
    side = front.copy()
    bpy.context.collection.objects.link(side)
    for polygon in front.data.polygons:
        polygon.use_smooth = True

    angles = (
        (front, Matrix.Rotation(0.10, 4, "X")),
        (side, Matrix.Rotation(0.31, 4, "X") @ Matrix.Rotation(-0.63, 4, "Z")),
    )
    views = []
    for obj, rotation in angles:
        points = [rotation @ vertex.co for vertex in obj.data.vertices]
        low = Vector(min(point[axis] for point in points) for axis in range(3))
        high = Vector(max(point[axis] for point in points) for axis in range(3))
        views.append((obj, rotation, (low + high) / 2, high - low))

    width, height = 1440, 880
    gap = max(max(size) for _, _, _, size in views) * 0.14
    half_spacing = (sum(size.x for _, _, _, size in views) / 2 + gap) / 2
    for (obj, rotation, center, _), x in zip(views, (-half_spacing, half_spacing)):
        obj.matrix_world = Matrix.Translation(Vector((x, 0, 0)) - center) @ rotation

    scene = bpy.context.scene
    camera = bpy.data.cameras.new("Model preview")
    camera.type = "ORTHO"
    combined_width = half_spacing * 2 + max(size.x for _, _, _, size in views)
    fitted_height = max(size.z for _, _, _, size in views) * width / height
    camera.ortho_scale = max(combined_width, fitted_height) * 1.20
    camera_obj = bpy.data.objects.new("Model preview", camera)
    bpy.context.collection.objects.link(camera_obj)
    camera_obj.location = (0, -220, 0)
    camera_obj.rotation_euler = (math.pi / 2, 0, 0)
    scene.camera = camera_obj

    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.studio_light = "paint.sl"
    shading.color_type = "SINGLE"
    shading.single_color = (0.62, 0.59, 0.55)
    shading.show_specular_highlight = False
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    shading.cavity_ridge_factor = 0.8
    shading.cavity_valley_factor = 0.85
    shading.curvature_ridge_factor = 0.45
    shading.curvature_valley_factor = 0.65
    scene.display.render_aa = "16"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__" and "--" in sys.argv:
    args = sys.argv[sys.argv.index("--") + 1:]
    if args[0] == "preview":
        _render_in_blender(*(Path(arg) for arg in args[1:]))
    else:
        _normalize_in_blender(*(Path(arg) for arg in args))
