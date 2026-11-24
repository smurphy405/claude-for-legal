#!/usr/bin/env python3
"""
yoyo_logo.py: cut-ready vinyl decal artwork for a stroller frame logo.

Writes three files (to the current directory unless --out-dir is given):

  yoyo_logo.svg       one logo, exactly 100 mm wide, outlined vector paths
  yoyo_logo.png       the same artwork at 300 DPI on a transparent background
  yoyo_logo_pair.svg  two identical logos stacked with a 15 mm vertical gap

What makes the output plotter friendly:
  * Every character is converted to outline paths. There are no <text>
    elements, so the cutter software never needs the fonts.
  * Overlapping contours are merged with Skia path ops, so the blade never
    cuts across the inside of a letter. Each letter is one closed <path>
    (outer edge plus its counters), which makes weeding predictable.
  * Curves are written as plain cubic Beziers (M/L/C/Z commands only),
    which every cutter program (Cricut, Silhouette, SignMaster, VinylMaster,
    Inkscape, Illustrator) imports correctly.
  * Fills are pure #000000. No strokes, gradients, filters, shadows or
    background shapes, and the SVG uses real millimetre units.

Usage:
  python3 yoyo_logo.py                       # BABYZEN / YOYO with superscript 2
  python3 yoyo_logo.py --model yoyo3         # STOKKE  / YOYO with superscript 3
  python3 yoyo_logo.py --model yoyo          # BABYZEN / YOYO, no superscript
  python3 yoyo_logo.py --brand STOKKE --sup 2
  python3 yoyo_logo.py --width-mm 120 --pair-gap-mm 20

Dependencies (all from PyPI; both fonts are SIL Open Font License):
  pip install fonttools skia-pathops pillow font-fredoka-one font-hanken-grotesk
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REQUIREMENTS = "fonttools skia-pathops pillow font-fredoka-one font-hanken-grotesk"

try:
    import pathops
    from fontTools.pens.basePen import BasePen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from PIL import Image, ImageChops, ImageDraw
except ImportError as exc:  # pragma: no cover - environment guard
    sys.exit(f"Missing dependency '{exc.name}'. Install with:\n  pip install {REQUIREMENTS}")


# --------------------------------------------------------------------------
# Content and design settings
# --------------------------------------------------------------------------

# model key -> (line 1 brand, line 2 model name, superscript)
MODELS = {
    "yoyo2": ("BABYZEN", "YOYO", "2"),
    "yoyo3": ("STOKKE", "YOYO", "3"),
    "yoyo": ("BABYZEN", "YOYO", ""),
}

SVG_NAME = "yoyo_logo.svg"
PNG_NAME = "yoyo_logo.png"
PAIR_NAME = "yoyo_logo_pair.svg"


@dataclass(frozen=True)
class Style:
    # Line 1 cap height as a fraction of line 2 cap height.
    brand_cap_ratio: float = 0.30
    # Line 1 is tracked out so it spans exactly the width of the model word.
    # This is the floor for that tracking (in em of the line 1 type size).
    brand_min_tracking_em: float = 0.35
    # Extra letter-spacing on the bold model word (em of the line 2 size).
    model_tracking_em: float = 0.07
    # Clear vertical space between the two lines, as a fraction of the
    # line 2 cap height.
    line_gap_ratio: float = 0.34
    # Superscript figure height as a fraction of the line 2 cap height.
    # It is the font's own bold figure scaled down (not the thin ² glyph),
    # so the strokes stay thick enough to cut and weed cleanly.
    sup_height_ratio: float = 0.44
    # Horizontal space between the last letter and the superscript (em).
    sup_gap_em: float = 0.05


# --------------------------------------------------------------------------
# Font discovery
# --------------------------------------------------------------------------

# Entries are either ("python_package", "file in package/files") or a bare
# font file name to look for in the usual system font folders.
MODEL_FONTS = [  # bold, rounded geometric sans
    ("font_fredoka_one", "FredokaOne-Regular.ttf"),
    "FredokaOne-Regular.ttf",
    "Fredoka-Bold.ttf",
    "Nunito-Black.ttf",
    "Nunito-ExtraBold.ttf",
    "VarelaRound-Regular.ttf",
    "Arial Rounded Bold.ttf",
    "ARLRDBD.TTF",
    "Montserrat-ExtraBold.ttf",
    "Inter-ExtraBold.otf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "Arial Bold.ttf",
    "arialbd.ttf",
]
BRAND_FONTS = [  # clean sans for the tracked uppercase line
    ("font_hanken_grotesk", "HankenGrotesk-SemiBold.otf"),
    "HankenGrotesk-SemiBold.otf",
    "Montserrat-SemiBold.ttf",
    "Inter-SemiBold.otf",
    "Inter-SemiBold.ttf",
    "SourceSansPro-Semibold.otf",
    "Roboto-Medium.ttf",
    "LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "Arial Bold.ttf",
    "arialbd.ttf",
]
FONT_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
    "~/Library/Fonts",
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
]
_system_font_index: dict[str, str] | None = None


def _system_fonts() -> dict[str, str]:
    global _system_font_index
    if _system_font_index is None:
        _system_font_index = {}
        for root in FONT_DIRS:
            root = os.path.expanduser(root)
            if not os.path.isdir(root):
                continue
            for dirpath, _, files in os.walk(root):
                for name in files:
                    if name.lower().endswith((".ttf", ".otf", ".ttc")):
                        _system_font_index.setdefault(name.lower(), os.path.join(dirpath, name))
    return _system_font_index


def find_font(candidates: list, override: str | None, role: str) -> str:
    if override:
        if not os.path.isfile(override):
            sys.exit(f"--{role}-font: file not found: {override}")
        return override
    for cand in candidates:
        if isinstance(cand, tuple):
            spec = importlib.util.find_spec(cand[0])
            if spec and spec.submodule_search_locations:
                path = os.path.join(spec.submodule_search_locations[0], "files", cand[1])
                if os.path.isfile(path):
                    return path
        else:
            path = _system_fonts().get(cand.lower())
            if path:
                return path
    sys.exit(f"No usable {role} font found. Install the bundled ones with:\n  pip install {REQUIREMENTS}")


class Font:
    """Thin wrapper around a TTFont that draws glyphs into a pathops Path."""

    def __init__(self, path: str):
        self.path = path
        self.tt = TTFont(path, fontNumber=0) if path.lower().endswith(".ttc") else TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upem = self.tt["head"].unitsPerEm
        self.hmtx = self.tt["hmtx"]
        cap = getattr(self.tt["OS/2"], "sCapHeight", 0) if "OS/2" in self.tt else 0
        if not cap:  # older fonts: measure the H
            probe = pathops.Path()
            self.draw_char("H", probe, 1.0, 0.0, 0.0)
            cap = -probe.bounds[1]
        self.cap_height = cap
        self.name = self.tt["name"].getDebugName(4) or os.path.basename(path)

    def draw_char(self, ch: str, path: "pathops.Path", scale: float, x: float, baseline: float) -> float:
        """Draw one character with its origin at (x, baseline), y axis pointing
        down. Returns the scaled advance width."""
        glyph = self.cmap.get(ord(ch))
        if glyph is None:
            sys.exit(f"Font {self.name} has no glyph for {ch!r}")
        self.glyphs[glyph].draw(TransformPen(path.getPen(), (scale, 0, 0, -scale, x, baseline)))
        return self.hmtx[glyph][0] * scale


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def build_line(font: Font, text: str, scale: float, tracking: float, baseline: float = 0.0) -> "pathops.Path":
    """Set a line of text as one overlap-free outline path."""
    line = pathops.Path()
    x = 0.0
    for i, ch in enumerate(text):
        glyph = pathops.Path()
        x += font.draw_char(ch, glyph, scale, x, baseline)
        glyph.simplify(fix_winding=True)  # normalise winding, drop self-overlaps
        line.addPath(glyph)
        if i < len(text) - 1:
            x += tracking
    line.simplify(fix_winding=True)  # merge any glyph-to-glyph overlaps
    return line


def moved(path: "pathops.Path", dx: float, dy: float, k: float = 1.0) -> "pathops.Path":
    return path.transform(k, 0, 0, k, dx, dy)


@dataclass
class Layout:
    brand: "pathops.Path"
    model: "pathops.Path"
    brand_cap: float
    model_cap: float
    brand_tracking_em: float


def compose(brand: str, word: str, sup: str, brand_font: Font, model_font: Font, style: Style) -> Layout:
    unit = 1000.0  # layout units per model em; y axis points down; line 2 baseline at y=0
    ms = unit / model_font.upem
    model_cap = model_font.cap_height * ms

    # Line 2: the bold model word.
    model = build_line(model_font, word, ms, style.model_tracking_em * unit)
    wx0, _, wx1, _ = model.bounds

    # Superscript: the same bold figure, scaled, top aligned to cap height.
    if sup:
        probe = build_line(model_font, sup, ms, 0.0)
        figure_height = probe.bounds[3] - probe.bounds[1]
        k = style.sup_height_ratio * model_cap / figure_height
        sup_path = build_line(model_font, sup, ms * k, 0.0)
        sx0, sy0, _, _ = sup_path.bounds
        model.addPath(moved(sup_path, wx1 + style.sup_gap_em * unit - sx0, -model_cap - sy0))
        model.simplify(fix_winding=True)

    # Line 1: small tracked caps, justified to the width of the model word.
    brand_cap = style.brand_cap_ratio * model_cap
    brand_path = pathops.Path()
    tracking_em = 0.0
    if brand:
        bs = brand_cap / brand_font.cap_height
        brand_em = brand_font.upem * bs
        probe = build_line(brand_font, brand, bs, 0.0)
        natural = probe.bounds[2] - probe.bounds[0]
        gaps = len(brand) - 1
        tracking = (wx1 - wx0 - natural) / gaps if gaps else 0.0
        tracking = max(tracking, style.brand_min_tracking_em * brand_em)
        tracking_em = tracking / brand_em
        baseline = -model_cap - style.line_gap_ratio * model_cap
        brand_path = build_line(brand_font, brand, bs, tracking, baseline)
        bx0, _, bx1, _ = brand_path.bounds
        brand_path = moved(brand_path, (wx0 + wx1) / 2 - (bx0 + bx1) / 2, 0.0)

    return Layout(brand_path, model, brand_cap, model_cap, tracking_em)


def to_millimetres(layout: Layout, width_mm: float) -> tuple[Layout, float]:
    """Scale the artwork so its ink is exactly width_mm wide, with the top
    left of the ink at (0, 0). Returns the scaled layout and its height."""
    boxes = [p.bounds for p in (layout.brand, layout.model) if list(p.contours)]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    k = width_mm / (x1 - x0)
    scaled = Layout(
        moved(layout.brand, -x0 * k, -y0 * k, k),
        moved(layout.model, -x0 * k, -y0 * k, k),
        layout.brand_cap * k,
        layout.model_cap * k,
        layout.brand_tracking_em,
    )
    return scaled, (y1 - y0) * k


def split_shapes(path: "pathops.Path") -> list["pathops.Path"]:
    """Split a simplified path into one closed shape per letter: each outer
    contour together with the counters (holes) that sit inside it."""
    contours = list(path.contours)
    if not contours:
        return []
    outer_dir = max(contours, key=lambda c: abs(c.area)).clockwise
    outers = [c for c in contours if c.clockwise == outer_dir]
    holes = [c for c in contours if c.clockwise != outer_dir]
    shapes = [[o] for o in outers]
    for hole in holes:
        start = hole.firstPoints[0]
        owners = [i for i, o in enumerate(outers) if o.contains(start)]
        if owners:
            shapes[min(owners, key=lambda i: abs(outers[i].area))].append(hole)
        else:
            shapes.append([hole])
    result = []
    for parts in shapes:
        shape = pathops.Path()
        for part in parts:
            shape.addPath(part)
        result.append(shape)
    result.sort(key=lambda s: (s.bounds[0], s.bounds[1]))
    return result


# --------------------------------------------------------------------------
# SVG output
# --------------------------------------------------------------------------

def fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class CubicSvgPen(BasePen):
    """Serialises a path using only M, L, C and Z commands. BasePen converts
    quadratic segments to cubics for us."""

    def __init__(self):
        super().__init__(None)
        self.out: list[str] = []

    def _pt(self, p) -> str:
        return f"{fmt(p[0])} {fmt(p[1])}"

    def _moveTo(self, p):
        self.out.append(f"M{self._pt(p)}")

    def _lineTo(self, p):
        self.out.append(f"L{self._pt(p)}")

    def _curveToOne(self, p1, p2, p3):
        self.out.append(f"C{self._pt(p1)} {self._pt(p2)} {self._pt(p3)}")

    def _closePath(self):
        self.out.append("Z")

    def _endPath(self):
        self.out.append("Z")  # cut paths are always closed


def path_d(path: "pathops.Path") -> str:
    pen = CubicSvgPen()
    path.draw(pen)
    return "".join(pen.out)


def svg_logo_group(layout: Layout, copy_id: str, dy: float, indent: str) -> list[str]:
    lines = [f'{indent}<g id="{copy_id}">']
    for part, path in (("brand", layout.brand), ("model", layout.model)):
        shapes = split_shapes(moved(path, 0.0, dy))
        if not shapes:
            continue
        lines.append(f'{indent}  <g id="{copy_id}-{part}">')
        for n, shape in enumerate(shapes, 1):
            lines.append(f'{indent}    <path id="{copy_id}-{part}-{n:02d}" fill="#000000" d="{path_d(shape)}"/>')
        lines.append(f"{indent}  </g>")
    lines.append(f"{indent}</g>")
    return lines


def write_svg(file: Path, layout: Layout, width_mm: float, logo_h: float, copies: int, gap_mm: float, label: str) -> float:
    height = copies * logo_h + (copies - 1) * gap_mm
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{fmt(width_mm)}mm" height="{fmt(height)}mm" viewBox="0 0 {fmt(width_mm)} {fmt(height)}">',
        f"  <!-- {label}: {copies} x ({fmt(width_mm)} x {fmt(logo_h)} mm)"
        + (f", {fmt(gap_mm)} mm vertical gap" if copies > 1 else "")
        + ". Outlined paths, solid #000000 fill, transparent background. 1 user unit = 1 mm. -->",
    ]
    for i in range(copies):
        out += svg_logo_group(layout, f"logo-{i + 1}", i * (logo_h + gap_mm), "  ")
    out.append("</svg>")
    file.write_text("\n".join(out) + "\n", encoding="utf-8")
    return height


# --------------------------------------------------------------------------
# PNG output
# --------------------------------------------------------------------------

class FlattenPen(BasePen):
    """Turns curves into short line segments for rasterising."""

    def __init__(self, max_step: float):
        super().__init__(None)
        self.max_step = max_step
        self.contours: list[list[tuple[float, float]]] = []

    def _moveTo(self, p):
        self.contours.append([p])

    def _lineTo(self, p):
        self.contours[-1].append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        length = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
        n = max(2, math.ceil(length / self.max_step))
        for i in range(1, n + 1):
            t = i / n
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            self.contours[-1].append(
                (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])
            )

    def _closePath(self):
        pass

    def _endPath(self):
        pass


def write_png(file: Path, layout: Layout, width_mm: float, height_mm: float, dpi: int, ss: int = 8) -> tuple[int, int]:
    """Rasterise with 8x8 supersampling (64 levels of edge coverage), then
    store pure black pixels with the coverage as the alpha channel."""
    w = round(width_mm / 25.4 * dpi)
    px_per_mm = w / width_mm
    h = max(1, round(height_mm * px_per_mm))
    f = px_per_mm * ss
    mask = Image.new("1", (w * ss, h * ss), 0)
    for path in (layout.brand, layout.model):
        pen = FlattenPen(max_step=2.0)
        path.transform(f, 0, 0, f, 0, 0).draw(pen)
        # Contours are overlap free after simplify(), so XOR-ing each filled
        # contour gives the correct result: counters punch holes in letters.
        for pts in pen.contours:
            if len(pts) < 3:
                continue
            pts = [(x - 0.5, y - 0.5) for x, y in pts]  # Pillow samples pixel centres
            box = (
                max(0, math.floor(min(p[0] for p in pts))),
                max(0, math.floor(min(p[1] for p in pts))),
                min(w * ss, math.ceil(max(p[0] for p in pts)) + 1),
                min(h * ss, math.ceil(max(p[1] for p in pts)) + 1),
            )
            tile = Image.new("1", (box[2] - box[0], box[3] - box[1]), 0)
            ImageDraw.Draw(tile).polygon([(x - box[0], y - box[1]) for x, y in pts], fill=1)
            mask.paste(ImageChops.logical_xor(mask.crop(box), tile), box)
    alpha = mask.convert("L").resize((w, h), Image.Resampling.BOX)
    black = Image.new("L", (w, h), 0)
    Image.merge("RGBA", (black, black, black, alpha)).save(file, dpi=(dpi, dpi), optimize=True)
    return w, h


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

FORBIDDEN_TAGS = {
    "text", "tspan", "textPath", "font", "linearGradient", "radialGradient", "pattern",
    "filter", "image", "mask", "clipPath", "style", "use", "rect", "circle", "ellipse",
}


def check_svg(file: Path, width_mm: float, expect_height: float, expect_copies: int) -> tuple[list[str], int]:
    problems = []
    root = ET.parse(file).getroot()
    ns = "{http://www.w3.org/2000/svg}"
    if root.tag != f"{ns}svg":
        problems.append("root element is not <svg>")
    if root.get("width") != f"{fmt(width_mm)}mm":
        problems.append(f"width is {root.get('width')}, expected {fmt(width_mm)}mm")
    if root.get("height") != f"{fmt(expect_height)}mm":
        problems.append(f"height is {root.get('height')}, expected {fmt(expect_height)}mm")
    vb = [float(v) for v in root.get("viewBox", "").split()]
    if len(vb) != 4 or vb[2] != float(fmt(width_mm)) or vb[3] != float(fmt(expect_height)):
        problems.append(f"viewBox {root.get('viewBox')} does not match the mm size")
    paths = 0
    for el in root.iter():
        tag = el.tag.replace(ns, "")
        if tag in FORBIDDEN_TAGS:
            problems.append(f"forbidden <{tag}> element")
        for attr in ("stroke", "style", "opacity", "filter", "fill-opacity"):
            if el.get(attr) is not None:
                problems.append(f"<{tag}> has a '{attr}' attribute")
        if tag == "path":
            paths += 1
            if el.get("fill") != "#000000":
                problems.append(f"path {el.get('id')} fill is {el.get('fill')}")
            if set(el.get("d", "")) - set("MLCZ0123456789.- "):
                problems.append(f"path {el.get('id')} uses unexpected path commands")
    copies = sum(1 for g in root.findall(f"{ns}g"))
    if copies != expect_copies:
        problems.append(f"found {copies} logo copies, expected {expect_copies}")
    return problems, paths


def check_png(file: Path, size: tuple[int, int], dpi: int) -> list[str]:
    problems = []
    with Image.open(file) as img:
        img.load()
        if img.mode != "RGBA":
            problems.append(f"mode is {img.mode}, expected RGBA")
            return problems
        if img.size != size:
            problems.append(f"size is {img.size}, expected {size}")
        got = img.info.get("dpi", (0, 0))
        if any(abs(v - dpi) > 0.5 for v in got):
            problems.append(f"DPI metadata is {got}, expected {dpi}")
        r, g, b, a = img.split()
        if any(ch.getextrema() != (0, 0) for ch in (r, g, b)):
            problems.append("some pixels are not pure black (#000000)")
        if a.getextrema() != (0, 255):
            problems.append(f"alpha range is {a.getextrema()}, expected (0, 255)")
        hist = a.histogram()
        if hist[0] / sum(hist) < 0.2:
            problems.append("background does not look transparent")
    return problems


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate vinyl-cutter ready stroller logo files.")
    ap.add_argument("--model", choices=sorted(MODELS), default="yoyo2",
                    help="yoyo2 = BABYZEN / YOYO2 (default), yoyo3 = STOKKE / YOYO3, yoyo = BABYZEN / YOYO")
    ap.add_argument("--brand", help="override the line 1 text (uppercased)")
    ap.add_argument("--word", help="override the line 2 text (uppercased)")
    ap.add_argument("--sup", help="override the superscript, e.g. 2, 3, or '' for none")
    ap.add_argument("--width-mm", type=float, default=100.0, help="total logo width in mm (default 100)")
    ap.add_argument("--pair-gap-mm", type=float, default=15.0, help="gap between the two copies (default 15)")
    ap.add_argument("--dpi", type=int, default=300, help="PNG resolution (default 300)")
    ap.add_argument("--brand-font", help="path to a .ttf/.otf for line 1")
    ap.add_argument("--model-font", help="path to a .ttf/.otf for line 2")
    ap.add_argument("--out-dir", default=".", help="output folder (default: current directory)")
    args = ap.parse_args()

    brand, word, sup = MODELS[args.model]
    brand = (args.brand if args.brand is not None else brand).upper()
    word = (args.word if args.word is not None else word).upper()
    sup = args.sup if args.sup is not None else sup
    if not word:
        sys.exit("Line 2 text cannot be empty")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    brand_font = Font(find_font(BRAND_FONTS, args.brand_font, "brand"))
    model_font = Font(find_font(MODEL_FONTS, args.model_font, "model"))

    layout, logo_h = to_millimetres(compose(brand, word, sup, brand_font, model_font, Style()), args.width_mm)
    label = f"{brand} {word}{sup}".strip()

    svg_file, png_file, pair_file = out_dir / SVG_NAME, out_dir / PNG_NAME, out_dir / PAIR_NAME
    write_svg(svg_file, layout, args.width_mm, logo_h, 1, 0.0, label)
    pair_h = write_svg(pair_file, layout, args.width_mm, logo_h, 2, args.pair_gap_mm, label)
    png_size = write_png(png_file, layout, args.width_mm, logo_h, args.dpi)

    print(f"Logo        : {label}  (line 1 '{brand}', line 2 '{word}' + superscript '{sup or '-'}')")
    print(f"Fonts       : line 1 {brand_font.name}  |  line 2 {model_font.name}")
    print(f"Size        : {fmt(args.width_mm)} x {logo_h:.2f} mm  "
          f"(cap heights: line 1 {layout.brand_cap:.2f} mm, line 2 {layout.model_cap:.2f} mm; "
          f"line 1 tracking {layout.brand_tracking_em:.2f} em)")
    print(f"Pair sheet  : {fmt(args.width_mm)} x {pair_h:.2f} mm  (2 copies, {fmt(args.pair_gap_mm)} mm gap)")

    print("\nVerification:")
    failures = 0
    for file, (problems, paths) in (
        (svg_file, check_svg(svg_file, args.width_mm, logo_h, 1)),
        (pair_file, check_svg(pair_file, args.width_mm, pair_h, 2)),
    ):
        failures += len(problems)
        status = "OK " if file.exists() and not problems else "FAIL"
        print(f"  [{status}] {file}  {file.stat().st_size:,} bytes, {paths} closed paths")
        for p in problems:
            print(f"         - {p}")
    problems = check_png(png_file, png_size, args.dpi)
    failures += len(problems)
    status = "OK " if png_file.exists() and not problems else "FAIL"
    print(f"  [{status}] {png_file}  {png_file.stat().st_size:,} bytes, "
          f"{png_size[0]} x {png_size[1]} px @ {args.dpi} DPI, RGBA transparent")
    for p in problems:
        print(f"         - {p}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
