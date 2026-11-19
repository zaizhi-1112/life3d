"""Decimate a local mesh for the island. Pass --color to keep its base colors."""

import argparse
from array import array
from math import cos, sin, sqrt
from pathlib import Path
import sys

import bpy


parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
parser.add_argument("--color", action="store_true")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
if args.color and args.source.suffix.lower() != ".glb":
    raise ValueError("A colored exhibit needs a material-bearing GLB")
bpy.ops.wm.read_factory_settings(use_empty=True)
if args.source.suffix.lower() == ".glb":
    bpy.ops.import_scene.gltf(filepath=str(args.source), import_pack_images=False)
else:
    bpy.ops.wm.stl_import(filepath=str(args.source))


def retain_base_color(material, resized):
    """Keep original color/alpha, UV transforms and material slots; omit PBR map sets."""
    if not material or not material.node_tree:
        return
    tree = material.node_tree
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            for socket in node.inputs:
                if socket.name not in ("Base Color", "Alpha"):
                    for link in list(socket.links):
                        tree.links.remove(link)
            node.inputs["Roughness"].default_value = 0.84
            node.inputs["Metallic"].default_value = 0.0
        elif node.type == "GROUP" and node.inputs.get("Occlusion"):
            for link in list(node.inputs["Occlusion"].links):
                tree.links.remove(link)

    # Walk the upstream color graph instead of decoding every large source map.
    queue = [(link.from_node, channel) for node in tree.nodes if node.type == "BSDF_PRINCIPLED"
             for channel in ("Base Color", "Alpha") for link in node.inputs[channel].links]
    visited = set()
    base_node = None
    while queue:
        node, channel = queue.pop()
        if (node, channel) in visited:
            continue
        visited.add((node, channel))
        if node.type == "TEX_IMAGE" and node.image:
            if channel == "Base Color":
                base_node = node
            if node.image not in resized:
                img = node.image
                width, height = img.size
                if min(width, height) < 1:
                    raise ValueError("Base color texture cannot be read")
                if max(width, height) > 512:
                    scale = 512 / max(width, height)
                    img.scale(max(1, round(width * scale)), max(1, round(height * scale)))
                    img.update()
                resized.add(img)
        queue.extend((link.from_node, channel) for socket in node.inputs for link in socket.links)
    return base_node


def has_surface_color(mesh, base_nodes):
    """Reject grayscale albedos, including atlases colored only outside the UV islands."""
    # Blender exposes scene-linear pixels. Judge chroma in displayed sRGB.
    def displayed(linear):
        return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055

    mesh.calc_loop_triangles()
    total_area = sum(tri.area for tri in mesh.loop_triangles)
    if total_area <= 0:
        return False
    colored_area = 0.0
    for material_index, material in enumerate(mesh.materials):
        node = base_nodes.get(material)
        if node is None:
            continue
        uv_layer = mesh.uv_layers.active
        vector = node.inputs["Vector"]
        offset_x = offset_y = rotation = 0.0
        scale_x = scale_y = 1.0
        if vector.is_linked and vector.links[0].from_node.type == "MAPPING":
            mapping = vector.links[0].from_node
            offset_x, offset_y = mapping.inputs["Location"].default_value[:2]
            rotation = mapping.inputs["Rotation"].default_value.z
            scale_x, scale_y = mapping.inputs["Scale"].default_value[:2]
            vector = mapping.inputs["Vector"]
        if vector.is_linked and vector.links[0].from_node.type == "UVMAP":
            uv_layer = mesh.uv_layers.get(vector.links[0].from_node.uv_map) or uv_layer
        if uv_layer is None:
            continue
        image = node.image
        width, height = image.size
        pixels = array("f", [0.0]) * len(image.pixels)
        image.pixels.foreach_get(pixels)
        cosine, sine = cos(rotation), sin(rotation)
        for tri in mesh.loop_triangles:
            if tri.material_index != material_index:
                continue
            corners = [uv_layer.data[loop].uv for loop in tri.loops]
            # A large flat panel can carry a tiny painted motif away from its
            # center. Give it more area samples than a small beveled triangle.
            count = max(1, round(4096 * tri.area / total_area))
            for sample in range(count):
                weights = (1/3, 1/3, 1/3)
                if count > 1:
                    radius = sqrt((sample + 0.5) / count)
                    angle = (0.5 + sample * 0.61803398875) % 1
                    weights = (1 - radius, radius * (1 - angle), radius * angle)
                u = sum(p.x * a for p, a in zip(corners, weights)) * scale_x
                v = sum(p.y * a for p, a in zip(corners, weights)) * scale_y
                s = cosine * u - sine * v + offset_x
                t = sine * u + cosine * v + offset_y
                if node.extension == "REPEAT":
                    s, t = s % 1, t % 1
                x = min(width - 1, max(0, int(s * width)))
                y = min(height - 1, max(0, int(t * height)))
                index = image.channels * (y * width + x)
                if image.channels == 4 and pixels[index + 3] < 0.1:
                    continue
                rgb = pixels[index:index + 3]
                high = displayed(max(rgb))
                if high - displayed(min(rgb)) > max(0.06, 0.10 * high):
                    colored_area += tri.area / count
                    if colored_area >= 0.002 * total_area:
                        return True
    return False


meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not meshes:
    raise ValueError("Source contains no mesh")
# Baking the existing hierarchy keeps the original model's scale and orientation.
for obj in meshes:
    transform = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = transform
    if not args.color:
        obj.data.materials.clear()

if args.color:
    resized = set()
    materials = {mat for obj in meshes for mat in obj.data.materials if mat}
    base_nodes = {material: retain_base_color(material, resized) for material in materials}
    if not any(base_nodes.values()) or not any(obj.data.uv_layers for obj in meshes):
        raise ValueError("Color exhibit has no usable base color texture or UV map")

bpy.ops.object.select_all(action="DESELECT")
for obj in meshes:
    obj.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
# glTF may split vertices at seams. UVs live on face corners, preserving a
# chart boundary while merging geometrically coincident vertices.
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.0000001)
bpy.ops.object.mode_set(mode="OBJECT")
obj.data.calc_loop_triangles()
faces = len(obj.data.loop_triangles)
if faces > 14000:
    decimate = obj.modifiers.new("Display mesh", "DECIMATE")
    decimate.ratio = 14000 / faces
    bpy.ops.object.modifier_apply(modifier=decimate.name)
if args.color and not has_surface_color(obj.data, base_nodes):
    raise ValueError("Base color is neutral across the textured surface; keep the previous edition")
bpy.ops.export_scene.gltf(filepath=str(args.destination), export_format="GLB",
                          use_selection=True, export_materials="EXPORT" if args.color else "NONE",
                          export_image_format="WEBP" if args.color else "NONE", export_image_quality=84,
                          export_texcoords=args.color, export_tangents=False,
                          export_attributes=False, export_animations=False,
                          export_skins=False, export_morph=False)
if not 32 < args.destination.stat().st_size <= 2_000_000:
    raise ValueError("Display mesh exceeds file budget")
