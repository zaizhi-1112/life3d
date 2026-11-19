"""Build the island's free props in Blender and export one GLB each.

    /Applications/Blender.app/Contents/MacOS/Blender -b -P tools/blender/make_props.py -- assets/
    (add `--preview` to also render a PNG contact image next to every GLB)

Materials named "roof", "glow" and "window" are recoloured in the browser.
"""
import math
import random
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(args[0]).resolve()
PREVIEW = "--preview" in args
OUT.mkdir(parents=True, exist_ok=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, color, rough=0.8, emit=None, strength=0.0):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        tree.nodes.clear()
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*emit, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    mat.diffuse_color = (*color, 1)
    return mat


def srgb(hex_):
    h = hex_.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def smooth(obj, on=True):
    for p in obj.data.polygons:
        p.use_smooth = on


def add(kind, **kw):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(**kw)
    return bpy.context.active_object


def bevel(obj, width=0.03, segments=2):
    m = obj.modifiers.new("bevel", "BEVEL")
    m.width, m.segments = width, segments
    m.limit_method = "ANGLE"


def jitter(obj, amount, seed):
    rnd = random.Random(seed)
    for v in obj.data.vertices:
        v.co += Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))) * amount


def export(name):
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.type == "MESH")
        bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")  # applies modifiers
    path = OUT / f"{name}.glb"
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                              export_apply=True, export_texcoords=False, export_tangents=False,
                              export_animations=False)
    print("exported", path.name, path.stat().st_size)
    if PREVIEW:
        render_preview(name)


def render_preview(name):
    scene = bpy.context.scene
    objs = [o for o in scene.objects if o.type == "MESH"]
    lo = Vector((min(v[0] for o in objs for v in o.bound_box), min(v[1] for o in objs for v in o.bound_box), 0))
    hi = Vector((max(v[0] for o in objs for v in o.bound_box), max(v[1] for o in objs for v in o.bound_box), max(v[2] for o in objs for v in o.bound_box)))
    size = max((hi - lo).length, 0.5)
    center = (lo + hi) / 2
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = center + Vector((size * 1.1, -size * 1.5, size * 0.9))
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.35, 0.3, 0.38, 1)
    scene.world = world
    scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = scene.render.resolution_y = 420
    scene.render.filepath = str(OUT / "_preview" / f"{name}.png")
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------- props
class _M:
    def __getattr__(self, key):
        return SPECS[key]()


SPECS = {
    "LEAF": lambda: material("leaf", srgb("#6f8f5c"), 0.9),
    "LEAF2": lambda: material("leaf_dark", srgb("#4d6b4f"), 0.9),
    "LEAF3": lambda: material("leaf_autumn", srgb("#c28a4a"), 0.9),
    "BARK": lambda: material("bark", srgb("#6b4b3a"), 0.95),
    "STONE": lambda: material("stone", srgb("#9a9087"), 0.95),
    "WOOD": lambda: material("wood", srgb("#8a6447"), 0.8),
    "WOOD_DARK": lambda: material("wood_dark", srgb("#4a372d"), 0.8),
    "WALL": lambda: material("wall", srgb("#efe4d0"), 0.9),
    "ROOF": lambda: material("roof", srgb("#ffffff"), 0.75),
    "WINDOW": lambda: material("window", srgb("#ffd08a"), 0.4, srgb("#ffb85e"), 3.0),
    "GLOW": lambda: material("glow", srgb("#fff2dc"), 0.3, srgb("#ffe2b0"), 2.0),
    "GRASS": lambda: material("grass", srgb("#8fa365"), 0.95),
    "METAL": lambda: material("metal", srgb("#3a3330"), 0.5),
}
M = _M()


def tree_round(name, leaf, seed):
    reset()
    leaf = getattr(M, leaf)
    rnd = random.Random(seed)
    trunk = add("cylinder", vertices=8, radius=0.09, depth=1.1, location=(0, 0, 0.55))
    for v in trunk.data.vertices:
        if v.co.z > 0:
            v.co.x *= 0.65
            v.co.y *= 0.65
    assign(trunk, M.BARK)
    for i in range(4):
        r = rnd.uniform(0.38, 0.55)
        blob = add("ico_sphere", subdivisions=2, radius=r,
                   location=(rnd.uniform(-0.25, 0.25), rnd.uniform(-0.25, 0.25), 1.15 + rnd.uniform(0, 0.45)))
        jitter(blob, 0.05, seed + i)
        assign(blob, leaf)
        smooth(blob, False)
    export(name)


def tree_pine(name, seed):
    reset()
    trunk = add("cylinder", vertices=7, radius=0.07, depth=0.5, location=(0, 0, 0.25))
    assign(trunk, M.BARK)
    for i, (r, z) in enumerate([(0.62, 0.65), (0.48, 1.05), (0.34, 1.42), (0.2, 1.74)]):
        cone = add("cone", vertices=9, radius1=r, radius2=0.02, depth=0.7, location=(0, 0, z))
        cone.rotation_euler.z = i * 0.6
        jitter(cone, 0.025, seed + i)
        assign(cone, M.LEAF2)
    export(name)


def rock(name, seed, squash=0.6):
    reset()
    obj = add("ico_sphere", subdivisions=2, radius=0.5, location=(0, 0, 0.18))
    obj.scale = (1.0, 0.8, squash)
    jitter(obj, 0.08, seed)
    assign(obj, M.STONE)
    smooth(obj, False)
    export(name)


def grass(name, seed):
    reset()
    rnd = random.Random(seed)
    for i in range(14):
        a, r = rnd.uniform(0, math.tau), rnd.uniform(0, 0.18)
        blade = add("cone", vertices=3, radius1=0.025, radius2=0, depth=rnd.uniform(0.22, 0.42),
                    location=(math.cos(a) * r, math.sin(a) * r, 0.15))
        blade.rotation_euler = (rnd.uniform(-0.35, 0.35), rnd.uniform(-0.35, 0.35), rnd.uniform(0, 3))
        assign(blade, M.GRASS)
    export(name)


def flowers(name, seed):
    reset()
    rnd = random.Random(seed)
    colors = [material("petal_white", srgb("#f4efe6"), 0.6), material("petal_pink", srgb("#e7a3a0"), 0.6),
              material("petal_yellow", srgb("#f0c96a"), 0.6), material("petal_lilac", srgb("#b8a2d6"), 0.6)]
    for i in range(9):
        a, r = rnd.uniform(0, math.tau), rnd.uniform(0, 0.22)
        x, y, h = math.cos(a) * r, math.sin(a) * r, rnd.uniform(0.18, 0.34)
        stem = add("cylinder", vertices=4, radius=0.008, depth=h, location=(x, y, h / 2))
        assign(stem, M.GRASS)
        head = add("ico_sphere", subdivisions=1, radius=0.035, location=(x, y, h))
        assign(head, colors[rnd.randrange(len(colors))])
    for i in range(6):
        a = rnd.uniform(0, math.tau)
        leaf = add("cone", vertices=3, radius1=0.03, radius2=0, depth=0.18, location=(math.cos(a) * 0.1, math.sin(a) * 0.1, 0.07))
        leaf.rotation_euler = (rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5), a)
        assign(leaf, M.GRASS)
    export(name)


def cottage(name, chimney=True):
    """Footprint ~1.2 x 1.0, door faces +Y in Blender (→ +Z in three.js)."""
    reset()
    base = add("cube", size=1, location=(0, 0, 0.42))
    base.scale = (1.2, 1.0, 0.84)
    bpy.ops.object.transform_apply(scale=True)
    bevel(base, 0.025)
    assign(base, M.WALL)
    plinth = add("cube", size=1, location=(0, 0, 0.05))
    plinth.scale = (1.28, 1.08, 0.1)
    assign(plinth, M.STONE)
    # 双坡屋顶：三棱柱，两侧出檐
    mesh = bpy.data.meshes.new("roof")
    w, d, h, z0 = 0.74, 0.62, 0.55, 0.84
    verts = [(-w, -d, z0), (w, -d, z0), (w, d, z0), (-w, d, z0), (-w, 0, z0 + h), (w, 0, z0 + h)]
    faces = [(0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5), (0, 3, 2, 1)]
    mesh.from_pydata(verts, [], faces)
    roof = bpy.data.objects.new("roof", mesh)
    bpy.context.collection.objects.link(roof)
    bpy.context.view_layer.objects.active = roof
    sol = roof.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = 0.06
    assign(roof, M.ROOF)
    gable = bpy.data.meshes.new("gable")
    gw = 0.6
    gable.from_pydata([(-gw, -0.5, z0), (gw, -0.5, z0), (gw, 0.5, z0), (-gw, 0.5, z0), (-gw, 0, z0 + h * 0.86), (gw, 0, z0 + h * 0.86)],
                      [], [(0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5)])
    g = bpy.data.objects.new("gable", gable)
    bpy.context.collection.objects.link(g)
    assign(g, M.WALL)
    door = add("cube", size=1, location=(-0.25, 0.505, 0.3))
    door.scale = (0.26, 0.04, 0.46)
    bevel(door, 0.02)
    assign(door, M.WOOD)
    for x in (0.25,):
        frame = add("cube", size=1, location=(x, 0.505, 0.5))
        frame.scale = (0.3, 0.04, 0.28)
        assign(frame, M.WOOD_DARK)
        pane = add("cube", size=1, location=(x, 0.53, 0.5))
        pane.scale = (0.22, 0.02, 0.2)
        assign(pane, M.WINDOW)
    side = add("cube", size=1, location=(0.605, 0, 0.5))
    side.scale = (0.02, 0.24, 0.2)
    assign(side, M.WINDOW)
    step = add("cube", size=1, location=(-0.25, 0.6, 0.03))
    step.scale = (0.4, 0.2, 0.06)
    assign(step, M.STONE)
    if chimney:
        c = add("cube", size=1, location=(0.42, -0.2, 1.25))
        c.scale = (0.16, 0.16, 0.5)
        assign(c, M.STONE)
    export(name)


def lantern(name):
    """Month lamp: wooden post with hanging lantern; the 'glow' glass is recoloured per month."""
    reset()
    post = add("cylinder", vertices=8, radius=0.05, depth=1.7, location=(0, 0, 0.85))
    assign(post, M.WOOD_DARK)
    foot = add("cylinder", vertices=8, radius=0.12, depth=0.1, location=(0, 0, 0.05))
    assign(foot, M.STONE)
    arm = add("cube", size=1, location=(0.17, 0, 1.66))
    arm.scale = (0.36, 0.04, 0.04)
    assign(arm, M.WOOD_DARK)
    hook = add("cylinder", vertices=6, radius=0.008, depth=0.12, location=(0.3, 0, 1.58))
    assign(hook, M.METAL)
    cap = add("cone", vertices=4, radius1=0.12, radius2=0.02, depth=0.08, location=(0.3, 0, 1.5))
    cap.rotation_euler.z = math.pi / 4
    assign(cap, M.METAL)
    glass = add("cube", size=1, location=(0.3, 0, 1.38))
    glass.scale = (0.13, 0.13, 0.17)
    assign(glass, M.GLOW)
    base = add("cube", size=1, location=(0.3, 0, 1.285))
    base.scale = (0.15, 0.15, 0.025)
    assign(base, M.METAL)
    export(name)


def bench(name):
    reset()
    for y in (-0.08, 0.06):
        s = add("cube", size=1, location=(0, y, 0.42))
        s.scale = (1.2, 0.12, 0.04)
        bevel(s, 0.01)
        assign(s, M.WOOD)
    back = add("cube", size=1, location=(0, -0.17, 0.66))
    back.scale = (1.2, 0.04, 0.2)
    bevel(back, 0.01)
    assign(back, M.WOOD)
    for x in (-0.5, 0.5):
        leg = add("cube", size=1, location=(x, -0.02, 0.2))
        leg.scale = (0.06, 0.3, 0.4)
        assign(leg, M.METAL)
    export(name)


def fence(name):
    reset()
    for x in (-0.6, 0, 0.6):
        p = add("cube", size=1, location=(x, 0, 0.3))
        p.scale = (0.07, 0.07, 0.6)
        bevel(p, 0.01)
        assign(p, M.WOOD)
    for z in (0.22, 0.45):
        r = add("cube", size=1, location=(0, 0, z))
        r.scale = (1.3, 0.04, 0.06)
        assign(r, M.WOOD)
    export(name)


def boat(name):
    reset()
    hull = add("uv_sphere", segments=16, ring_count=8, radius=0.5, location=(0, 0, 0.12))
    hull.scale = (1.6, 0.55, 0.45)
    bpy.ops.object.transform_apply(scale=True)
    bm = bmesh.new()
    bm.from_mesh(hull.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z > 0.0], context="VERTS")
    bm.to_mesh(hull.data)
    bm.free()
    sol = hull.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = 0.04
    hull.location.z = 0.2
    assign(hull, M.WOOD)
    smooth(hull)
    seat = add("cube", size=1, location=(0, 0, 0.16))
    seat.scale = (0.16, 0.5, 0.03)
    assign(seat, M.WOOD_DARK)
    mast = add("cylinder", vertices=6, radius=0.02, depth=0.9, location=(0.35, 0, 0.6))
    assign(mast, M.WOOD_DARK)
    glass = add("cube", size=1, location=(0.35, 0, 1.08))
    glass.scale = (0.1, 0.1, 0.13)
    assign(glass, M.GLOW)
    export(name)


def pier(name):
    reset()
    for i in range(7):
        plank = add("cube", size=1, location=(0, i * 0.32, 0.3))
        plank.scale = (1.0, 0.28, 0.05)
        plank.rotation_euler.z = (i % 3 - 1) * 0.02
        bevel(plank, 0.01)
        assign(plank, M.WOOD)
    for i in (0, 3, 6):
        for x in (-0.45, 0.45):
            p = add("cylinder", vertices=7, radius=0.06, depth=1.0, location=(x, i * 0.32, -0.15))
            assign(p, M.WOOD_DARK)
    export(name)


tree_round("tree_round", "LEAF", 3)
tree_round("tree_round_b", "LEAF", 11)
tree_round("tree_autumn", "LEAF3", 21)
tree_pine("tree_pine", 5)
rock("rock_a", 1)
rock("rock_b", 9, 0.45)
grass("grass", 4)
flowers("flowers", 8)
cottage("cottage")
cottage("cottage_small", chimney=False)
lantern("lantern")
bench("bench")
fence("fence")
boat("boat")
pier("pier")
