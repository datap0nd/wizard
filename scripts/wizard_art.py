"""Wizard's character sprite and logo, drawn as pixel grids (the owner's ask, 9 Oct 2026: a sprite and a logo for the
productised Wizard, and the character animating while Wizard works; in Samsung colours: Samsung Blue, white, black).

Standard library only, so it also runs on a work PC where Application Control blocks compiled packages.

  python scripts/wizard_art.py            # draw everything into brand/ and the web app
  python scripts/wizard_art.py --check    # fail if a committed file differs from what this script draws
  python scripts/wizard_art.py --preview OUT_DIR   # big contact sheets for looking the frames over

Every part is a text grid: one character per pixel, "." transparent, the rest keys of PALETTE. Frames are put together
from parts (body, arms, staff, props, effects), so the character stays the same in every animation.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import zlib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
WEB = ROOT / "apps" / "web"

RGBA = tuple[int, int, int, int]
Part = tuple[str, ...]

# Samsung colours (the owner's call, 9 Oct 2026): Samsung Blue robe and hat, white trim, black outline. The sky blue
# of the orb and the green of a passed check are the only other hues.
PALETTE: dict[str, RGBA] = {
    "K": (10, 14, 40, 255),     # outline (near black)
    "E": (10, 14, 40, 255),     # eyes
    "B": (20, 40, 160, 255),    # Samsung Blue #1428A0
    "b": (11, 24, 105, 255),    # blue shadow
    "L": (58, 92, 214, 255),    # blue light
    "Y": (255, 255, 255, 255),  # trim, stars (white)
    "y": (184, 196, 230, 255),  # trim shadow
    "W": (255, 255, 255, 255),  # white
    "S": (246, 201, 163, 255),  # skin
    "s": (220, 157, 126, 255),  # skin shadow
    "R": (239, 150, 140, 255),  # cheeks, mouth
    "H": (243, 240, 232, 255),  # beard
    "h": (196, 201, 214, 255),  # beard shadow
    "T": (139, 90, 43, 255),    # wood
    "t": (92, 58, 26, 255),     # wood shadow
    "O": (110, 190, 255, 255),  # orb (sky blue)
    "o": (31, 111, 224, 255),   # orb shadow
    "C": (190, 228, 255, 255),  # magic light
    "D": (24, 26, 36, 255),     # boots (black)
    "P": (252, 250, 243, 255),  # paper
    "p": (214, 210, 196, 255),  # paper shadow
    "G": (52, 199, 89, 255),    # a passed check
    "g": (156, 163, 178, 255),  # smoke
    "d": (110, 117, 135, 255),  # smoke shadow, dark orb
}

FRAME = 48

# ---------------------------------------------------------------------------------------------------------------- parts
# The body is drawn in two pieces so it can breathe: everything down to the hem, and the boots under it.
TORSO: Part = (
    "................KKK.......",
    "...............KLBbKK.....",
    "..............KLBBbbbK....",
    ".............KLBBbKKbbK...",
    ".............KLBBbK..KbK..",
    "............KLBBBbK..KYYK.",
    "............KLBBBbK..KYyK.",
    "...........KLBBBBbbK..KK..",
    "..........KLBBBBYbbK......",
    "..........KLBYBBBbbK......",
    ".........KLBYWYBBbbbK.....",
    ".........KLBBYBBBBbbK.....",
    "........KYYYYYYYYYYyyK....",
    "........KyyyyyyyyyyyyK....",
    "..KKKKKKLLBBBBBBBBbbbKKKK.",
    "KLLLLBBBBBBBBBBBBBBBBbbbbK",
    ".KKKKKKKKKKKKKKKKKKKKKKKK.",
    ".....KHHsHHssssHHsHHK.....",
    ".....KHHSSESSSSESSHHK.....",
    ".....KHHRSESSSSESRHHK.....",
    ".....KHHHHHHSsHHHHHHK.....",
    "....KHHHHHHhhhhHHHHHHK....",
    "..KLhHHHHHHHHHHHHHHHHhbK..",
    ".KLBhHHHHHHHHHHHHHHHHhbbK.",
    ".KLBhHHHHHHHHHHHHHHHHhbbK.",
    ".KLBBhHHHHHHHHHHHHHHhBbbK.",
    ".KLBBhHHHHHHHHHHHHHHhBbbK.",
    ".KLBBBhHHHHHHHHHHHHhBBbbK.",
    ".KLBBBBhHHHHHHHHHHhBBBbbK.",
    ".KYYYYYYhHHHHHHHHhYYYYyyK.",
    ".KLBBBBBBhHHHHHHhBBBBBbbK.",
    ".KLBBBBBBBhHHHHhBBBBBBbbK.",
    "KLBBBBBBBBBhhhhBBBBBBBbbbK",
    "KLBBBBBBBBBBBBBBBBBBBBbbbK",
    "KLBBBBBBBBBBBBBBBBBBBBbbbK",
    "KYYYYYYYYYYYYYYYYYYYYYyyyK",
    "KyyyyyyyyyyyyyyyyyyyyyyyyK",
    ".KKKKKKKKKKKKKKKKKKKKKKKK.",
)
BOOTS: Part = (
    ".....KDDDDK....KDDDDK.....",
    ".....KKKKKK....KKKKKK.....",
)
BODY_X, BODY_Y = 11, 8         # where the torso's top-left sits in a frame at rest
EYES_ROW, EYE_L, EYE_R = 18, 10, 15
MOUTH_ROW = 21

# The arm on the viewer's left, hanging.
SLEEVE_HANG: Part = (
    "....KK.",
    "...KLBK",
    "..KLBBK",
    "..KLBBK",
    ".KLBBBK",
    ".KLBBBK",
    "KLBBBbK",
    "KLBBbbK",
    "KYYYyyK",
    ".KSSsK.",
    "..KKKK.",
)
# The arm on the viewer's left, bent so the hand strokes the beard.
SLEEVE_BEARD: Part = (
    "....KK......",
    "...KLBK.....",
    "..KLBBK.....",
    "..KLBBK.....",
    ".KLBBBBKKK..",
    ".KLBBBBBYYK.",
    "KLBBBBBbYyKK",
    "KLBBbbbbKSSK",
    ".KKKKKKKKSsK",
    ".........KK.",
)
# The arm on the viewer's right, holding the staff at the side.
SLEEVE_STAFF: Part = (
    ".KK.....",
    "KBbKK...",
    "KBBbbK..",
    "KBBbbbK.",
    "KbBbbbbK",
    "KbBbbbbK",
    ".KbbbbbK",
    ".KbbbbbK",
    "..KYyyyK",
    "...KKKK.",
)
# The arm on the viewer's right, raised: the wide sleeve falls back from the hand.
SLEEVE_RAISE: Part = (
    "......KK",
    ".....KYK",
    "....KYyK",
    "...KbbbK",
    "..KBbbK.",
    ".KBBbbK.",
    "KBBbbK..",
    "KBbbK...",
    "KbbK....",
    ".KK.....",
)
# Both hands forward, holding something in front of the beard (a book).
HANDS_FRONT: Part = (
    "KK..............KK",
    "KBK............KbK",
    "KBBK..........KbbK",
    "KLBBK........KbbbK",
    "KLBBBK......KbbbbK",
    ".KLBYYK....KYYbbK.",
    "..KKYSSK..KSSYKK..",
    "....KKK....KKK....",
)
FIST: Part = (
    ".KKK.",
    "KSSSK",
    "KsSSK",
    ".KKK.",
)
ORB: Part = (
    "..KKK..",
    ".KWOOK.",
    "KWOOOoK",
    "KOOOOoK",
    "KoOOooK",
    ".KoooK.",
    ".KTTtK.",
)
ORB_DARK: Part = tuple(row.replace("W", "g").replace("O", "d").replace("o", "K") for row in ORB)
SHAFT = "..KTtK."
STAFF_LENGTH = 38               # orb top to the ground

BOOK: Part = (
    "KKKKKKKK.KKKKKKKK",
    "KPPPPPPPKPPPPPPPK",
    "KPppppPPKPPppppPK",
    "KPPPPPPPKPPPPPPPK",
    "KPppppPPKPPppppPK",
    "KPPPPPPPKPPPPPPPK",
    "KPpppPPPKPPpppPPK",
    "KbbbbbbbKbbbbbbbK",
    ".KKKKKKKKKKKKKKK.",
)
PAGE_UP: tuple[Part, ...] = (      # one page turning, drawn over the open book (right page lifts, crosses, lands)
    (
        ".........KKKKKK..",
        ".........KPPPPPK.",
        ".........KPPPPK..",
        ".........KPPPK...",
        ".........KPPK....",
        ".........KKK.....",
    ),
    (
        "........KK.......",
        "........KPK......",
        "........KPK......",
        "........KPK......",
        "........KPK......",
        "........KPK......",
        "........KK.......",
    ),
    (
        "..KKKKKK.........",
        ".KPPPPPK.........",
        "..KPPPPK.........",
        "...KPPPK.........",
        "....KPPK.........",
        ".....KKK.........",
    ),
)
MAGNIFIER: Part = (
    "..KKK....",
    ".KWCCK...",
    "KWOOOCK..",
    "KCOOOOK..",
    "KCOOOoK..",
    ".KCooKK..",
    "..KKKTtK.",
    ".....KTtK",
    "......KK.",
)
HAND: Part = (
    ".KKK.",
    "KSSSK",
    "KSSsK",
    ".KKK.",
)
QUILL_FEATHER: Part = (
    ".....KK",
    "....KWK",
    "...KWyK",
    "..KWWyK",
    ".KWWyK.",
    ".KWyK..",
    "KyKK...",
    "K......",
)
CHECK: Part = (
    ".......KK",
    "......KGK",
    ".KK..KGGK",
    "KGGKKGGK.",
    ".KGGGGK..",
    "..KGGK...",
    "...KK....",
)
SWEAT: Part = (
    ".K.",
    "KCK",
    "KOK",
    ".K.",
)
BUBBLE_DOT: Part = (".KK.", "KWWK", "KWWK", ".KK.")
BUBBLE_DOT_SMALL: Part = ("KK", "KK")

GLYPHS: dict[str, Part] = {      # 3x3 symbols a calculation throws off
    "+": (".W.", "WWW", ".W."),
    "x": ("W.W", ".W.", "W.W"),
    "=": ("WWW", "...", "WWW"),
    "%": ("W.W", "..W", "W.W"),
}


# --------------------------------------------------------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, w: int = FRAME, h: int = FRAME) -> None:
        self.w, self.h = w, h
        self.px: list[list[RGBA | None]] = [[None] * w for _ in range(h)]

    def put(self, x: int, y: int, color: RGBA | str) -> None:
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        rgba = PALETTE[color] if isinstance(color, str) else color
        below = self.px[y][x]
        if rgba[3] == 255 or below is None:
            self.px[y][x] = rgba
            return
        a = rgba[3] / 255
        self.px[y][x] = (round(rgba[0] * a + below[0] * (1 - a)), round(rgba[1] * a + below[1] * (1 - a)),
                         round(rgba[2] * a + below[2] * (1 - a)), below[3])

    def part(self, part: Part, x: int, y: int, *, flip: bool = False, swap: dict[str, str] | None = None) -> None:
        for r, row in enumerate(part):
            cells = row[::-1] if flip else row
            for c, ch in enumerate(cells):
                if ch != ".":
                    self.put(x + c, y + r, (swap or {}).get(ch, ch))

    def paste(self, other: Canvas, x: int, y: int) -> None:
        for r in range(other.h):
            for c in range(other.w):
                px = other.px[r][c]
                if px is not None:
                    self.put(x + c, y + r, px)


def sparkle(cv: Canvas, x: int, y: int, size: int, color: str = "W") -> None:
    """A twinkle: size 0 is one pixel, 1 a plus, 2 a four-pointed star with a light core."""
    if size <= 0:
        cv.put(x, y, color)
        return
    arms = 1 if size == 1 else 2
    for d in range(-arms, arms + 1):
        tip = abs(d) == arms and size >= 2
        cv.put(x + d, y, "o" if tip else color)
        cv.put(x, y + d, "o" if tip else color)
    cv.put(x, y, "W")


def puff(cv: Canvas, x: int, y: int, r: int) -> None:
    """A smoke puff: a disc with an outline and a lighter top."""
    for dy in range(-r - 1, r + 2):
        for dx in range(-r - 1, r + 2):
            d = math.hypot(dx, dy)
            if d <= r - 0.3:
                cv.put(x + dx, y + dy, "g" if dy < r / 3 else "d")
            elif d <= r + 0.7:
                cv.put(x + dx, y + dy, "K")


def shadow(cv: Canvas, cx: int, y: int, half: int) -> None:
    for dx in range(-half, half + 2):
        for dy, scale in ((0, 1.0), (1, 0.7)):
            if abs(dx - 0.5) <= half * scale + 0.5:
                cv.put(cx + dx, y + dy, (10, 14, 40, 46))


# ------------------------------------------------------------------------------------------------------------ the figure
LIT = {"b": "B", "B": "L"}         # a left arm, turned to the light


def wizard(cv: Canvas, *, pose: str = "stand", dy: int = 0, breathe: int = 0, eyes: str = "open", mouth: str = "",
           orb: str = "lit", staff_dy: int = 0, hand_dy: int = 0, arm: tuple[int, int] = (0, 0)) -> None:
    """Draw the wizard.

    pose: stand (staff at his side), beard (stroking it), lift (left arm raised, for a magnifier or a wave), raise
    (staff held high), book (reading, the staff floating beside him). dy lifts the whole figure (a jump); breathe sinks
    the torso into the boots by 0-1 pixel; arm moves a raised left hand."""
    x, y = BODY_X, BODY_Y + dy
    top = y + breathe
    shadow(cv, BODY_X + 12, BODY_Y + len(TORSO) + len(BOOTS) - 1, max(4, 12 - abs(dy) * 2))
    cv.part(BOOTS, x, y + len(TORSO))

    staff_x = x + 26
    if pose in ("stand", "beard", "lift"):
        draw_staff(cv, staff_x, top + 1 + staff_dy, orb)
    elif pose == "raise":
        draw_staff(cv, staff_x, top - 6 + staff_dy, orb, length=STAFF_LENGTH - 4)
    elif pose == "book":
        draw_staff(cv, staff_x + 4, top + 2 + staff_dy, orb, length=STAFF_LENGTH - 8)

    cv.part(TORSO, x, top)
    face(cv, x, top, eyes, mouth)

    if pose in ("stand", "raise"):
        cv.part(SLEEVE_HANG, x - 4, top + 21)
    if pose == "beard":
        cv.part(SLEEVE_BEARD, x - 4, top + 21 + hand_dy)
    if pose == "lift":
        cv.part(SLEEVE_RAISE, x - 4 + arm[0], top + 16 + arm[1], flip=True, swap=LIT)
    if pose in ("stand", "beard", "lift"):
        cv.part(SLEEVE_STAFF, x + 22, top + 21)
        cv.part(FIST, staff_x + 1, top + 29)
    if pose == "raise":
        cv.part(SLEEVE_RAISE, x + 22, top + 17)
        cv.part(FIST, staff_x + 1, top + 15 + staff_dy)
    if pose == "book":
        cv.part(HANDS_FRONT, x + 4, top + 24)


def lifted_hand(top: int, arm: tuple[int, int]) -> tuple[int, int]:
    """Where the raised left hand sits (its top-left), for the thing it holds."""
    return BODY_X - 6 + arm[0], top + 14 + arm[1]


def draw_staff(cv: Canvas, x: int, y: int, orb: str, *, length: int = STAFF_LENGTH) -> None:
    cv.part(ORB_DARK if orb == "dark" else ORB, x, y)
    for r in range(len(ORB), length - 1):
        cv.part((SHAFT,), x, y + r)
    cv.part(("..KKKK.",), x, y + length - 1)
    if orb == "glow":
        for gx, gy in ((-1, 3), (7, 3), (3, -1)):
            cv.put(x + gx, y + gy, "O")


def face(cv: Canvas, x: int, y: int, eyes: str, mouth: str) -> None:
    row = y + EYES_ROW
    for ex in (x + EYE_L, x + EYE_R):
        cv.put(ex, row, "S")
        cv.put(ex, row + 1, "S")
        if eyes == "open":
            cv.put(ex, row, "E")
            cv.put(ex, row + 1, "E")
        elif eyes == "closed":
            cv.put(ex, row + 1, "E")
            cv.put(ex + (1 if ex == x + EYE_L else -1), row + 1, "E")
        elif eyes == "up":
            cv.put(ex, row, "E")
        elif eyes == "down":
            cv.put(ex, row + 1, "E")
        elif eyes == "left":
            cv.put(ex - 1, row, "E")
            cv.put(ex - 1, row + 1, "E")
        elif eyes == "happy":
            cv.put(ex, row, "E")
            cv.put(ex - 1, row + 1, "E")
            cv.put(ex + 1, row + 1, "E")
    m = y + MOUTH_ROW
    if mouth == "o":
        for mx in (x + 12, x + 13):
            cv.put(mx, m, "K")
            cv.put(mx, m + 1, "K")
    elif mouth == "smile":
        cv.put(x + 11, m, "K")
        cv.put(x + 12, m + 1, "K")
        cv.put(x + 13, m + 1, "K")
        cv.put(x + 14, m, "K")
        cv.put(x + 12, m, "R")
        cv.put(x + 13, m, "R")


# ----------------------------------------------------------------------------------------------------------- animations
Frames = list[Canvas]
BREATH = (0, 0, 1, 1, 0, 0)


def anim_idle() -> Frames:
    """At rest: breathing, a blink, a twinkle on the orb."""
    out = []
    for i, eyes in enumerate(("open", "open", "open", "open", "closed", "open")):
        cv = Canvas()
        wizard(cv, breathe=BREATH[i], eyes=eyes)
        if i in (1, 2, 3):
            sparkle(cv, BODY_X + 31, BODY_Y + 1 + BREATH[i], (0, 1, 2, 1)[i])
        out.append(cv)
    return out


def anim_wave() -> Frames:
    """Hello: the left hand waves, the wizard smiles."""
    out = []
    for i, arm in enumerate(((0, 0), (-1, 0), (-2, 1), (-1, 0), (0, 0), (1, 1))):
        cv = Canvas()
        wizard(cv, pose="lift", arm=arm, eyes="happy", mouth="smile", breathe=BREATH[i])
        hx, hy = lifted_hand(BODY_Y + BREATH[i], arm)
        cv.part(HAND, hx + (i % 2), hy)
        if i in (1, 2, 4):
            sparkle(cv, hx - 2, hy - 2, 0, "o")
        out.append(cv)
    return out


def anim_think() -> Frames:
    """Gemini is deciding the next step: a hand strokes the beard, thought bubbles rise."""
    out = []
    dots = (0, 1, 2, 3, 3, 0)
    for i in range(6):
        cv = Canvas()
        wizard(cv, pose="beard", eyes="up", hand_dy=(0, 1, 0, 1, 0, 1)[i], breathe=BREATH[i])
        for d in range(dots[i]):
            cv.part(BUBBLE_DOT_SMALL if d == 0 else BUBBLE_DOT, 11 - d * 4 + (1 if d == 0 else 0), 14 - d * 4)
        out.append(cv)
    return out


SCAN = ((0, 0), (1, -1), (2, 0), (2, 1), (1, 1), (0, 0))


def anim_search() -> Frames:
    """Searching sources: a magnifying glass sweeps, its glint moving."""
    out = []
    for i, arm in enumerate(SCAN):
        cv = Canvas()
        wizard(cv, pose="lift", arm=arm, eyes="left", breathe=BREATH[i])
        hx, hy = lifted_hand(BODY_Y + BREATH[i], arm)
        cv.part(MAGNIFIER, hx - 5, hy - 6)
        cv.part(HAND, hx, hy)
        cv.put(hx - 3 + (i % 3), hy - 4 + (i % 3), "W")
        out.append(cv)
    return out


def book_at(top: int) -> tuple[int, int]:
    return BODY_X + 4, top + 24


def draw_book(cv: Canvas, bx: int, by: int) -> None:
    cv.part(BOOK, bx, by)
    cv.part(HAND, bx - 2, by + 5)
    cv.part(HAND, bx + 14, by + 5)


def anim_read() -> Frames:
    """Reading a source: pages turn, motes of light rise from the book."""
    out = []
    pages = (None, 0, 1, 2, None, None)
    for i in range(6):
        cv = Canvas()
        top = BODY_Y + BREATH[i]
        wizard(cv, pose="book", eyes="down", staff_dy=(0, -1, -1, 0, 1, 1)[i], breathe=BREATH[i])
        bx, by = book_at(top)
        draw_book(cv, bx, by)
        page = pages[i]
        if page is not None:
            cv.part(PAGE_UP[page], bx, by - 4)
        for k in range(2):
            rise = (i + k * 3) % 6
            sparkle(cv, bx - 3 + k * 23, by - 1 - rise * 2, 0 if rise > 3 else 1, "O")
        out.append(cv)
    return out


def anim_write() -> Frames:
    """Writing the answer: the quill moves along the page, line by line."""
    out = []
    for i in range(6):
        cv = Canvas()
        top = BODY_Y + BREATH[i]
        wizard(cv, pose="book", eyes="down", staff_dy=(0, -1, -1, 0, 1, 1)[i], breathe=BREATH[i])
        bx, by = book_at(top)
        cv.part(BOOK, bx, by)
        cv.part(HAND, bx - 2, by + 5)
        line, col = divmod(i, 3)
        for ln in range(line + 1):
            for c in range(5 if ln < line else 1 + col * 2):
                cv.put(bx + 10 + c, by + 2 + ln * 2, "B")
        qx, qy = bx + 11 + col * 2, by + 1 + line * 2
        cv.part(QUILL_FEATHER, qx, qy - 7)
        cv.part(HAND, qx - 1, qy - 1)
        out.append(cv)
    return out


def anim_cast() -> Frames:
    """Calculating: the staff held high throws off + x = % signs."""
    out = []
    symbols = "+x=%"
    for i in range(6):
        cv = Canvas()
        wizard(cv, pose="raise", eyes="up", orb="glow" if i % 2 else "lit", mouth="o" if i in (2, 3) else "")
        ox, oy = BODY_X + 29, BODY_Y - 3
        for k in range(3):
            t = (i + k * 2) % 6          # 0..5 along the arc, leftwards from the orb
            gx = ox - 7 - t * 5
            gy = 3 - round(2 * math.sin(math.pi * t / 5))
            cv.part(GLYPHS[symbols[(k + (i + k * 2) // 6) % len(symbols)]], gx, gy, swap={"W": "B" if k % 2 else "o"})
        sparkle(cv, ox, oy + 1, 2 if i % 2 else 1)
        out.append(cv)
    return out


def bar_chart(cv: Canvas, x: int, y: int, heights: list[int]) -> None:
    """A floating three-bar chart, its baseline at y."""
    for k, h in enumerate(heights):
        bx = x + k * 4
        for r in range(h):
            for c in range(3):
                edge = c != 1 or r == h - 1
                cv.put(bx + c, y - r, "K" if edge else ("B" if k == 2 else "O"))
    for c in range(-1, 12):
        cv.put(x + c, y + 1, "K")


def anim_chart() -> Frames:
    """Drawing a chart: bars rise in the air beside him."""
    out = []
    grow = ([0, 0, 0], [3, 0, 0], [4, 3, 0], [5, 5, 3], [5, 7, 7], [5, 7, 10])
    for i in range(6):
        cv = Canvas()
        wizard(cv, pose="raise", eyes="left", orb="glow" if i % 2 else "lit", mouth="smile" if i == 5 else "")
        bar_chart(cv, 1, 19, grow[i])
        tallest = max(range(3), key=lambda k: grow[i][k])
        sparkle(cv, 2 + tallest * 4, 17 - grow[i][tallest], 2 if i == 5 else 1)
        out.append(cv)
    return out


def anim_check() -> Frames:
    """Check my data: the glass goes over the figures, then a tick."""
    out = []
    for i, arm in enumerate(((0, 0), (1, 1), (2, 0), (1, -1), (0, 0), (0, 0))):
        cv = Canvas()
        done = i >= 4
        wizard(cv, pose="lift", arm=arm, eyes="happy" if done else "left", mouth="smile" if done else "")
        hx, hy = lifted_hand(BODY_Y, arm)
        cv.part(MAGNIFIER, hx - 5, hy - 6)
        cv.part(HAND, hx, hy)
        if done:
            cv.part(CHECK, hx - 3, hy - 14 + (1 if i == 4 else 0))
            sparkle(cv, hx + 7, hy - 13, 1 if i == 4 else 2)
        out.append(cv)
    return out


def anim_success() -> Frames:
    """The answer is in: a hop, the staff high, a burst of stars."""
    out = []
    jump = (0, -2, -4, -4, -3, -1, 0, 0)
    for i, dy in enumerate(jump):
        cv = Canvas()
        wizard(cv, pose="raise", dy=dy, eyes="happy", mouth="smile", orb="glow" if i % 2 == 0 else "lit", staff_dy=2)
        ox, oy = BODY_X + 29, BODY_Y + 2 + dy
        if 1 <= i <= 6:
            dist = 1 + i * 2
            for k, angle in enumerate(range(150, 390, 40)):
                a = math.radians(angle)
                size = 2 if (k + i) % 2 else 1
                sparkle(cv, ox + round(math.cos(a) * dist), oy - round(math.sin(a) * dist * 0.8), size,
                        "O" if i < 5 else "C")
        out.append(cv)
    return out


def anim_fail() -> Frames:
    """It did not work: the orb fizzles out in smoke, a bead of sweat."""
    out = []
    for i in range(6):
        cv = Canvas()
        wizard(cv, eyes="closed" if i >= 2 else "open", breathe=1 if i >= 2 else 0, orb="dark" if i >= 1 else "lit",
               mouth="o" if i == 1 else "")
        ox, oy = BODY_X + 29, BODY_Y + 1
        if i >= 1:
            puff(cv, ox + (i % 2), oy - 2 - i, 1 + min(i, 2) // 2)
        if i >= 3:
            puff(cv, ox - 4, oy - 3 - (i - 3) * 2, 1)
        if i >= 2:
            cv.part(SWEAT, BODY_X + 4, BODY_Y + 17 + min(i - 2, 2))
        out.append(cv)
    return out


# name, builder, frames per second, loops
ANIMATIONS: list[tuple[str, Callable[[], Frames], int, bool]] = [
    ("idle", anim_idle, 6, True),
    ("wave", anim_wave, 8, True),
    ("think", anim_think, 6, True),
    ("search", anim_search, 7, True),
    ("read", anim_read, 6, True),
    ("write", anim_write, 6, True),
    ("cast", anim_cast, 8, True),
    ("chart", anim_chart, 6, True),
    ("check", anim_check, 6, True),
    ("success", anim_success, 10, False),
    ("fail", anim_fail, 7, False),
]


# ----------------------------------------------------------------------------------------------------------------- logo
# The mark is the wizard's hat on a 16-pixel grid, so it stays crisp as a 16 and 32 pixel favicon.
HAT_MARK: Part = (
    "........KKK.....",
    ".......KLBbKK...",
    "......KLBBbbbK..",
    "......KLBbKKbbK.",
    ".....KLBBbK.KYYK",
    ".....KLBBbK.KyyK",
    "....KLBBYBbK.KK.",
    "....KLBYWYbK....",
    "...KLBBBYBbbK...",
    "...KLBBBBBbbK...",
    "..KYYYYYYYYYyK..",
    "..KyyyyyyyyyyK..",
    "KKKLLBBBBBBbbKKK",
    "KLLBBBBBBBBBBbbK",
    ".KKKKKKKKKKKKKK.",
    "................",
)
# On a Samsung Blue tile the hat turns white with a blue band: the reversed mark.
REVERSED = {"B": "W", "L": "W", "b": "y", "Y": "B", "W": "B", "y": "b", "K": "b"}

LETTERS: dict[str, Part] = {
    "W": (
        "##......##",
        "##......##",
        "##......##",
        "##..##..##",
        "##..##..##",
        "##..##..##",
        "##..##..##",
        "##########",
        ".###..###.",
    ),
    "I": (
        "######",
        "######",
        "..##..",
        "..##..",
        "..##..",
        "..##..",
        "..##..",
        "######",
        "######",
    ),
    "Z": (
        "########",
        "########",
        ".....###",
        "....###.",
        "...###..",
        "..###...",
        ".###....",
        "########",
        "########",
    ),
    "A": (
        "..####..",
        ".######.",
        "###..###",
        "##....##",
        "##....##",
        "########",
        "########",
        "##....##",
        "##....##",
    ),
    "R": (
        "#######.",
        "########",
        "##....##",
        "##....##",
        "########",
        "#######.",
        "##..###.",
        "##...###",
        "##....##",
    ),
    "D": (
        "######..",
        "#######.",
        "##...###",
        "##....##",
        "##....##",
        "##....##",
        "##...###",
        "#######.",
        "######..",
    ),
}


def wordmark(text: str, color: str) -> Canvas:
    widths = [len(LETTERS[ch][0]) for ch in text]
    cv = Canvas(sum(widths) + 2 * (len(text) - 1), len(LETTERS[text[0]]))
    x = 0
    for ch, w in zip(text, widths, strict=True):
        cv.part(tuple(row.replace("#", color) for row in LETTERS[ch]), x, 0)
        x += w + 2
    return cv


def mark(*, reversed_: bool = False) -> Canvas:
    cv = Canvas(16, 16)
    cv.part(HAT_MARK, 0, 0, swap=REVERSED if reversed_ else None)
    return cv


def app_icon() -> Canvas:
    """The reversed hat on a Samsung Blue tile with rounded corners (20 x 20)."""
    cv = Canvas(20, 20)
    for y in range(20):
        for x in range(20):
            corner = min(x, 19 - x) + min(y, 19 - y)
            if corner >= 2 or (min(x, 19 - x) >= 1 and min(y, 19 - y) >= 1):
                cv.put(x, y, "B")
    cv.part(HAT_MARK, 2, 3, swap=REVERSED)
    return cv


def logo(*, white: bool = False) -> Canvas:
    word = wordmark("WIZARD", "W" if white else "K")
    cv = Canvas(16 + 5 + word.w, 16)
    cv.paste(mark(reversed_=white), 0, 0)
    cv.paste(word, 21, 5)
    return cv


# ------------------------------------------------------------------------------------------------------------------ png
def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _raw(cv: Canvas, scale: int) -> bytes:
    out = bytearray()
    for y in range(cv.h * scale):
        out.append(0)
        row = cv.px[y // scale]
        for x in range(cv.w * scale):
            out.extend(row[x // scale] or (0, 0, 0, 0))
    return bytes(out)


def png(cv: Canvas, scale: int = 1) -> bytes:
    head = struct.pack(">IIBBBBB", cv.w * scale, cv.h * scale, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", head) + _chunk(b"IDAT", zlib.compress(_raw(cv, scale), 9))
            + _chunk(b"IEND", b""))


def sheet(frames_by_row: list[Frames], cols: int) -> Canvas:
    out = Canvas(cols * FRAME, len(frames_by_row) * FRAME)
    for r, frames in enumerate(frames_by_row):
        for c, frame in enumerate(frames):
            out.paste(frame, c * FRAME, r * FRAME)
    return out


def on(cv: Canvas, bg: RGBA) -> Canvas:
    out = Canvas(cv.w, cv.h)
    for y in range(cv.h):
        for x in range(cv.w):
            out.px[y][x] = bg
    out.paste(cv, 0, 0)
    return out


def apng(frames: Frames, fps: int, scale: int, *, hold_last: bool = False) -> bytes:
    """An animated PNG that loops (the previews in brand/). A one-shot animation holds its last frame for a second."""
    w, h = frames[0].w * scale, frames[0].h * scale
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    out += _chunk(b"acTL", struct.pack(">II", len(frames), 0))
    seq = 0
    for i, frame in enumerate(frames):
        last = i == len(frames) - 1
        delay = (fps, fps) if hold_last and last else (1, fps)
        out += _chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, w, h, 0, 0, delay[0], delay[1], 1, 0))
        seq += 1
        data = zlib.compress(_raw(frame, scale), 9)
        if i == 0:
            out += _chunk(b"IDAT", data)
        else:
            out += _chunk(b"fdAT", struct.pack(">I", seq) + data)
            seq += 1
    out += _chunk(b"IEND", b"")
    return bytes(out)


def svg(cv: Canvas, title: str, *, size: int | None = None) -> str:
    """Pixels as one path per colour (each row's runs merged), crisp at any size."""
    paths: dict[RGBA, list[str]] = {}
    for y in range(cv.h):
        x = 0
        while x < cv.w:
            px = cv.px[y][x]
            if px is None:
                x += 1
                continue
            start = x
            while x < cv.w and cv.px[y][x] == px:
                x += 1
            paths.setdefault(px, []).append(f"M{start} {y}h{x - start}v1h-{x - start}z")
    width = f' width="{cv.w * size}" height="{cv.h * size}"' if size else ""
    body = "".join(f'<path fill="#{r:02x}{g:02x}{b:02x}" d="{"".join(d)}"/>' for (r, g, b, _), d in paths.items())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cv.w} {cv.h}"{width} shape-rendering="crispEdges"'
            f' role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n')


def favicon_link(cv: Canvas) -> str:
    text = svg(cv, "Wizard").strip().replace('"', "'")
    for a, b in (("%", "%25"), ("#", "%23"), ("<", "%3C"), (">", "%3E")):
        text = text.replace(a, b)
    return f'<link rel="icon" href="data:image/svg+xml,{text}" />'


ROLES = {
    "idle": "At rest: nothing is running.",
    "wave": "Hello, on the start screen.",
    "think": "Gemini is deciding the next step (no tool running, no answer text yet).",
    "search": "A search tool runs: search reports, report schema, list sources, search catalog, browse knowledge.",
    "read": "A read tool runs: run report, query PostgreSQL, read or query an attachment, read knowledge, definitions.",
    "write": "The answer text is streaming in.",
    "cast": "wizard_calculate runs.",
    "chart": "wizard_render_visual runs.",
    "check": "Check my data runs.",
    "success": "The run finished with an answer (plays once).",
    "fail": "The run failed (plays once).",
}


def outputs() -> dict[Path, bytes]:
    """Every file this script owns, by path."""
    rows = [build() for _, build, _, _ in ANIMATIONS]
    cols = max(len(r) for r in rows)
    full = sheet(rows, cols)
    files: dict[Path, bytes] = {}
    files[BRAND / "sprite" / "wizard-sprite.png"] = png(full)
    files[BRAND / "sprite" / "wizard-sprite@4x.png"] = png(full, 4)
    for (name, _, fps, loops), frames in zip(ANIMATIONS, rows, strict=True):
        files[BRAND / "sprite" / "preview" / f"{name}.png"] = apng(frames, fps, 4, hold_last=not loops)
    atlas = {
        "image": "wizard-sprite.png",
        "image_4x": "wizard-sprite@4x.png",
        "frame": {"width": FRAME, "height": FRAME},
        "columns": cols,
        "drawn_by": "scripts/wizard_art.py",
        "animations": {
            name: {"row": r, "frames": len(frames), "fps": fps, "loop": loops, "when": ROLES[name],
                   "rects": [[c * FRAME, r * FRAME, FRAME, FRAME] for c in range(len(frames))]}
            for r, ((name, _, fps, loops), frames) in enumerate(zip(ANIMATIONS, rows, strict=True))
        },
        "palette": {k: "#{:02x}{:02x}{:02x}".format(*v[:3]) for k, v in PALETTE.items()},
    }
    files[BRAND / "sprite" / "wizard-sprite.json"] = (json.dumps(atlas, indent=2) + "\n").encode()

    files[BRAND / "logo" / "wizard-logo.svg"] = svg(logo(), "Wizard").encode()
    files[BRAND / "logo" / "wizard-logo-white.svg"] = svg(logo(white=True), "Wizard").encode()
    files[BRAND / "logo" / "wizard-mark.svg"] = svg(mark(), "Wizard").encode()
    files[BRAND / "logo" / "wizard-app-icon.svg"] = svg(app_icon(), "Wizard").encode()
    files[BRAND / "logo" / "wizard-logo.png"] = png(logo(), 8)
    files[BRAND / "logo" / "wizard-mark.png"] = png(mark(), 32)
    for size in (32, 180, 512):
        files[BRAND / "logo" / f"wizard-app-icon-{size}.png"] = png(app_icon(), max(1, size // 20))

    files[WEB / "src" / "assets" / "wizard-sprite.png"] = png(full)
    files[WEB / "src" / "assets" / "wizard-mark.svg"] = svg(mark(), "Wizard").encode()
    files[WEB / "src" / "assets" / "wizard-logo.svg"] = svg(logo(), "Wizard").encode()
    lines = [f"  {name}: {{row: {r}, frames: {len(frames)}, fps: {fps}, loop: {str(loops).lower()}}},"
             for r, ((name, _, fps, loops), frames) in enumerate(zip(ANIMATIONS, rows, strict=True))]
    files[WEB / "src" / "wizardSheet.ts"] = "\n".join([
        "// Drawn by scripts/wizard_art.py, which writes this file with the sprite sheet: do not edit by hand.",
        f"export const FRAME = {FRAME};",
        f"export const COLUMNS = {cols};",
        f"export const ROWS = {len(rows)};",
        "export const ANIMATIONS = {",
        *lines,
        "} as const;",
        "export type WizardAnimation = keyof typeof ANIMATIONS;",
        "",
    ]).encode()

    index = WEB / "index.html"
    html = index.read_text(encoding="utf-8")
    files[index] = re.sub(r'<link rel="icon" href="[^"]*" />', lambda _: favicon_link(mark()), html, count=1).encode()
    return files


def _pixels(data: bytes) -> list[bytes]:
    """A PNG's header and decompressed image data, frame by frame: the same pixels compare equal whichever zlib wrote
    them (Windows Python builds use a different one)."""
    parts: list[bytes] = []
    pos, idat = 8, bytearray()
    while pos < len(data):
        (length,), kind = struct.unpack(">I", data[pos:pos + 4]), data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind in (b"IHDR", b"acTL", b"fcTL"):
            if idat:
                parts.append(zlib.decompress(bytes(idat)))
                idat.clear()
            parts.append(kind + body[4:] if kind == b"fcTL" else kind + body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"fdAT":
            idat += body[4:]
        pos += 12 + length
    if idat:
        parts.append(zlib.decompress(bytes(idat)))
    return parts


def stale() -> list[str]:
    """Files whose committed content differs from what this script draws."""
    out = []
    for path, data in outputs().items():
        if not path.is_file():
            out.append(f"{path.relative_to(ROOT)} (missing)")
            continue
        have = path.read_bytes()
        same = _pixels(have) == _pixels(data) if path.suffix == ".png" else have.replace(b"\r\n", b"\n") == data
        if not same:
            out.append(str(path.relative_to(ROOT)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a committed file is not what this script draws")
    parser.add_argument("--preview", type=Path, help="write big contact sheets to this folder instead")
    args = parser.parse_args()
    if args.check:
        bad = stale()
        for line in bad:
            print("stale:", line)
        print("wizard art is up to date" if not bad else "run: python scripts/wizard_art.py")
        return 1 if bad else 0
    if args.preview:
        args.preview.mkdir(parents=True, exist_ok=True)
        rows = [build() for _, build, _, _ in ANIMATIONS]
        (args.preview / "sheet.png").write_bytes(png(on(sheet(rows, 8), (226, 230, 238, 255)), 4))
        board = Canvas(110, 62)
        board.paste(logo(), 2, 2)
        board.paste(mark(), 2, 24)
        board.paste(app_icon(), 24, 22)
        for yy in range(42, 62):
            for xx in range(110):
                board.put(xx, yy, "B")
        board.paste(logo(white=True), 2, 44)
        (args.preview / "logo.png").write_bytes(png(on(board, (255, 255, 255, 255)), 8))
        print("wrote", args.preview)
        return 0
    for path, data in outputs().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)
            print("wrote", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
