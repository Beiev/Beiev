#!/usr/bin/env python3
"""Build the SVG assets of the Beiev GitHub profile README.

Every SVG is self-contained: fonts are subset to the glyphs each file uses and
embedded as WOFF2 data URIs, because GitHub serves README images through a
proxy where external fonts and scripts do not load. Motion is CSS only and
stops under ``prefers-reduced-motion``.

Usage:
    python tools/build_assets.py FONT_DIR OUT_DIR

FONT_DIR holds the OFL variable fonts from github.com/google/fonts:
``SpaceGrotesk.ttf`` (ofl/spacegrotesk) and ``JetBrainsMono.ttf``
(ofl/jetbrainsmono). Requires ``fonttools`` and ``brotli``.
"""

from __future__ import annotations

import base64
import io
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

# Palette of rzmrn.com (src/app/globals.css).
BG = "#050505"
BORDER = "#1F1F1F"
TEXT = "#EDEDED"
TEXT_SOFT = "#B4B4B4"
SECOND = "#808080"
MUTED = "#4A4A4A"
ACCENT = "#3B82F6"
ACCENT_SOFT = "#60A5FA"

HEADER_W, HEADER_H = 1200, 420
CARD_W, CARD_H = 1200, 320
RADIUS = 18
PAD_X = 64
SEED = 1307

WARM = (255, 214, 170)
WARM_CORE = (255, 228, 196)
COOL = (150, 180, 255)
KNOT = (222, 232, 255)
HII = (232, 168, 186)

MAX_DESC_LINES = 3

class Face:
    """One static font instance that measures text and embeds a subset."""

    def __init__(self, path: Path, weight: int, family: str, fallback: str) -> None:
        font = instancer.instantiateVariableFont(TTFont(path), {"wght": weight})
        buf = io.BytesIO()
        font.save(buf)
        self._blob = buf.getvalue()
        self.family = family
        self.weight = weight
        self.stack = f"{family}, {fallback}"
        self.upm = font["head"].unitsPerEm
        self._cmap = font.getBestCmap()
        self._hmtx = font["hmtx"]

    def width(self, text: str, size: float) -> float:
        """Advance width of ``text`` at ``size`` px, without kerning."""
        total = 0
        for ch in text:
            glyph = self._cmap.get(ord(ch))
            if glyph is None:
                raise ValueError(f"{self.family} has no glyph for {ch!r}")
            total += self._hmtx[glyph][0]
        return total * size / self.upm

    def font_face(self, chars: set[str]) -> str:
        """CSS @font-face with a WOFF2 subset limited to ``chars``."""
        font = TTFont(io.BytesIO(self._blob))
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["kern", "liga", "calt"]
        options.name_IDs = []
        options.notdef_outline = True
        sub = subset.Subsetter(options)
        sub.populate(text="".join(sorted(chars | {" "})))
        sub.subset(font)
        out = io.BytesIO()
        font.flavor = "woff2"
        font.save(out)
        data = base64.b64encode(out.getvalue()).decode("ascii")
        return (
            f"@font-face{{font-family:{self.family};font-weight:{self.weight};"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}"
        )


@dataclass
class Doc:
    """Collects SVG body parts and the glyphs used per font face."""

    width: int
    height: int
    title: str
    desc: str
    parts: list[str] = field(default_factory=list)
    defs: list[str] = field(default_factory=list)
    css: list[str] = field(default_factory=list)
    used: dict[str, tuple[Face, set[str]]] = field(default_factory=dict)

    def text(
        self,
        face: Face,
        s: str,
        x: float,
        y: float,
        size: float,
        fill: str,
        *,
        extra: str = "",
        spacing: float = 0.0,
        anchor: str = "start",
    ) -> str:
        """Return a <text> element and register its glyphs."""
        self.used.setdefault(face.family, (face, set()))[1].update(s)
        ls = f' letter-spacing="{spacing:g}"' if spacing else ""
        an = f' text-anchor="{anchor}"' if anchor != "start" else ""
        return (
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{face.stack}" font-weight="{face.weight}" '
            f'font-size="{size:g}" fill="{fill}"{ls}{an}{extra}>{escape(s)}</text>'
        )

    def render(self) -> str:
        """Serialize the document."""
        faces = "".join(f.font_face(chars) for f, chars in self.used.values())
        style = faces + "".join(self.css)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" role="img" aria-labelledby="t d">'
            f'<title id="t">{escape(self.title)}</title><desc id="d">{escape(self.desc)}</desc>'
            f"<defs><style>{style}</style>{''.join(self.defs)}</defs>"
            f"{''.join(self.parts)}</svg>\n"
        )


def rgb(c: tuple[float, float, float]) -> str:
    """Hex color from an RGB tuple."""
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in c)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[float, float, float]:
    """Linear blend of two RGB colors."""
    return tuple(x + (y - x) * t for x, y in zip(a, b))  # type: ignore[return-value]


def frame(doc: Doc, clip_id: str) -> None:
    """Rounded background and the clip that keeps the sky inside it."""
    w, h = doc.width, doc.height
    doc.defs.append(
        f'<clipPath id="{clip_id}"><rect x="0" y="0" width="{w}" height="{h}" rx="{RADIUS}"/></clipPath>'
    )
    doc.parts.append(f'<rect x="0" y="0" width="{w}" height="{h}" rx="{RADIUS}" fill="{BG}"/>')


def border(doc: Doc) -> None:
    """Hairline border drawn on top, so the card reads on light pages too."""
    w, h = doc.width, doc.height
    doc.parts.append(
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="{RADIUS - 0.5}" '
        f'fill="none" stroke="{BORDER}"/>'
    )


def starfield(rng: random.Random, w: int, h: int, count: int, twinkle: int) -> str:
    """Faint static stars plus a few that twinkle."""
    out = []
    for i in range(count):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.choice((0.5, 0.6, 0.7, 0.8, 1.0, 1.2))
        op = rng.uniform(0.15, 0.55)
        col = rgb(mix((255, 255, 255), COOL, rng.uniform(0, 0.5)))
        if i < twinkle:
            dur = rng.uniform(3.0, 7.0)
            delay = rng.uniform(0, 6.0)
            out.append(
                f'<circle class="tw" cx="{x:.1f}" cy="{y:.1f}" r="{r + 0.3:.1f}" fill="{col}" '
                f'style="animation-duration:{dur:.1f}s;animation-delay:-{delay:.1f}s"/>'
            )
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}" opacity="{op:.2f}"/>')
    return "".join(out)


def galaxy(
    rng: random.Random,
    radius: float,
    *,
    arms: int = 2,
    arm_points: int = 260,
    bulge_points: int = 140,
    disk_points: int = 110,
    pitch_deg: float = 14.0,
    jitter: float = 0.07,
    tint: tuple[int, int, int] = COOL,
) -> str:
    """Dots of a log-spiral galaxy centered on the origin, warm core and cool arms."""
    out = []
    r0 = 0.12 * radius
    turn = 1.0 / math.tan(math.radians(pitch_deg))

    def dot(x: float, y: float, r: float, col: tuple[float, float, float], op: float) -> None:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{rgb(col)}" opacity="{op:.2f}"/>')

    for _ in range(disk_points):
        rr = radius * math.sqrt(rng.random())
        th = rng.uniform(0, 2 * math.pi)
        dot(rr * math.cos(th), rr * math.sin(th), rng.uniform(0.5, 0.9), tint, rng.uniform(0.08, 0.25))
    for a in range(arms):
        base = a * 2 * math.pi / arms
        for _ in range(arm_points):
            t = rng.random() ** 0.85
            rr = r0 + (radius - r0) * t
            th = base + math.log(rr / r0) * turn
            sigma = jitter * radius * (0.35 + 0.9 * t)
            x = rr * math.cos(th) + rng.gauss(0, sigma)
            y = rr * math.sin(th) + rng.gauss(0, sigma)
            roll = rng.random()
            if roll < 0.04:
                dot(x, y, rng.uniform(1.4, 2.0), KNOT, rng.uniform(0.6, 0.95))
            elif roll < 0.06:
                dot(x, y, rng.uniform(1.0, 1.6), HII, rng.uniform(0.35, 0.6))
            else:
                col = mix(WARM, tint, min(1.0, t * 1.25))
                dot(x, y, rng.uniform(0.6, 1.4), col, (0.3 + 0.55 * rng.random()) * (1 - 0.45 * t))
    for _ in range(bulge_points):
        rr = abs(rng.gauss(0, 0.13 * radius))
        th = rng.uniform(0, 2 * math.pi)
        dot(rr * math.cos(th), rr * math.sin(th), rng.uniform(0.6, 1.5), WARM_CORE, rng.uniform(0.4, 0.9))
    return "".join(out)


def galaxy_glow(doc: Doc, gid: str, radius: float, tint: tuple[int, int, int] = COOL) -> str:
    """Soft warm core and cool halo, drawn under the dots."""
    doc.defs.append(
        f'<radialGradient id="{gid}c"><stop offset="0" stop-color="{rgb(WARM_CORE)}" stop-opacity="0.75"/>'
        f'<stop offset="0.35" stop-color="{rgb(WARM)}" stop-opacity="0.22"/>'
        f'<stop offset="1" stop-color="{rgb(WARM)}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="{gid}h"><stop offset="0" stop-color="{rgb(tint)}" stop-opacity="0.14"/>'
        f'<stop offset="1" stop-color="{rgb(tint)}" stop-opacity="0"/></radialGradient>'
    )
    return (
        f'<circle r="{radius * 1.15:.1f}" fill="url(#{gid}h)"/>'
        f'<circle r="{radius * 0.34:.1f}" fill="url(#{gid}c)"/>'
    )


BASE_CSS = (
    ".tw{animation-name:tw;animation-iteration-count:infinite;animation-timing-function:ease-in-out}"
    "@keyframes tw{0%,100%{opacity:.15}50%{opacity:.9}}"
    ".spin{animation:spin 160s linear infinite}"
    "@keyframes spin{to{transform:rotate(360deg)}}"
    ".up{animation:up 1.2s cubic-bezier(.16,1,.3,1) backwards}"
    "@keyframes up{from{opacity:0;transform:translateY(16px)}}"
    ".fade{animation:fade 2.6s ease-out backwards}"
    "@keyframes fade{from{opacity:0}}"
    ".core{animation:breathe 7s ease-in-out infinite}"
    "@keyframes breathe{50%{opacity:.55}}"
    ".m{opacity:0;animation-timing-function:linear;animation-iteration-count:infinite}"
    "@keyframes mL{0%{opacity:0;transform:translate(0,0)}1.5%{opacity:1}"
    "7%{opacity:0;transform:translate(-240px,84px)}100%{opacity:0;transform:translate(-240px,84px)}}"
    "@keyframes mS{0%{opacity:0;transform:translate(0,0)}1.5%{opacity:1}"
    "6%{opacity:0;transform:translate(-160px,56px)}100%{opacity:0;transform:translate(-160px,56px)}}"
    "@media (prefers-reduced-motion:reduce){.tw,.spin,.bar,.m,.up,.fade,.core{animation:none!important}}"
)


@dataclass(frozen=True)
class Meteor:
    """One shooting star: start point, keyframes, cycle length and first delay."""

    x: float
    y: float
    keyframes: str
    period: float
    delay: float


def meteors(doc: Doc, items: tuple[Meteor, ...]) -> str:
    """Shooting stars that cross the sky now and then; hidden under reduced motion."""
    doc.defs.append(
        '<linearGradient id="mt" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity="0.95"/>'
        f'<stop offset="0.35" stop-color="{rgb(COOL)}" stop-opacity="0.45"/>'
        f'<stop offset="1" stop-color="{rgb(COOL)}" stop-opacity="0"/></linearGradient>'
    )
    tail_x, tail_y = 86.0, -30.1
    out = []
    for m in items:
        out.append(
            f'<g transform="translate({m.x:g} {m.y:g})"><g class="m" style="animation-name:{m.keyframes};'
            f'animation-duration:{m.period:g}s;animation-delay:{m.delay:g}s">'
            f'<line x1="0" y1="0" x2="{tail_x}" y2="{tail_y}" stroke="url(#mt)" stroke-width="1.5" '
            'stroke-linecap="round"/><circle r="1.6" fill="#FFFFFF"/></g></g>'
        )
    return "".join(out)


def rise(delay: float) -> str:
    """Attributes for text that rises in on load."""
    return f' class="up" style="animation-delay:{delay:g}s"'


def header_galaxy(doc: Doc, rng: random.Random, x: float, y: float, r: float, **kw: float) -> str:
    """The banner galaxy: tilted disk, breathing core, slow turn, fade-in on load."""
    return (
        f'<g class="fade"><g transform="translate({x:g} {y:g}) rotate(-18) scale(1 0.46)">'
        f'<g class="core">{galaxy_glow(doc, "g1", r)}</g>'
        f'<g class="spin">{galaxy(rng, r, **kw)}</g></g></g>'  # type: ignore[arg-type]
    )


HEADER_DESC = (
    "Dark banner in the style of rzmrn.com: a slowly turning spiral galaxy, "
    "twinkling stars and an occasional shooting star. Agents and automation, "
    "fine-tuning, evals, 10+ years in video."
)


def header(sg_bold: Face, sg: Face, mono: Face) -> str:
    """The banner: name, role, focus line and a slowly turning galaxy."""
    rng = random.Random(SEED)
    doc = Doc(HEADER_W, HEADER_H, "Maksym Beiev — Applied AI Engineer · AI & Automation Lead", HEADER_DESC)
    doc.css.append(BASE_CSS)
    frame(doc, "hf")
    sky = [starfield(rng, HEADER_W, HEADER_H, 170, 50)]
    sky.append(
        header_galaxy(doc, rng, 948, 206, 232, arm_points=430, bulge_points=200, disk_points=150, jitter=0.048)
    )
    sky.append(
        meteors(
            doc,
            (
                Meteor(1180, 110, "mL", 9, 2.2),
                Meteor(1080, 300, "mL", 13, 6.5),
                Meteor(900, 48, "mL", 17, 11),
            ),
        )
    )
    doc.parts.append(f'<g clip-path="url(#hf)">{"".join(sky)}</g>')
    doc.parts.append(doc.text(sg_bold, "RZMRN", PAD_X, 78, 19, TEXT, spacing=0.6, extra=rise(0)))
    doc.parts.append(
        doc.text(
            mono, "EN · PL · UA · RU", HEADER_W - PAD_X, 78, 14, SECOND, spacing=1.6, anchor="end", extra=rise(0)
        )
    )
    doc.parts.append(doc.text(sg_bold, "Maksym Beiev", PAD_X - 3, 216, 80, TEXT, spacing=-1.6, extra=rise(0.1)))
    doc.parts.append(
        doc.text(sg, "Applied AI Engineer · AI & Automation Lead", PAD_X, 266, 27, TEXT_SOFT, extra=rise(0.25))
    )
    doc.parts.append(
        doc.text(
            mono,
            "agents & automation / fine-tuning / evals / 10+ yrs in video",
            PAD_X,
            322,
            16,
            SECOND,
            extra=rise(0.4),
        )
    )
    border(doc)
    return doc.render()


def wrap(face: Face, text: str, size: float, max_w: float) -> list[str]:
    """Greedy word wrap by measured width."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and face.width(trial, size) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


@dataclass(frozen=True)
class Card:
    """Content of one project card."""

    slug: str
    label: str
    title: str
    desc: str
    tags: tuple[str, ...]


Faces = tuple[Face, Face, Face]


@dataclass(frozen=True)
class Layout:
    """Text column geometry of a card."""

    width: int
    x: float
    label_y: float
    title_size: float
    desc_size: float
    wrap_w: float
    pill_size: float
    max_lines: int


WIDE = Layout(CARD_W, 56, 64, 50, 24, 650, 16, 3)
COMPACT_W = 600
COMPACT = Layout(COMPACT_W, 40, 362, 50, 25, 520, 18, 5)
# The visual of a wide card lives in this region; compact cards scale it to full width.
VISUAL_X0, VISUAL_X1, VISUAL_Y0, VISUAL_Y1 = 690.0, 1200.0, 24.0, 300.0


def card_text(doc: Doc, card: Card, faces: Faces, lay: Layout) -> tuple[list[str], float]:
    """Label, title, description and tag pills; returns parts and the bottom y."""
    sg_bold, sg, mono = faces
    parts = [doc.text(mono, card.label, lay.x, lay.label_y, 15, SECOND, spacing=1.8)]
    title_y = lay.label_y + 1.24 * lay.title_size
    parts.append(doc.text(sg_bold, card.title, lay.x - 2, title_y, lay.title_size, TEXT, spacing=-0.8))
    arrow_x = lay.x + sg_bold.width(card.title, lay.title_size) - 0.8 * len(card.title) + 6
    parts.append(doc.text(mono, "↗", arrow_x, title_y - 4, 0.52 * lay.title_size, ACCENT))
    lines = wrap(sg, card.desc, lay.desc_size, lay.wrap_w)
    if len(lines) > lay.max_lines:
        raise ValueError(f"{card.slug}: description takes {len(lines)} lines")
    first = title_y + 2 * lay.desc_size
    step = 1.333 * lay.desc_size
    for i, line in enumerate(lines):
        parts.append(doc.text(sg, line, lay.x, first + i * step, lay.desc_size, TEXT_SOFT))
    ph = 2.125 * lay.pill_size
    px, py = lay.x, first + (len(lines) - 1) * step + 16
    for tag in card.tags:
        w = mono.width(tag, lay.pill_size) + 1.9 * lay.pill_size
        if px > lay.x and px + w > lay.x + lay.wrap_w:
            px, py = lay.x, py + ph + 10
        parts.append(
            f'<rect x="{px:.1f}" y="{py:.1f}" width="{w:.1f}" height="{ph:.1f}" rx="{ph / 2:.1f}" '
            f'fill="#0D0D0D" stroke="{BORDER}"/>'
        )
        parts.append(
            doc.text(mono, tag, px + 0.95 * lay.pill_size, py + 0.7 * ph, lay.pill_size, SECOND)
        )
        px += w + 10
    return parts, py + ph


def chronicle_visual(doc: Doc, rng: random.Random) -> str:
    """Atlas motif in wide-card coordinates: three galaxies over a river of time."""
    sky = []
    for _ in range(260):
        u = rng.random()
        x = 690 + u * 520
        y = 278 + 10 * math.sin(u * 5.5) + rng.gauss(0, 5)
        sky.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rng.uniform(0.4, 1.0):.1f}" '
            f'fill="{rgb(mix(COOL, WARM, u))}" opacity="{rng.uniform(0.15, 0.5):.2f}"/>'
        )
    for gid, (gx, gy, gr, rot, tint, n) in {
        "a": (930, 140, 108, -24, COOL, 170),
        "b": (1095, 82, 36, 30, (150, 220, 210), 50),
        "c": (790, 218, 30, -50, (240, 200, 150), 40),
    }.items():
        sky.append(f'<g transform="translate({gx} {gy}) rotate({rot}) scale(1 0.5)">')
        sky.append(galaxy_glow(doc, f"c{gid}", gr, tint))
        dots = galaxy(rng, gr, arm_points=n, bulge_points=n // 2, disk_points=n // 3, tint=tint)
        sky.append(f'<g class="spin">{dots}</g></g>')
    return "".join(sky)


WAVE_CSS = (
    ".bar{transform-box:fill-box;transform-origin:center;animation:wave 1.6s ease-in-out infinite}"
    "@keyframes wave{0%,100%{transform:scaleY(.35)}50%{transform:scaleY(1)}}"
    ".pulse{animation:pulse 1.8s ease-in-out infinite}"
    "@keyframes pulse{50%{opacity:.25}}"
    "@media (prefers-reduced-motion:reduce){.pulse{animation:none!important}}"
)


def localflow_visual(doc: Doc, rng: random.Random, mono: Face) -> str:
    """Live waveform, a live transcript line and a status chip, in wide-card coordinates."""
    cx, cy, bars, step = 945.0, 128.0, 44, 9.0
    x_start = cx - (bars - 1) * step / 2
    out = []
    for i in range(bars):
        u = i / (bars - 1)
        env = math.sin(math.pi * u) ** 0.8 * (0.55 + 0.45 * abs(math.sin(u * 9.1 + 0.6)))
        h = max(6.0, 112 * env * rng.uniform(0.7, 1.0))
        col = ACCENT if 0.3 < u < 0.7 else ACCENT_SOFT
        op = 0.35 + 0.6 * math.sin(math.pi * u)
        out.append(
            f'<rect class="bar" x="{x_start + i * step - 2:.1f}" y="{cy - h / 2:.1f}" width="4" '
            f'height="{h:.1f}" rx="2" fill="{col}" opacity="{op:.2f}" '
            f'style="animation-delay:-{(i * 0.137) % 1.6:.2f}s"/>'
        )
    # A live transcript line: settled words bright, the draft tail still dim.
    said, draft, size = "every word stays", "on your Mac", 18.0
    tx = cx - mono.width(f"{said} {draft}", size) / 2
    out.append(doc.text(mono, said, tx, 222, size, TEXT))
    out.append(doc.text(mono, draft, tx + mono.width(said + " ", size), 222, size, MUTED))
    # Status chip with a pulsing dot instead of a keyboard shortcut.
    label, lsize = "LIVE · ON DEVICE", 13.0
    cw = mono.width(label, lsize) + 1.6 * len(label) + 52
    ch = 34.0
    chx, chy = cx - cw / 2, 248.0
    out.append(
        f'<rect x="{chx:.1f}" y="{chy:.1f}" width="{cw:.1f}" height="{ch}" rx="{ch / 2}" '
        f'fill="#0D0D0D" stroke="{BORDER}"/>'
        f'<circle class="pulse" cx="{chx + 20:.1f}" cy="{chy + ch / 2:.1f}" r="4" fill="{ACCENT_SOFT}"/>'
    )
    out.append(doc.text(mono, label, chx + 34, chy + 22, lsize, SECOND, spacing=1.6))
    return "".join(out)


CHRONICLE = Card(
    "chronicle",
    "OPEN SOURCE · PYTHON · MIT",
    "Chronicle",
    "Local-first shared memory for AI agents. Decisions, evidence and working "
    "state outlive the chat, so the next agent picks up where the last one stopped.",
    ("MCP", "SQLite", "CLI", "Atlas UI"),
)
LOCALFLOW = Card(
    "localflow",
    "OPEN SOURCE · SWIFT · MIT",
    "LocalFlow",
    "Dictation, voice notes and meeting memory for macOS. One shortcut, speak "
    "anywhere: every model runs on your Mac, with no cloud and no subscription.",
    ("Apple Silicon", "MLX", "CoreML", "on-device ASR"),
)
CARD_TITLES = {
    "chronicle": "Chronicle — local-first shared memory for AI agents",
    "localflow": "LocalFlow — local-first dictation for macOS",
}


def build_card(card: Card, faces: Faces, compact: bool) -> str:
    """One project card, wide (text left, visual right) or compact (visual on top)."""
    lay = COMPACT if compact else WIDE
    rng = random.Random(SEED + (1 if card.slug == "chronicle" else 2))
    doc = Doc(lay.width, CARD_H, CARD_TITLES[card.slug], card.desc)
    doc.css.append(BASE_CSS + (WAVE_CSS if card.slug == "localflow" else ""))
    text_parts, bottom = card_text(doc, card, faces, lay)
    if compact:
        doc.height = round(bottom + 40)
    stars = starfield(rng, doc.width, doc.height, 60 if compact else 70, 12)
    if card.slug == "chronicle":
        visual = chronicle_visual(doc, rng)
    else:
        visual = localflow_visual(doc, rng, faces[2])
    if compact:
        s = lay.width / (VISUAL_X1 - VISUAL_X0)
        visual = (
            f'<g transform="scale({s:.4f}) translate({-VISUAL_X0:g} {-VISUAL_Y0:g})">{visual}</g>'
        )
    frame(doc, "cf")
    doc.parts.append(f'<g clip-path="url(#cf)">{stars}{visual}</g>')
    doc.parts.extend(text_parts)
    border(doc)
    return doc.render()


def header_compact(sg_bold: Face, sg: Face, mono: Face) -> str:
    """Narrow-screen banner: the same parts stacked for a phone."""
    rng = random.Random(SEED + 3)
    w, h, x = 600, 620, 40.0
    doc = Doc(w, h, "Maksym Beiev — Applied AI Engineer · AI & Automation Lead", HEADER_DESC)
    doc.css.append(BASE_CSS)
    frame(doc, "hf")
    sky = [starfield(rng, w, h, 100, 28)]
    sky.append(header_galaxy(doc, rng, 395, 158, 160, arm_points=300, bulge_points=140, disk_points=110, jitter=0.05))
    sky.append(meteors(doc, (Meteor(570, 30, "mS", 10, 2.4), Meteor(585, 196, "mS", 15, 7.5))))
    doc.parts.append(f'<g clip-path="url(#hf)">{"".join(sky)}</g>')
    doc.parts.append(doc.text(sg_bold, "RZMRN", x, 62, 19, TEXT, spacing=0.6, extra=rise(0)))
    doc.parts.append(
        doc.text(mono, "EN · PL · UA · RU", w - x, 62, 14, SECOND, spacing=1.6, anchor="end", extra=rise(0))
    )
    doc.parts.append(doc.text(sg_bold, "Maksym", x - 3, 330, 84, TEXT, spacing=-1.6, extra=rise(0.1)))
    doc.parts.append(doc.text(sg_bold, "Beiev", x - 3, 408, 84, TEXT, spacing=-1.6, extra=rise(0.18)))
    doc.parts.append(doc.text(sg, "Applied AI Engineer", x, 462, 29, TEXT_SOFT, extra=rise(0.3)))
    doc.parts.append(doc.text(sg, "AI & Automation Lead", x, 499, 29, TEXT_SOFT, extra=rise(0.36)))
    doc.parts.append(doc.text(mono, "agents & automation / fine-tuning", x, 552, 19, SECOND, extra=rise(0.5)))
    doc.parts.append(doc.text(mono, "evals / 10+ yrs in video", x, 582, 19, SECOND, extra=rise(0.56)))
    border(doc)
    return doc.render()


def main() -> None:
    """Build all assets into OUT_DIR."""
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    font_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    sans = "'Space Grotesk', 'Segoe UI', system-ui, sans-serif"
    sg_bold = Face(font_dir / "SpaceGrotesk.ttf", 600, "SGB", sans)
    sg = Face(font_dir / "SpaceGrotesk.ttf", 400, "SGR", sans)
    mono = Face(font_dir / "JetBrainsMono.ttf", 400, "JBM", "'JetBrains Mono', ui-monospace, monospace")
    faces = (sg_bold, sg, mono)
    builds = {
        "header.svg": lambda: header(*faces),
        "header-compact.svg": lambda: header_compact(*faces),
        "card-chronicle.svg": lambda: build_card(CHRONICLE, faces, compact=False),
        "card-chronicle-compact.svg": lambda: build_card(CHRONICLE, faces, compact=True),
        "card-localflow.svg": lambda: build_card(LOCALFLOW, faces, compact=False),
        "card-localflow-compact.svg": lambda: build_card(LOCALFLOW, faces, compact=True),
    }
    for name, build in builds.items():
        svg = build()
        (out / name).write_text(svg, encoding="utf-8")
        print(f"{name}: {len(svg.encode()) / 1024:.1f} KiB")


if __name__ == "__main__":
    main()
