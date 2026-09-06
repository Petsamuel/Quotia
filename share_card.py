"""Signed share links and the Open Graph image behind them.

A quote has no database row to point at — the corpus is scraped live on every
request — so a share link has to carry the quote itself. The payload is signed
because /q and /og render whatever they are handed: without a signature anyone
could put arbitrary words in a stranger's mouth on our own domain and share the
result as though we had published it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import zlib
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

SHARE_SECRET_ENV_VAR = "QUOTIA_SHARE_SECRET"

# A signature has to outlive a redeploy or every link ever shared turns into a
# 404, so the fallback is a fixed string rather than a random one. It is visible
# in public source, which makes forgery possible: set QUOTIA_SHARE_SECRET in
# production to close that off.
_FALLBACK_SECRET = b"quotia-unconfigured-share-secret"

_SIGNATURE_LENGTH = 16
_MAX_TOKEN_LENGTH = 1400
_MAX_PAYLOAD_BYTES = 4096

# Long enough for the wordiest Goodreads entries, short enough that a token
# stays inside the URL length every platform accepts.
MAX_TEXT_LENGTH = 700
MAX_AUTHOR_LENGTH = 120
MAX_SOURCE_LENGTH = 40


def _secret() -> bytes:
    configured = os.getenv(SHARE_SECRET_ENV_VAR, "").strip()
    return configured.encode("utf-8") if configured else _FALLBACK_SECRET


def _sign(body: str) -> str:
    digest = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:_SIGNATURE_LENGTH]


def encode_quote(text: str, author: str, source: str = "") -> str:
    """Build the opaque id that /q/{token} and /og/{token}.png accept."""
    payload = json.dumps(
        {
            "t": text[:MAX_TEXT_LENGTH],
            "a": author[:MAX_AUTHOR_LENGTH],
            "s": source[:MAX_SOURCE_LENGTH],
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(zlib.compress(payload, 9)).decode("ascii").rstrip("=")
    return f"{body}.{_sign(body)}"


def decode_quote(token: str) -> Optional[Tuple[str, str, str]]:
    """Reverse encode_quote, or None if the token is malformed or unsigned by us."""
    if not token or len(token) > _MAX_TOKEN_LENGTH or "." not in token:
        return None

    body, _, signature = token.rpartition(".")
    if not hmac.compare_digest(signature, _sign(body)):
        return None

    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        # Bounded so a hand-crafted payload cannot decompress into something huge,
        # even though the signature check above should already have rejected it.
        payload = zlib.decompressobj().decompress(raw, _MAX_PAYLOAD_BYTES)
        quote = json.loads(payload.decode("utf-8"))
        text, author, source = quote["t"], quote["a"], quote.get("s", "")
    except (binascii.Error, zlib.error, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None

    if not isinstance(text, str) or not isinstance(author, str) or not text.strip():
        return None
    if not isinstance(source, str):
        source = ""
    return (
        text[:MAX_TEXT_LENGTH],
        author[:MAX_AUTHOR_LENGTH],
        source[:MAX_SOURCE_LENGTH],
    )


# --- image -------------------------------------------------------------------

# This is a port of renderQuoteImage() in static/js/script.js, element for
# element: same palette, same rule under the quote, same brandmark, same source
# attribution. "Save as image" and a link preview are the same picture, so the
# two must not drift — a change to one belongs in the other.
#
# The one thing that does differ is the frame. The canvas card is 1080x1080 for
# saving and posting by hand; a link card is cropped to 1200x630 by X, LinkedIn
# and WhatsApp, and handing them a square gets the brandmark and the top of the
# quote sliced off. Same design, the aspect ratio the platforms actually show.
CARD_WIDTH = 1200
CARD_HEIGHT = 630
_PADDING = 74
_BORDER_INSET = 28

_BACKGROUND = "#F2F0EA"
_INK = "#050505"
_ACCENT = "#FF3333"
_BRAND_INK = (5, 5, 5, 179)      # rgba(5,5,5,0.7) on the wordmark
_ATTRIBUTION_INK = (5, 5, 5, 115)  # rgba(5,5,5,0.45) on "via source"

# The page pulls Playfair Display and Space Mono from Google Fonts, which the
# server cannot reach at render time, so the same families ship in the repo.
# Both are OFL licensed (see OFL.txt alongside them).
_FONT_DIR = Path(__file__).resolve().parent / "static" / "assets" / "fonts"
_PLAYFAIR = _FONT_DIR / "PlayfairDisplay.ttf"
_SPACE_MONO = _FONT_DIR / "SpaceMono-Regular.ttf"

# The stylesheet only loads Playfair at weight 700, so every Playfair run on the
# canvas card is bold whether or not it asks for bold. Match that here.
_PLAYFAIR_WEIGHT = "Bold"


def _playfair(size: int) -> ImageFont.FreeTypeFont:
    try:
        font = ImageFont.truetype(str(_PLAYFAIR), size)
    except OSError:
        logger.warning("Playfair Display missing from %s; card will not match the site", _FONT_DIR)
        return ImageFont.load_default(size=size)
    try:
        font.set_variation_by_name(_PLAYFAIR_WEIGHT)
    except (OSError, ValueError):
        pass  # a static build of the face, already at one weight
    return font


def _space_mono(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(_SPACE_MONO), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """Greedy wrap, matching the measureText loop on the canvas."""
    lines: List[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if line and draw.textlength(candidate, font=font) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _draw_logo_mark(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float) -> None:
    """The logo.svg mark in primitives, as drawLogoMark() does on the canvas."""
    scale = radius / 19.5  # logo.svg outer circle is r=19.5 in a 40x40 box
    width = max(1, round(scale))

    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=_INK, width=width)
    inner = 10 * scale
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], outline=_INK, width=width)

    # The accent dot sits at (28,12) in a circle centred on (20,20).
    dot = 2 * scale
    dx, dy = cx + 8 * scale, cy - 8 * scale
    draw.ellipse([dx - dot, dy - dot, dx + dot, dy + dot], fill=_ACCENT)


def render_card(text: str, author: str, source: str = "") -> bytes:
    """Render one quote as the PNG platforms show in a link preview."""
    image = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [_BORDER_INSET, _BORDER_INSET, CARD_WIDTH - _BORDER_INSET - 1, CARD_HEIGHT - _BORDER_INSET - 1],
        outline=_INK,
        width=2,
    )

    max_width = CARD_WIDTH - _PADDING * 2
    # Room kept below the quote for the rule, the author and the brandmark row.
    max_text_height = CARD_HEIGHT - _PADDING * 2 - 196

    body = f"“{text}”"
    size = 24
    for size in range(52, 23, -2):
        font = _playfair(size)
        lines = _wrap(draw, body, font, max_width)
        if len(lines) * (size * 1.35) <= max_text_height:
            break
    else:  # pragma: no cover - a single word wider than the card
        font = _playfair(24)
        lines = _wrap(draw, body, font, max_width)

    # Canvas positions text on the alphabetic baseline; anchor="ls" is the same
    # origin in Pillow, so the arithmetic below ports across unchanged.
    line_height = size * 1.35
    y = _PADDING + line_height
    for line in lines:
        draw.text((_PADDING, y), line, font=font, fill=_INK, anchor="ls")
        y += line_height

    draw.rectangle([_PADDING, y + 6, _PADDING + 90, y + 10], fill=_ACCENT)
    draw.text((_PADDING, y + 74), author, font=_playfair(34), fill=_INK, anchor="ls")

    # Brandmark bottom left, source attribution bottom right.
    baseline = CARD_HEIGHT - _PADDING + 10
    radius = 14
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    _draw_logo_mark(overlay_draw, _PADDING + radius, baseline - 8, radius)
    overlay.putalpha(overlay.getchannel("A").point(lambda a: int(a * 0.6)))
    image.alpha_composite(overlay)

    draw.text(
        (_PADDING + radius * 2 + 14, baseline),
        "Quotia",
        font=_playfair(27),
        fill=_BRAND_INK,
        anchor="ls",
    )

    if source:
        draw.text(
            (CARD_WIDTH - _PADDING, baseline + 6),
            f"via {source}",
            font=_space_mono(19),
            fill=_ATTRIBUTION_INK,
            anchor="rs",
        )

    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
