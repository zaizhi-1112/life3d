"""Procedural model of the bundled fictional day, in millimeters."""
import math
from pathlib import Path
import struct


TITLE = "风停后的灯塔"
SUMMARY = "把积压的一件事收了尾，傍晚出去透了口气。今天的心情从紧绷慢慢落到了平静。"
IDEA = "一座落在波纹小岛上的灯塔。用低矮宽底稳住重心，塔身做成细棱，帽檐收成圆弧。"


def make_sample(path: Path) -> Path:
    # Heights, radii, and eight-fold shaping of one continuous solid.
    profile = [
        (0, 25.2, 1.5), (0.7, 26.4, 1.6), (1.5, 27, 1.5),
        (3.1, 27, 1.4), (4.0, 26.2, 1.3), (4.5, 24.6, 1.2),
        (4.6, 22.4, 1), (5.4, 21.5, .9), (5.5, 20, .8),
        (5.2, 18.7, .7), (5.5, 17, .6), (6.2, 16.1, .6),
        (6.3, 14.7, .5), (6.1, 13, .4), (6.7, 11.8, .3),
        (7.4, 11.2, .1), (9, 11.1, .1), (9.7, 10.5, .15),
        (11.4, 10.2, .55), (25, 8.9, .55), (31, 8.3, .55),
        (32, 8.3, .2), (33.2, 9.35, .1), (34.5, 10.3, 0),
        (35.2, 10.3, 0), (35.8, 9.5, 0), (36.2, 7.9, .25),
        (39.6, 7.9, .85), (41.3, 7.9, .75), (42.3, 8.9, .3),
        (43.6, 10, .1), (44.3, 10.1, .1), (45.2, 9.6, .1),
        (46.4, 8.2, .07), (48.5, 5.6, .03), (50, 3.1, 0),
        (51, 1.7, 0), (52, 1.5, 0), (53, 1.2, 0), (53.5, .6, 0),
    ]
    sides = 128
    rings = []
    for height, radius, wave in profile:
        ring = []
        for step in range(sides):
            theta = step * math.tau / sides
            phase = 5 * theta + radius * .16
            if height > 7:
                phase = (8 if height >= 35.8 else 20) * theta
            distance = radius + wave * math.cos(phase)
            ring.append((distance * math.cos(theta), distance * math.sin(theta), height))
        rings.append(ring)
    faces = []
    for lower, upper in zip(rings, rings[1:]):
        for step in range(sides):
            nxt = (step + 1) % sides
            faces.append((lower[step], lower[nxt], upper[nxt]))
            faces.append((lower[step], upper[nxt], upper[step]))
    for step in range(sides):
        nxt = (step + 1) % sides
        faces.append(((0, 0, 0), rings[0][nxt], rings[0][step]))
        faces.append(((0, 0, 53.5), rings[-1][step], rings[-1][nxt]))
    with path.open("wb") as handle:
        handle.write(b"Moodprint: Lighthouse".ljust(80, b"\x00"))
        handle.write(struct.pack("<I", len(faces)))
        for triangle in faces:
            coordinates = [value for point in triangle for value in point]
            handle.write(struct.pack("<12fH", 0, 0, 0, *coordinates, 0))
    return path
