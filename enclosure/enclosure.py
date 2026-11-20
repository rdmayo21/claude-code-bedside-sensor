"""Bedside sensor enclosure: a vented pod for the SHT41 and a case for the QT Py ESP32 Pico.

Two separate parts joined by the 100 mm STEMMA QT cable, so the board's heat stays away from
the sensor. Each part is a tray plus a press-fit lid. Board geometry comes from Adafruit's own
STEP models (ref/, from github.com/adafruit/Adafruit_CAD_Parts, MIT license); the SHT40 model
stands in for the SHT41, which uses the same 1.0" x 0.7" board.

Run from this folder: uv run --python 3.12 --with cadquery python enclosure.py
Writes print/*.stl, print/*.3mf and print/*_preview.svg, and fails if either board touches
its enclosure. The STL/3MF files in print/ are already generated: you only need this script
to change the design.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).parent
OUT = HERE / "print"

WALL = 1.6  # side walls and floor
LID = 1.6  # lid plate
LIP_H = 1.6  # lid lip that drops inside the walls
FIT = 0.20  # lid lip clearance per side (raise if the lid is too tight)
CLEAR = 0.30  # board-to-wall clearance per side
SLOT_W = 1.6  # vent slot width
SLOT_GAP = 1.6  # material between vent slots
USB_W, USB_H = 12.5, 7.0  # USB-C plug overmold envelope; update from the real cable's plug


@dataclass(frozen=True)
class Box:
    """Inner cavity size (mm)."""

    x: float
    y: float
    z: float


def _tray(cav: Box) -> cq.Workplane:
    """Open-top box with the cavity's corner at the origin and its floor at z=0."""
    outer = (
        cq.Workplane("XY")
        .box(cav.x + 2 * WALL, cav.y + 2 * WALL, cav.z + WALL, centered=False)
        .translate((-WALL, -WALL, -WALL))
        .edges("|Z")
        .fillet(1.2)
    )
    inner = cq.Workplane("XY").box(cav.x, cav.y, cav.z + 1, centered=False)
    return outer.cut(inner)


def _lid(cav: Box) -> cq.Workplane:
    """Lid plate with a lip, modeled in place: plate on the walls, lip hanging into the cavity."""
    plate = (
        cq.Workplane("XY")
        .box(cav.x + 2 * WALL, cav.y + 2 * WALL, LID, centered=False)
        .translate((-WALL, -WALL, cav.z))
        .edges("|Z")
        .fillet(1.2)
    )
    lip_outer = cq.Workplane("XY").box(
        cav.x - 2 * FIT, cav.y - 2 * FIT, LIP_H, centered=False
    )
    lip_inner = cq.Workplane("XY").box(
        cav.x - 2 * FIT - 2.4, cav.y - 2 * FIT - 2.4, LIP_H, centered=False
    )
    lip = lip_outer.cut(lip_inner.translate((1.2, 1.2, 0))).translate(
        (FIT, FIT, cav.z - LIP_H)
    )
    return plate.union(lip)


def _slots(
    x0: float, x1: float, length: float, axis: str, z0: float, depth: float
) -> cq.Workplane:
    """Row of vent slots spread along x between x0 and x1; each slot runs `length` along `axis`."""
    n = int((x1 - x0 + SLOT_GAP) // (SLOT_W + SLOT_GAP))
    span = n * SLOT_W + (n - 1) * SLOT_GAP
    start = x0 + (x1 - x0 - span) / 2
    result = None
    for i in range(n):
        x = start + i * (SLOT_W + SLOT_GAP)
        if axis == "y":
            s = (
                cq.Workplane("XY")
                .box(SLOT_W, length, depth, centered=False)
                .translate((x, 0, z0))
            )
        else:
            s = (
                cq.Workplane("XY")
                .box(SLOT_W, depth, length, centered=False)
                .translate((x, 0, z0))
            )
        result = s if result is None else result.union(s)
    return result


def _place(step: str, dx: float, dy: float, dz: float) -> cq.Workplane:
    return cq.importers.importStep(str(HERE / "ref" / step)).translate((dx, dy, dz))


# ---------------------------------------------------------------------------------------------
# Sensor pod (SHT41). Model coords: PCB x 0..25.40, y 0..17.78, z 0..1.57; parts on top up to
# 4.53; STEMMA QT sockets at both short ends (y 5.89..11.89, z 1.57..4.53); the sensor itself at
# x 11.95..13.45; the green power LED at x 2.76..4.35, y 12.18..12.97.
# The cable uses the +x socket, so the -x end (next to the LED) stays a solid wall.
# ---------------------------------------------------------------------------------------------
SHT_PCB = (25.40, 17.78, 1.57)
SHT_RISE = 2.5  # PCB bottom height above the floor (posts)
SHT_HOLES = [(2.54, 2.54), (22.86, 2.54), (2.54, 15.24), (22.86, 15.24)]
pod = Box(SHT_PCB[0] + 2 * CLEAR, SHT_PCB[1] + 2 * CLEAR, 9.0)


def sensor_pod() -> tuple[cq.Workplane, cq.Workplane, cq.Workplane]:
    """Return (tray, lid, positioned board model)."""
    tray = _tray(pod)
    ox, oy = CLEAR, CLEAR  # board origin inside the cavity
    for hx, hy in SHT_HOLES:  # posts with locating pins
        post = (
            cq.Workplane("XY")
            .circle(2.4)
            .extrude(SHT_RISE)
            .translate((ox + hx, oy + hy, 0))
        )
        pin = (
            cq.Workplane("XY")
            .circle(1.0)
            .extrude(1.4)
            .translate((ox + hx, oy + hy, SHT_RISE))
        )
        tray = tray.union(post).union(pin)
    # Cable socket opening in the +x end wall: socket y 5.89..11.89, z 1.57..4.53 above PCB bottom.
    sy0, sy1 = oy + 5.89 - 1.0, oy + 11.89 + 1.0
    sz0, sz1 = SHT_RISE + 1.57 - 0.8, pod.z + 0.01
    tray = tray.cut(
        cq.Workplane("XY")
        .box(WALL + 2, sy1 - sy0, sz1 - sz0, centered=False)
        .translate((pod.x - 1, sy0, sz0))
    )
    # Vents only over the sensor half (x >= 8), away from the LED end.
    vx0, vx1 = ox + 8.0, ox + 19.8  # stay clear of the corner posts (edge at x 20.76)
    floor_vents = _slots(vx0, vx1, pod.y - 6, "y", -WALL - 0.5, WALL + 1).translate(
        (0, 3, 0)
    )
    side_vents_low = _slots(vx0, vx1, 4.5, "z", 2.0, WALL + 2).translate(
        (0, -WALL - 1, 0)
    )
    side_vents_high = _slots(vx0, vx1, 4.5, "z", 2.0, WALL + 2).translate(
        (0, pod.y - 1, 0)
    )
    tray = tray.cut(floor_vents).cut(side_vents_low).cut(side_vents_high)
    lid = _lid(pod)
    # Lid notch over the cable opening, so the lid seats with the plug in place.
    lid = lid.cut(
        cq.Workplane("XY")
        .box(3.0, sy1 - sy0, LIP_H + 0.5, centered=False)
        .translate((pod.x - 2.9, sy0, pod.z - LIP_H - 0.2))
    )
    lid_vents = _slots(vx0, vx1, pod.y - 6, "y", pod.z - 0.5, LID + 1).translate(
        (0, 3, 0)
    )
    lid = lid.cut(lid_vents)
    # Hold-down pegs over the mounting-hole rings, 0.2 mm above the PCB top.
    pcb_top = SHT_RISE + SHT_PCB[2]
    for hx, hy in SHT_HOLES:
        peg = (
            cq.Workplane("XY")
            .circle(1.8)
            .extrude(pod.z - pcb_top - 0.2)
            .translate((ox + hx, oy + hy, pcb_top + 0.2))
        )
        lid = lid.union(peg)
    board = _place("sht40.step", ox, oy, SHT_RISE)
    return tray, lid, board


# ---------------------------------------------------------------------------------------------
# Board case (QT Py ESP32 Pico). Model coords: PCB x 0..17.78, y 0..20.70, z 0..0.74; USB-C
# x 4.42..13.36, y 13.79..21.69 (sticks out 1 mm past y=20.70), z -0.26..3.94; STEMMA QT socket
# x 8.07..14.07, y 0.10..5.05, z 0.74..3.70; bottom parts down to z -1.65.
# ---------------------------------------------------------------------------------------------
QT_PCB = (17.78, 20.70, 0.74)
QT_RISE = 2.4  # PCB bottom above the floor (clears the bottom parts)
case = Box(QT_PCB[0] + 2 * CLEAR, QT_PCB[1] + 2 * CLEAR, 9.0)


def board_case() -> tuple[cq.Workplane, cq.Workplane, cq.Workplane]:
    """Return (tray, lid, positioned board model)."""
    tray = _tray(case)
    ox, oy = CLEAR, CLEAR
    # Edge ledges along both long sides; the bottom parts sit between x 3.67 and 15.05.
    for x in (0.0, case.x - 1.9):
        tray = tray.union(
            cq.Workplane("XY")
            .box(1.9, case.y, QT_RISE, centered=False)
            .translate((x, 0, 0))
        )
    # USB-C opening sized for the plug's overmold, centered on the socket.
    tray = tray.cut(_usb_envelope())
    # STEMMA QT cable opening in the -y end wall.
    scx, scz = ox + (8.07 + 14.07) / 2, QT_RISE + (0.74 + 3.70) / 2
    tray = tray.cut(
        cq.Workplane("XY").box(7.6, WALL + 2, 5.2).translate((scx, -WALL / 2, scz))
    )
    # Heat vents: both long side walls, high up, and the lid.
    for x in (-WALL - 1, case.x - 1):
        vents = _slots(3.0, case.y - 3.0, 3.5, "z", 4.6, WALL + 2)
        vents = vents.rotate((0, 0, 0), (0, 0, 1), 90).translate((x + WALL + 2, 0, 0))
        tray = tray.cut(vents)
    lid = _lid(case)
    # Notch the lid lip over the USB-C opening: without it the plug envelope's top
    # (z 7.74) reaches 0.34 mm into the lip (bottom z 7.40) over its 12.5 mm width.
    ucx = CLEAR + (4.42 + 13.36) / 2
    lid = lid.cut(
        cq.Workplane("XY")
        .box(USB_W + 0.6, FIT + 1.2 + 0.6, LIP_H + 0.2, centered=False)
        .translate((ucx - USB_W / 2 - 0.3, case.y - FIT - 1.2 - 0.3, case.z - LIP_H - 0.2))
    )
    lid = lid.cut(
        _slots(3.0, case.x - 3.0, case.y - 8, "y", case.z - 0.5, LID + 1).translate(
            (0, 4, 0)
        )
    )
    # Hold-down pegs over the ledges (castellated edge pads), 0.2 mm above the PCB top.
    pcb_top = QT_RISE + QT_PCB[2]
    peg_h = case.z - pcb_top - 0.2
    for x in (0.95, case.x - 0.95):
        for y in (7.0, 12.0):
            peg = (
                cq.Workplane("XY")
                .box(1.4, 2.0, peg_h)
                .translate((x, y, pcb_top + 0.2 + peg_h / 2))
            )
            lid = lid.union(peg)
    board = _place("qtpy_esp32_pico.step", ox, oy, QT_RISE)
    return tray, lid, board


def _usb_envelope() -> cq.Workplane:
    """USB-C plug overmold envelope through the board case's +y end wall, 1 mm into the cavity."""
    ucx, ucz = CLEAR + (4.42 + 13.36) / 2, QT_RISE + (-0.26 + 3.94) / 2
    return (
        cq.Workplane("XY")
        .box(USB_W, WALL + 2, USB_H)
        .translate((ucx, case.y + WALL / 2, ucz))
    )


def _clash(a: cq.Workplane, b: cq.Workplane) -> float:
    """Overlap volume of two shapes; an empty intersection has no solids."""
    return sum(s.Volume() for s in a.intersect(b).solids().vals())


def _self_test() -> None:
    """Prove the clash check can see an overlap, and that the openings are really open."""
    tray, lid, board = board_case()
    ptray, _, _ = sensor_pod()
    probe = cq.Workplane("XY")
    hit = probe.box(30, 30, 3, centered=False).translate((-2, -2, QT_RISE))
    wall = probe.box(1.0, 2, 2).translate((-WALL / 2, case.y / 2, 2.0))
    usb = probe.box(8, 6, 2.4).translate((CLEAR + 8.89, case.y + 1, QT_RISE + 1.84))
    cable = probe.box(5, 6, 3).translate((CLEAR + 11.07, -1, QT_RISE + 2.22))
    pcable = probe.box(6, 5, 3).translate((pod.x + 0.5, CLEAR + 8.89, SHT_RISE + 3.05))
    checks = [
        ("clash check sees a deliberate overlap", _clash(hit, board) > 1),
        ("probe into a solid wall hits", _clash(wall, tray) > 0.5),
        ("USB-C opening is clear", _clash(usb, tray) == 0),
        ("USB-C plug envelope clears the tray", _clash(_usb_envelope(), tray) < 1e-6),
        ("USB-C plug envelope clears the lid lip", _clash(_usb_envelope(), lid) < 1e-6),
        ("board-case cable opening is clear", _clash(cable, tray) == 0),
        ("sensor-pod cable opening is clear", _clash(pcable, ptray) == 0),
    ]
    for label, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not all(ok for _, ok in checks):
        sys.exit(1)


def main() -> None:
    """Build both parts, check fit against the board models, and export print files."""
    OUT.mkdir(exist_ok=True)
    _self_test()
    problems = []
    for name, (tray, lid, board) in {
        "sensor_pod": sensor_pod(),
        "board_case": board_case(),
    }.items():
        for part_name, part in (("tray", tray), ("lid", lid)):
            v = _clash(part, board)
            print(f"{name} {part_name}: overlap with board model = {v:.3f} mm^3")
            if v > 0.01:
                problems.append(f"{name} {part_name} hits the board ({v:.2f} mm^3)")
        bb = tray.val().BoundingBox()
        print(
            f"{name}: outer {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen + LID:.1f} mm with lid"
        )
        # Print orientation: tray as modeled; lid flipped so its plate is on the bed.
        lid_print = lid.rotate((0, 0, 0), (1, 0, 0), 180)
        for label, shape in ((f"{name}_tray", tray), (f"{name}_lid", lid_print)):
            for ext in ("stl", "3mf"):
                try:
                    cq.exporters.export(shape, str(OUT / f"{label}.{ext}"))
                except Exception as exc:  # 3MF needs a recent CadQuery
                    print(f"  skipped {label}.{ext}: {exc}")
        assembly = tray.union(lid)
        cq.exporters.export(
            assembly.union(board) if name else assembly,
            str(OUT / f"{name}_preview.svg"),
            opt={
                "width": 600,
                "height": 400,
                "showHidden": False,
                "projectionDir": (1.0, -1.4, 0.9),
            },
        )
    if problems:
        print("FIT PROBLEMS:", *problems, sep="\n  ")
        sys.exit(1)
    print("fit ok: neither board touches its enclosure")


if __name__ == "__main__":
    main()
