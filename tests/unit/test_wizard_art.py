"""The wizard sprite and logo: the committed files are what scripts/wizard_art.py draws, and every animation moves."""
import struct
import zlib

from scripts import wizard_art


def test_committed_art_is_what_the_script_draws() -> None:
    assert wizard_art.stale() == [], "run: python scripts/wizard_art.py"


def test_every_animation_moves_within_its_frame() -> None:
    for name, build, fps, _ in wizard_art.ANIMATIONS:
        frames = build()
        assert 4 <= len(frames) <= 8 and fps > 0, name
        assert all((f.w, f.h) == (wizard_art.FRAME, wizard_art.FRAME) for f in frames), name
        assert len({tuple(map(tuple, f.px)) for f in frames}) > 1, f"{name} does not move"


def test_png_comparison_ignores_how_the_bytes_were_compressed() -> None:
    cv = wizard_art.mark()
    head = struct.pack(">IIBBBBB", cv.w * 2, cv.h * 2, 8, 6, 0, 0, 0)
    other_zlib = (b"\x89PNG\r\n\x1a\n" + wizard_art._chunk(b"IHDR", head)
                  + wizard_art._chunk(b"IDAT", zlib.compress(wizard_art._raw(cv, 2), 1)) + wizard_art._chunk(b"IEND", b""))
    assert other_zlib != wizard_art.png(cv, 2)
    assert wizard_art._pixels(other_zlib) == wizard_art._pixels(wizard_art.png(cv, 2))
    assert wizard_art._pixels(wizard_art.png(cv, 2)) != wizard_art._pixels(wizard_art.png(wizard_art.app_icon(), 2))
