"""Generate ShipCheck's small, attribution-free PNG interface icons.

The drawings are deliberately simple so the UI keeps one consistent visual
language without depending on an external icon service at runtime.
"""
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "icons"
SCALE = 4
SIZE = 24


def point(value: float) -> int:
    return round(value * SCALE)


def points(values):
    return [(point(x), point(y)) for x, y in values]


def generate(name: str, painter) -> None:
    image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    painter(draw)
    image.resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(OUTPUT / f"{name}.png")


def line(draw, values, width=1.8, fill=(35, 73, 105, 255), joint="curve"):
    draw.line(points(values), fill=fill, width=point(width), joint=joint)


def rect(draw, box, radius=0, width=1.8, fill=(35, 73, 105, 255)):
    scaled = tuple(point(value) for value in box)
    if radius:
        draw.rounded_rectangle(scaled, radius=point(radius), outline=fill, width=point(width))
    else:
        draw.rectangle(scaled, outline=fill, width=point(width))


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    generate("mail", lambda d: (
        rect(d, (3, 5, 21, 19), 2),
        line(d, [(4, 7), (12, 13), (20, 7)]),
    ))
    generate("inbox", lambda d: (
        line(d, [(4, 5), (20, 5), (22, 12), (22, 19), (2, 19), (2, 12), (4, 5)]),
        line(d, [(2.5, 13), (8, 13), (10, 16), (14, 16), (16, 13), (21.5, 13)]),
    ))
    generate("check", lambda d: line(d, [(4.5, 12.5), (9.5, 17), (19.5, 6.5)], 2.3))
    generate("warning", lambda d: (
        line(d, [(12, 3), (22, 20), (2, 20), (12, 3)], 1.8),
        line(d, [(12, 8), (12, 14)], 2),
        d.ellipse((point(11), point(16.5), point(13), point(18.5)), fill=(35, 73, 105, 255)),
    ))
    generate("left", lambda d: line(d, [(15, 5), (8, 12), (15, 19)], 2.1))
    generate("right", lambda d: line(d, [(9, 5), (16, 12), (9, 19)], 2.1))
    generate("down", lambda d: line(d, [(5, 9), (12, 16), (19, 9)], 2.1))
    generate("download", lambda d: (
        line(d, [(12, 3), (12, 15)], 2),
        line(d, [(7, 10), (12, 15), (17, 10)], 2),
        line(d, [(4, 19), (20, 19)], 2),
    ))
    generate("external", lambda d: (
        rect(d, (4, 7, 17, 20), 1.5),
        line(d, [(11, 13), (20, 4)], 2),
        line(d, [(14, 4), (20, 4), (20, 10)], 2),
    ))
    generate("document", lambda d: (
        line(d, [(6, 2.5), (14.5, 2.5), (19, 7), (19, 21.5), (6, 21.5), (6, 2.5)]),
        line(d, [(14, 3), (14, 8), (19, 8)]),
        line(d, [(9, 12), (16, 12)]),
        line(d, [(9, 16), (16, 16)]),
    ))
    generate("search", lambda d: (
        d.ellipse((point(3), point(3), point(16), point(16)), outline=(35, 73, 105, 255), width=point(1.8)),
        line(d, [(14, 14), (21, 21)], 2),
    ))
    generate("refresh", lambda d: (
        d.arc((point(3), point(3), point(21), point(21)), start=35, end=305,
              fill=(35, 73, 105, 255), width=point(1.9)),
        line(d, [(18.5, 3.7), (20.5, 8.5), (15.5, 8)], 1.8),
    ))
    generate("review", lambda d: (
        rect(d, (5, 4, 19, 21), 1.5),
        line(d, [(9, 4), (9, 2.5), (15, 2.5), (15, 4)]),
        line(d, [(8, 13), (11, 16), (17, 9)], 2),
    ))


if __name__ == "__main__":
    main()
