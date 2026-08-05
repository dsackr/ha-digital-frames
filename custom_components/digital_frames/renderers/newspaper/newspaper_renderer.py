#!/usr/bin/env python3
"""Newspaper Front Page Renderer for Digital Frames.

Fetches headlines from free RSS feeds (BBC, NPR, Google News topics,
TechCrunch, TMZ, etc.), composes an authentic multi-column newspaper
front page with Pillow (no AI image generation), encodes to Spectra 6
4-bit binary, and optionally uploads to a frame.

Orientation is driven by frame resolution: width > height → landscape
layout; otherwise portrait. Integration path uses --render-only so core
owns encode/send.

Elon 5-step notes (why this design):
1. Requirements less dumb — e-ink needs crisp type in 6 colors, not photo
   collages or generative AI art. Headlines + decks from RSS are enough.
2. Delete — no paid NewsAPI key, no browser HTML→PNG, no AI image gen,
   no article photos (copyright + ugly dither on Spectra 6).
3. Simplify — one RSS fetch layer + deterministic Pillow layout.
4. Accelerate — match agenda/xotd --render-only contract.
5. Automate — Live skill + schedule; offline fallbacks always print.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Spectra 6 palette (shared_utils if present, else inline)
# ---------------------------------------------------------------------------
try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_script_dir)
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from shared_utils.spectra6 import (  # type: ignore
        COLOR_BLACK,
        COLOR_WHITE,
        COLOR_YELLOW,
        COLOR_RED,
        COLOR_BLUE,
        COLOR_GREEN,
        SPECTRA6_REAL_WORLD_RGB,
        SPECTRA6_NIBBLE_VALUES,
        get_closest_nibble,
        pack_row_half,
        pack_split_halves,
        pack_sequential,
        encode_spectra6_bin,
    )
    _has_shared_utils = True
except ImportError:
    _has_shared_utils = False
    COLOR_BLACK = (0, 0, 0)
    COLOR_WHITE = (255, 255, 255)
    COLOR_YELLOW = (239, 222, 68)
    COLOR_RED = (178, 19, 24)
    COLOR_BLUE = (33, 87, 186)
    COLOR_GREEN = (18, 95, 32)

    SPECTRA6_REAL_WORLD_RGB = (
        COLOR_BLACK,
        COLOR_WHITE,
        COLOR_YELLOW,
        COLOR_RED,
        COLOR_BLUE,
        COLOR_GREEN,
    )
    SPECTRA6_NIBBLE_VALUES = (0, 1, 2, 3, 5, 6)

    def get_closest_nibble(r: int, g: int, b: int) -> int:
        min_dist = float("inf")
        best = 1
        for i, color in enumerate(SPECTRA6_REAL_WORLD_RGB):
            dist = (r - color[0]) ** 2 + (g - color[1]) ** 2 + (b - color[2]) ** 2
            if dist < min_dist:
                min_dist = dist
                best = SPECTRA6_NIBBLE_VALUES[i]
        return best

    def pack_row_half(image: Image.Image, y: int, start_x: int, end_x: int) -> bytes:
        out = bytearray()
        pixels = image.load()
        width = image.width
        for x in range(start_x, end_x, 2):
            r, g, b = pixels[x, y][:3]
            high = get_closest_nibble(r, g, b)
            odd_x = x + 1
            if odd_x < end_x and odd_x < width:
                r2, g2, b2 = pixels[odd_x, y][:3]
                low = get_closest_nibble(r2, g2, b2)
            else:
                low = 1
            out.append((high << 4) | low)
        return bytes(out)

    def pack_split_halves(image: Image.Image) -> bytes:
        width, height = image.size
        half = width // 2
        left_bytes = bytearray()
        right_bytes = bytearray()
        for y in range(height):
            left_bytes.extend(pack_row_half(image, y, 0, half))
            right_bytes.extend(pack_row_half(image, y, half, width))
        return bytes(left_bytes) + bytes(right_bytes)

    def pack_sequential(image: Image.Image) -> bytes:
        width, height = image.size
        out = bytearray()
        for y in range(height):
            out.extend(pack_row_half(image, y, 0, width))
        return bytes(out)

    def encode_spectra6_bin(image: Image.Image, layout: str) -> bytes:
        """Pack for common layouts. The 31.5\" banded layout
        (split_8_bands_vchunks) is *not* implemented here — Live skill
        delivery re-packs from newspaper_preview.png in panel_codec when
        the subprocess .bin size does not match the panel wire size.
        Standalone upload to a 31.5\" frame should go through HA Send Now."""
        print(f"Encoding image buffer using layout: {layout}...")
        if layout == "split_half":
            return pack_split_halves(image)
        if layout == "split_8_bands_vchunks":
            print(
                "Warning: layout split_8_bands_vchunks is not packed in this "
                "script; emitting plain 4bpp. Digital Frames will re-pack "
                "from the RGB preview on Send Now."
            )
        return pack_sequential(image)


USER_AGENT = "DigitalFramesNewspaper/1.0 (+https://github.com/dsackr/ha-digital-frames)"

# ---------------------------------------------------------------------------
# Free RSS sources & topic map (no API keys)
# ---------------------------------------------------------------------------
# Publisher feeds + Google News topic/section feeds. Google News is used for
# Reuters/AP (direct RSS removed) and for topic browsing.
SOURCE_FEEDS: dict[str, dict[str, str]] = {
    "bbc": {
        "name": "BBC",
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "section": "World",
    },
    "bbc_world": {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "section": "World",
    },
    "bbc_tech": {
        "name": "BBC Tech",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "section": "Tech",
    },
    "bbc_politics": {
        "name": "BBC Politics",
        "url": "https://feeds.bbci.co.uk/news/politics/rss.xml",
        "section": "Politics",
    },
    "npr": {
        "name": "NPR",
        "url": "https://feeds.npr.org/1001/rss.xml",
        "section": "National",
    },
    "npr_politics": {
        "name": "NPR Politics",
        "url": "https://feeds.npr.org/1014/rss.xml",
        "section": "Politics",
    },
    "guardian": {
        "name": "The Guardian",
        "url": "https://www.theguardian.com/world/rss",
        "section": "World",
    },
    "nyt": {
        "name": "NYT",
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "section": "National",
    },
    "politico": {
        "name": "Politico",
        "url": "https://rss.politico.com/politics-news.xml",
        "section": "Politics",
    },
    "techcrunch": {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "section": "Tech",
    },
    "wired": {
        "name": "Wired",
        "url": "https://www.wired.com/feed/rss",
        "section": "Tech",
    },
    "ars": {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "section": "Tech",
    },
    "hn": {
        "name": "Hacker News",
        "url": "https://hnrss.org/frontpage",
        "section": "Tech",
    },
    "tmz": {
        "name": "TMZ",
        "url": "https://www.tmz.com/rss.xml",
        "section": "Gossip",
    },
    "espn": {
        "name": "ESPN",
        "url": "https://www.espn.com/espn/rss/news",
        "section": "Sports",
    },
    "sciam": {
        "name": "Scientific American",
        "url": "http://rss.sciam.com/ScientificAmerican-Global",
        "section": "Science",
    },
    "reuters": {
        "name": "Reuters",
        "url": "https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en-US&gl=US&ceid=US:en",
        "section": "World",
    },
    "ap": {
        "name": "AP",
        "url": "https://news.google.com/rss/search?q=site:apnews.com+when:1d&hl=en-US&gl=US&ceid=US:en",
        "section": "National",
    },
    "gnews_world": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "section": "World",
    },
    "gnews_nation": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en",
        "section": "National",
    },
    "gnews_business": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "section": "Business",
    },
    "gnews_tech": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
        "section": "Tech",
    },
    "gnews_science": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
        "section": "Science",
    },
    "gnews_sports": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
        "section": "Sports",
    },
    "gnews_entertainment": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-US&gl=US&ceid=US:en",
        "section": "Arts",
    },
    "gnews_health": {
        "name": "Google News",
        "url": "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en",
        "section": "Health",
    },
}

# Topic → ordered source ids to pull (first feeds preferred for hero).
TOPIC_SOURCES: dict[str, list[str]] = {
    "world": ["bbc_world", "guardian", "reuters", "gnews_world", "bbc"],
    "national": ["npr", "nyt", "ap", "gnews_nation"],
    "politics": ["politico", "npr_politics", "bbc_politics", "ap", "gnews_nation"],
    "tech": ["techcrunch", "wired", "ars", "hn", "bbc_tech", "gnews_tech"],
    "business": ["gnews_business", "nyt", "reuters"],
    "science": ["sciam", "gnews_science", "ars"],
    "sports": ["espn", "gnews_sports"],
    "entertainment": ["gnews_entertainment", "tmz"],
    "gossip": ["tmz", "gnews_entertainment"],
    "health": ["gnews_health", "npr"],
}

NEWS_MIXES: dict[str, list[str]] = {
    "general": ["world", "national", "politics", "tech"],
    "tech": ["tech", "science", "business"],
    "politics": ["politics", "national", "world"],
    "gossip": ["gossip", "entertainment"],
    "world": ["world", "national"],
    "business": ["business", "tech", "national"],
    "science": ["science", "tech", "health"],
    "sports": ["sports", "national"],
    "entertainment": ["entertainment", "gossip"],
}

FALLBACK_STORIES: list[dict[str, str]] = [
    {
        "title": "Frame Awaits Morning Edition as Wire Quiet",
        "summary": "No live wire copy reached the pressroom. This standby dispatch keeps the front page on the wall until feeds return.",
        "source": "Staff",
        "section": "City",
    },
    {
        "title": "Readers Prefer Ink-True Type on E-Paper Screens",
        "summary": "High-contrast serif headlines and multi-column body text remain the most readable format for low-refresh displays.",
        "source": "Design Desk",
        "section": "Arts",
    },
    {
        "title": "Six Colors, Infinite Columns: The Spectra Palette",
        "summary": "Black, white, red, blue, yellow, and green define every rule, kicker, and dateline on this edition.",
        "source": "Pressroom",
        "section": "Tech",
    },
    {
        "title": "Local Edition Runs Without Cloud Keys or Fees",
        "summary": "Public RSS remains the cheapest, stablest way to fill a front page from world desks and specialty wires.",
        "source": "Wire Desk",
        "section": "Business",
    },
    {
        "title": "Portrait and Landscape Forms Share One Makeup Engine",
        "summary": "The same stories recompose for tall gallery hangs and wide sideboard frames without a second generator.",
        "source": "Makeup",
        "section": "City",
    },
    {
        "title": "Schedule the Paper Once; Wake to Fresh Headlines",
        "summary": "Home Assistant Live skills refresh the page on a timer the same way a photo schedule rotates art.",
        "source": "Home",
        "section": "National",
    },
    {
        "title": "Gossip, Politics, Tech: Choose Your Beats",
        "summary": "Topic picks route the fetch layer to TMZ, Politico, TechCrunch, BBC, and Google News sections as needed.",
        "source": "Editors",
        "section": "National",
    },
    {
        "title": "No Generative Art Required for the Masthead",
        "summary": "Typography, Scotch rules, and column grids produce a newspaper look the panel can print sharply.",
        "source": "Typography",
        "section": "Arts",
    },
]


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Fontsource CDN serves static latin TTFs Pillow can load (variable axes
# from google/fonts work for some faces but not all; static is safer).
FONT_SOURCES = {
    "PlayfairDisplay": {
        # Full URL per style — not a shared base_url path layout.
        "files": {
            "Regular": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@latest/latin-400-normal.ttf",
            "Bold": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@latest/latin-700-normal.ttf",
            "Black": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@latest/latin-900-normal.ttf",
            "Italic": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@latest/latin-400-italic.ttf",
        },
        "local": {
            "Regular": "PlayfairDisplay-Regular.ttf",
            "Bold": "PlayfairDisplay-Bold.ttf",
            "Black": "PlayfairDisplay-Black.ttf",
            "Italic": "PlayfairDisplay-Italic.ttf",
        },
    },
    "LibreBaskerville": {
        "files": {
            "Regular": "https://cdn.jsdelivr.net/fontsource/fonts/libre-baskerville@latest/latin-400-normal.ttf",
            "Bold": "https://cdn.jsdelivr.net/fontsource/fonts/libre-baskerville@latest/latin-700-normal.ttf",
            "Italic": "https://cdn.jsdelivr.net/fontsource/fonts/libre-baskerville@latest/latin-400-italic.ttf",
        },
        "local": {
            "Regular": "LibreBaskerville-Regular.ttf",
            "Bold": "LibreBaskerville-Bold.ttf",
            "Italic": "LibreBaskerville-Italic.ttf",
        },
    },
}

_FONT_CACHE: dict[tuple[str, str, int], ImageFont.ImageFont] = {}


def _ssl_context():
    """Prefer system CAs; fall back to unverified only if verify fails later."""
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def _http_get(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    ctx = _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except (ssl.SSLError, urllib.error.URLError) as err:
        # Corporate MITM / incomplete CA stores — retry once unverified so
        # the paper still prints in constrained home-lab environments.
        msg = str(err).lower()
        if "ssl" in msg or "certificate" in msg:
            print(f"SSL issue for {url[:60]}… retrying without verify")
            with urllib.request.urlopen(
                req, timeout=timeout, context=ssl._create_unverified_context()
            ) as resp:
                return resp.read()
        raise


def load_font(family: str, style: str, size: int) -> ImageFont.ImageFont:
    cache_key = (family, style, size)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "fonts")
    os.makedirs(font_dir, exist_ok=True)

    src = FONT_SOURCES.get(family) or FONT_SOURCES["LibreBaskerville"]
    files = src.get("files") or {}
    locals_ = src.get("local") or {}
    style_key = style if style in files or style in locals_ else "Regular"
    filename = locals_.get(style_key) or f"{family}-{style_key}.ttf"
    font_path = os.path.join(font_dir, filename)
    url = files.get(style_key)

    if (not os.path.exists(font_path) or os.path.getsize(font_path) < 1000) and url:
        try:
            print(f"Downloading font {filename}...")
            data = _http_get(url, timeout=25)
            if len(data) > 1000:
                with open(font_path, "wb") as f:
                    f.write(data)
            else:
                print(f"Font download too small ({filename}): {len(data)} bytes")
        except Exception as e:
            print(f"Font download failed ({filename}): {e}")

    try:
        font = ImageFont.truetype(font_path, size)
        _FONT_CACHE[cache_key] = font
        return font
    except Exception as e:
        print(f"Font load failed ({font_path}): {e}")
        # Cross-family fallback before bitmap default
        if family != "LibreBaskerville":
            return load_font("LibreBaskerville", "Regular", size)
        font = ImageFont.load_default()
        _FONT_CACHE[cache_key] = font
        return font


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def text_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, sample: str = "Ag") -> int:
    bbox = draw.textbbox((0, 0), sample, font=font)
    return bbox[3] - bbox[1]


def draw_justified_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    x: int,
    y: int,
    width: int,
    fill,
    last_line: bool = False,
) -> None:
    words = text.split()
    if len(words) <= 1 or last_line:
        draw.text((x, y), text, font=font, fill=fill)
        return
    natural = draw.textlength(text, font=font)
    if natural >= width * 0.92:
        draw.text((x, y), text, font=font, fill=fill)
        return
    gaps = len(words) - 1
    extra = width - natural
    # Distribute leftover pixels across gaps (integer spacing).
    base_gap = draw.textlength(" ", font=font)
    extra_each = extra / gaps
    cursor = float(x)
    for i, word in enumerate(words):
        draw.text((int(cursor), y), word, font=font, fill=fill)
        cursor += draw.textlength(word, font=font)
        if i < gaps:
            cursor += base_gap + extra_each


def fit_headline(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    family: str,
    style: str,
    max_size: int,
    min_size: int,
    max_lines: int = 5,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    for size in range(max_size, min_size - 1, -2):
        font = load_font(family, style, size)
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) > max_lines:
            continue
        lh = text_height(draw, font) + max(2, size // 10)
        total = lh * len(lines)
        if total <= max_height:
            return font, lines, lh
    font = load_font(family, style, min_size)
    lines = wrap_text(draw, text, font, max_width)[:max_lines]
    if lines and len(wrap_text(draw, text, font, max_width)) > max_lines:
        # ellipsis on last line
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = (last.rstrip() + "…") if last else "…"
    lh = text_height(draw, font) + max(2, min_size // 10)
    return font, lines, lh


def get_timezone(tz_name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        return datetime.timezone.utc


# ---------------------------------------------------------------------------
# RSS fetch / parse
# ---------------------------------------------------------------------------
def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(el: ET.Element, names: tuple[str, ...]) -> str:
    for child in el:
        if _local_tag(child.tag) in names:
            if child.text and child.text.strip():
                return child.text.strip()
            # Some feeds put content in nested tags or attributes
            parts = [t for t in child.itertext() if t and t.strip()]
            if parts:
                return " ".join(parts).strip()
    return ""


def parse_rss_items(xml_bytes: bytes, source_name: str, section: str) -> list[dict[str, str]]:
    stories: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"RSS parse error for {source_name}: {e}")
        return stories

    items = []
    for el in root.iter():
        if _local_tag(el.tag) in ("item", "entry"):
            items.append(el)

    for item in items:
        title = strip_html(_child_text(item, ("title",)))
        summary = strip_html(
            _child_text(item, ("description", "summary", "content", "subtitle"))
        )
        # Google News often puts source after " - SourceName" in title
        src = source_name
        if " - " in title and source_name == "Google News":
            title, maybe_src = title.rsplit(" - ", 1)
            if len(maybe_src) < 40:
                src = maybe_src.strip()
                title = title.strip()
        if not title:
            continue
        # Trim summary noise
        if summary.startswith(title):
            summary = summary[len(title) :].lstrip(" -–—:")
        summary = summary[:400]
        stories.append(
            {
                "title": title,
                "summary": summary,
                "source": src,
                "section": section,
            }
        )
    return stories


def resolve_feed_ids(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Build ordered unique source ids from news_mix / topics / sources."""
    feed_ids: list[str] = []

    # Explicit sources list wins as seed
    raw_sources = config.get("sources") or config.get("source") or ""
    if isinstance(raw_sources, str):
        sources = [s.strip().lower() for s in raw_sources.split(",") if s.strip()]
    else:
        sources = [str(s).strip().lower() for s in raw_sources if str(s).strip()]

    for s in sources:
        if s in SOURCE_FEEDS and s not in feed_ids:
            feed_ids.append(s)

    # Topics from mix or free-form list
    mix = (config.get("news_mix") or "general").strip().lower()
    raw_topics = config.get("topics") or ""
    if isinstance(raw_topics, str):
        topics = [t.strip().lower() for t in raw_topics.split(",") if t.strip()]
    else:
        topics = [str(t).strip().lower() for t in raw_topics if str(t).strip()]

    if not topics and mix in NEWS_MIXES:
        topics = list(NEWS_MIXES[mix])
    if not topics:
        topics = list(NEWS_MIXES["general"])

    for topic in topics:
        for sid in TOPIC_SOURCES.get(topic, []):
            if sid not in feed_ids:
                feed_ids.append(sid)

    # Custom RSS URL
    custom = (config.get("custom_rss_url") or "").strip()
    if custom:
        # Inject as a virtual source at runtime in fetch layer
        feed_ids.insert(0, "__custom__")

    if not feed_ids:
        feed_ids = ["bbc", "npr", "gnews_world"]
    return feed_ids, topics


def _fetch_one_feed(
    fid: str,
    custom_url: str,
    per_feed: int,
    seen_titles: set[str],
) -> list[dict[str, str]]:
    if fid == "__custom__":
        meta = {"name": "Custom", "url": custom_url, "section": "Wire"}
    else:
        meta = SOURCE_FEEDS.get(fid)
        if not meta:
            return []
    out: list[dict[str, str]] = []
    try:
        print(f"Fetching {meta['name']}: {meta['url'][:70]}...")
        data = _http_get(meta["url"])
        items = parse_rss_items(data, meta["name"], meta["section"])
        for item in items[:per_feed]:
            key = item["title"].lower()[:80]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            out.append(item)
    except Exception as e:
        print(f"Feed error ({meta['name']}): {e}")
    return out


def fetch_stories(config: dict[str, Any], max_stories: int = 10) -> list[dict[str, str]]:
    feed_ids, topics = resolve_feed_ids(config)
    # Small per-feed cap so one desk cannot drown out other beats.
    per_feed = 3
    collected: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    custom = (config.get("custom_rss_url") or "").strip()

    fetched_ids: set[str] = set()

    # Pass 1: one primary feed per topic for section diversity
    for topic in topics:
        primaries = TOPIC_SOURCES.get(topic) or []
        if not primaries:
            continue
        fid = primaries[0]
        if fid not in feed_ids and fid != "__custom__":
            continue
        if fid in fetched_ids:
            continue
        items = _fetch_one_feed(fid, custom, per_feed, seen_titles)
        fetched_ids.add(fid)
        collected.extend(items)

    # Pass 2: remaining feeds until we have enough raw material
    for fid in feed_ids:
        if len(collected) >= max_stories * 3:
            break
        if fid in fetched_ids:
            continue
        items = _fetch_one_feed(fid, custom, per_feed, seen_titles)
        fetched_ids.add(fid)
        collected.extend(items)

    if not collected:
        print("No live stories; using fallback edition.")
        return list(FALLBACK_STORIES[:max_stories])

    # Prefer diversity of sections when possible
    by_section: dict[str, list[dict[str, str]]] = {}
    for s in collected:
        by_section.setdefault(s["section"], []).append(s)

    ordered: list[dict[str, str]] = []
    sections = list(by_section.keys())
    idx = 0
    while len(ordered) < max_stories and any(by_section.values()):
        sec = sections[idx % len(sections)]
        bucket = by_section.get(sec) or []
        if bucket:
            ordered.append(bucket.pop(0))
        idx += 1
        if idx > max_stories * 20:
            break

    if len(ordered) < max_stories:
        for s in collected:
            if s not in ordered:
                ordered.append(s)
            if len(ordered) >= max_stories:
                break

    return ordered[:max_stories]


# ---------------------------------------------------------------------------
# Newspaper composition
# ---------------------------------------------------------------------------
def _draw_scotch_rule(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int, thick: int = 3) -> int:
    """Classic double rule (thick over thin). Returns y below rule."""
    draw.line([(x0, y), (x1, y)], fill=COLOR_BLACK, width=thick)
    draw.line([(x0, y + thick + 2), (x1, y + thick + 2)], fill=COLOR_BLACK, width=1)
    return y + thick + 6


def _draw_thin_rule(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int) -> int:
    draw.line([(x0, y), (x1, y)], fill=COLOR_BLACK, width=1)
    return y + 4


def _draw_column_rule(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int) -> None:
    draw.line([(x, y0), (x, y1)], fill=COLOR_BLACK, width=1)


def render_masthead(
    draw: ImageDraw.ImageDraw,
    width: int,
    margin: int,
    paper_name: str,
    when: datetime.datetime,
    edition: str,
    is_landscape: bool,
) -> int:
    """Draw nameplate + dateline. Returns y below masthead block."""
    y = margin
    name = (paper_name or "THE DAILY FRAME").strip().upper()
    max_name_w = width - 2 * margin

    if is_landscape:
        name_size_max, name_size_min = 54, 22
        meta_size = 11
        vol_size = 10
    else:
        name_size_max, name_size_min = 96, 36
        meta_size = 16
        vol_size = 14

    # Fit masthead name
    name_font = load_font("PlayfairDisplay", "Black", name_size_max)
    size = name_size_max
    while size >= name_size_min and draw.textlength(name, font=name_font) > max_name_w:
        size -= 2
        name_font = load_font("PlayfairDisplay", "Black", size)

    # Volume / price line above nameplate (classic)
    vol_font = load_font("LibreBaskerville", "Regular", vol_size)
    day_num = when.timetuple().tm_yday
    vol_left = f"VOL. {when.year - 2020}  —  NO. {day_num}"
    vol_right = edition.upper() if edition else "MORNING EDITION"
    price = "PRICELESS"
    draw.text((margin, y), vol_left, font=vol_font, fill=COLOR_BLACK)
    draw.text((width // 2, y), price, font=vol_font, fill=COLOR_BLACK, anchor="ma")
    draw.text((width - margin, y), vol_right, font=vol_font, fill=COLOR_BLACK, anchor="ra")
    y += text_height(draw, vol_font) + (4 if is_landscape else 8)

    y = _draw_thin_rule(draw, margin, y, width - margin)
    y += 2 if is_landscape else 6

    # Nameplate
    name_h = text_height(draw, name_font, name)
    draw.text((width // 2, y), name, font=name_font, fill=COLOR_BLACK, anchor="ma")
    y += name_h + (4 if is_landscape else 10)

    y = _draw_scotch_rule(draw, margin, y, width - margin, thick=3 if not is_landscape else 2)

    # Dateline
    meta_font = load_font("LibreBaskerville", "Italic", meta_size)
    date_str = when.strftime("%A, %B %-d, %Y") if os.name != "nt" else when.strftime("%A, %B %d, %Y")
    # %-d is platform-specific; normalize
    date_str = when.strftime("%A, %B ") + str(when.day) + when.strftime(", %Y")
    city = "HOME EDITION"
    draw.text((margin, y), city, font=meta_font, fill=COLOR_BLACK)
    draw.text((width // 2, y), date_str, font=meta_font, fill=COLOR_BLACK, anchor="ma")
    draw.text((width - margin, y), when.strftime("%H:%M"), font=meta_font, fill=COLOR_BLACK, anchor="ra")
    y += text_height(draw, meta_font) + (4 if is_landscape else 8)

    y = _draw_scotch_rule(draw, margin, y, width - margin, thick=2 if is_landscape else 3)
    return y + (2 if is_landscape else 6)


def _draw_kicker(draw, text: str, font, x: int, y: int, color=COLOR_RED) -> int:
    kicker = (text or "").upper()
    draw.text((x, y), kicker, font=font, fill=color)
    return y + text_height(draw, font) + 2


def _draw_story_block(
    draw: ImageDraw.ImageDraw,
    story: dict[str, str],
    x: int,
    y: int,
    col_w: int,
    max_y: int,
    *,
    is_hero: bool,
    is_landscape: bool,
) -> int:
    """Draw one story into a column box. Returns new y (may exceed max_y if empty)."""
    if y >= max_y - 20:
        return y

    if is_hero:
        kicker_size = 11 if is_landscape else 16
        head_max = 34 if is_landscape else 48
        head_min = 15 if is_landscape else 22
        deck_size = 11 if is_landscape else 16
        body_size = 11 if is_landscape else 15
        max_head_lines = 4 if is_landscape else 5
        max_body_lines = 5 if is_landscape else 10
    else:
        kicker_size = 10 if is_landscape else 12
        head_max = 17 if is_landscape else 24
        head_min = 11 if is_landscape else 15
        deck_size = 10 if is_landscape else 12
        body_size = 10 if is_landscape else 13
        max_head_lines = 3 if is_landscape else 4
        max_body_lines = 5 if is_landscape else 14

    kicker_font = load_font("LibreBaskerville", "Bold", kicker_size)
    body_font = load_font("LibreBaskerville", "Regular", body_size)
    deck_font = load_font("LibreBaskerville", "Italic", deck_size)
    byline_font = load_font("LibreBaskerville", "Italic", max(9, body_size - 1))

    # Kicker / section
    y = _draw_kicker(draw, story.get("section", "News"), kicker_font, x, y)
    if y >= max_y:
        return y

    head_budget = min(int((max_y - y) * (0.45 if is_hero else 0.4)), 200 if is_hero else 120)
    head_font, head_lines, head_lh = fit_headline(
        draw,
        story["title"],
        col_w,
        head_budget,
        "PlayfairDisplay",
        "Bold" if not is_hero else "Black",
        head_max,
        head_min,
        max_lines=max_head_lines,
    )
    for line in head_lines:
        if y + head_lh > max_y:
            break
        draw.text((x, y), line, font=head_font, fill=COLOR_BLACK)
        y += head_lh
    y += 3 if is_landscape else 6

    # Byline
    byline = f"By {story.get('source', 'Wire')}"
    if y + text_height(draw, byline_font) < max_y:
        draw.text((x, y), byline, font=byline_font, fill=COLOR_BLACK)
        y += text_height(draw, byline_font) + (2 if is_landscape else 4)

    # Short rule under byline
    if y + 6 < max_y:
        draw.line([(x, y), (x + min(40, col_w // 3), y)], fill=COLOR_BLACK, width=1)
        y += 4 if is_landscape else 8

    summary = story.get("summary") or ""
    if summary and y < max_y - 10:
        # First sentence-ish as deck if long enough
        deck = summary
        if len(summary) > 120:
            cut = summary.find(". ")
            if 40 < cut < 160:
                deck = summary[: cut + 1]
        deck_lines = wrap_text(draw, deck, deck_font, col_w)[: 2 if is_landscape else 3]
        for i, line in enumerate(deck_lines):
            if y + text_height(draw, deck_font) > max_y:
                break
            draw.text((x, y), line, font=deck_font, fill=COLOR_BLACK)
            y += text_height(draw, deck_font) + 2
        y += 2 if is_landscape else 4

        # Remaining body justified
        rest = summary[len(deck) :].strip() if deck != summary else ""
        if not rest and len(summary) > len(deck):
            rest = summary
        body_src = rest if rest else (summary if not deck_lines else "")
        if body_src and y < max_y - 12:
            body_lines = wrap_text(draw, body_src, body_font, col_w)[:max_body_lines]
            lh = text_height(draw, body_font) + (2 if is_landscape else 3)
            for i, line in enumerate(body_lines):
                if y + lh > max_y:
                    break
                last = i == len(body_lines) - 1
                draw_justified_line(draw, line, body_font, x, y, col_w, COLOR_BLACK, last_line=last)
                y += lh

    return y


def render_newspaper(
    width: int,
    height: int,
    stories: list[dict[str, str]],
    paper_name: str,
    when: datetime.datetime,
    edition: str = "Morning Edition",
) -> Image.Image:
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)
    is_landscape = width > height

    margin = 16 if is_landscape else 36
    y = render_masthead(draw, width, margin, paper_name, when, edition, is_landscape)
    content_bottom = height - margin - (14 if is_landscape else 22)

    if not stories:
        stories = list(FALLBACK_STORIES)

    hero = stories[0]
    rest = stories[1:]

    if is_landscape:
        # Landscape: hero left (~58%), secondary stack right; optional bottom strip
        gap = 12
        left_w = int((width - 2 * margin - gap) * 0.58)
        right_x = margin + left_w + gap
        right_w = width - margin - right_x
        col_top = y
        _draw_column_rule(draw, margin + left_w + gap // 2, col_top, content_bottom)

        y_left = _draw_story_block(
            draw, hero, margin, col_top, left_w, content_bottom,
            is_hero=True, is_landscape=True,
        )

        # Right column: 2–3 secondary stories stacked
        y_right = col_top
        for i, story in enumerate(rest[:3]):
            if y_right >= content_bottom - 20:
                break
            y_right = _draw_story_block(
                draw, story, right_x, y_right, right_w,
                content_bottom if i == 2 else min(content_bottom, y_right + (content_bottom - col_top) // 2 + 20),
                is_hero=False, is_landscape=True,
            )
            if i < 2 and y_right < content_bottom - 16:
                y_right = _draw_thin_rule(draw, right_x, y_right + 4, right_x + right_w) + 4

        # If room under hero, add one more brief
        if rest[3:] and y_left < content_bottom - 40:
            y_left = _draw_thin_rule(draw, margin, y_left + 6, margin + left_w) + 4
            _draw_story_block(
                draw, rest[3], margin, y_left, left_w, content_bottom,
                is_hero=False, is_landscape=True,
            )
    else:
        # Portrait: hero full-width, then 2–3 columns of secondary copy
        hero_bottom_limit = y + int((content_bottom - y) * 0.34)
        y = _draw_story_block(
            draw, hero, margin, y, width - 2 * margin, hero_bottom_limit,
            is_hero=True, is_landscape=False,
        )
        y += 8
        y = _draw_scotch_rule(draw, margin, y, width - margin, thick=2)
        y += 8

        cols = 3 if width >= 1000 else 2
        gap = 16
        usable = width - 2 * margin - gap * (cols - 1)
        col_w = usable // cols
        col_top = y
        col_ys = [col_top] * cols

        # Vertical rules
        for c in range(1, cols):
            rx = margin + c * (col_w + gap) - gap // 2
            _draw_column_rule(draw, rx, col_top, content_bottom)

        # Target ~equal story counts per column so the page fills top-to-bottom.
        per_col = max(1, (len(rest) + cols - 1) // cols)
        for i, story in enumerate(rest):
            c = min(range(cols), key=lambda idx: col_ys[idx])
            if col_ys[c] >= content_bottom - 30:
                continue
            cx = margin + c * (col_w + gap)
            stories_left_in_col_est = max(1, per_col)
            col_room = content_bottom - col_ys[c]
            share = max(140, col_room // max(1, stories_left_in_col_est))
            soft_max = min(content_bottom, col_ys[c] + share)
            if i >= len(rest) - cols or col_room < 220:
                soft_max = content_bottom
            if col_ys[c] > col_top + 10:
                col_ys[c] = _draw_thin_rule(draw, cx, col_ys[c] + 6, cx + col_w) + 6
            col_ys[c] = _draw_story_block(
                draw, story, cx, col_ys[c], col_w, soft_max,
                is_hero=False, is_landscape=False,
            )

        # Fill leftover column space with an "Also today" brief index —
        # classic newspaper technique when wire copy runs short.
        brief_font = load_font("LibreBaskerville", "Regular", 12)
        brief_head = load_font("LibreBaskerville", "Bold", 13)
        for c in range(cols):
            if col_ys[c] >= content_bottom - 60:
                continue
            cx = margin + c * (col_w + gap)
            yb = col_ys[c] + 10
            yb = _draw_thin_rule(draw, cx, yb, cx + col_w) + 6
            draw.text((cx, yb), "ALSO TODAY", font=brief_head, fill=COLOR_RED)
            yb += text_height(draw, brief_head) + 6
            # Reuse hero + other column titles as one-line briefs
            briefs = [hero] + [s for j, s in enumerate(rest) if j % cols != c]
            for b in briefs:
                if yb >= content_bottom - 16:
                    break
                line = f"• {b['title']}"
                wrapped = wrap_text(draw, line, brief_font, col_w)[:2]
                for wl in wrapped:
                    if yb >= content_bottom - 14:
                        break
                    draw.text((cx, yb), wl, font=brief_font, fill=COLOR_BLACK)
                    yb += text_height(draw, brief_font) + 3
                yb += 4

    # Folio footer
    footer_font = load_font("LibreBaskerville", "Regular", 10 if is_landscape else 13)
    folio = f"{(paper_name or 'THE DAILY FRAME').upper()}  ·  PAGE 1  ·  {when.strftime('%B %d, %Y')}"
    draw.text((width // 2, height - margin // 2 - 2), folio, font=footer_font, fill=COLOR_BLACK, anchor="md")

    return img


# ---------------------------------------------------------------------------
# Frame upload / CLI
# ---------------------------------------------------------------------------
def upload_bin_to_frame(frame_ip: str, binary_bytes: bytes) -> bool:
    url = f"http://{frame_ip}/api/display"
    print(f"Uploading {len(binary_bytes)} bytes to {url}...")
    try:
        req = urllib.request.Request(
            url,
            data=binary_bytes,
            method="POST",
            headers={"Content-Type": "application/octet-stream", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Upload response: HTTP {resp.status}")
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"Error during upload: {e}")
        return False


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.json (default: config.json next to this script)",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render and pack .bin but skip frame upload (Live skill path).",
    )
    return parser.parse_args(argv)


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> int:
    args = parse_args(argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(script_dir, "config.json")
    if not os.path.isfile(config_path):
        example = os.path.join(script_dir, "config.example.json")
        if os.path.isfile(example) and not args.config:
            print(f"No config.json; using {example}")
            config_path = example
        else:
            print(f"Config not found: {config_path}")
            return 1

    config = load_config(config_path)
    frame_conf = config.get("frame") or {}
    resolution = frame_conf.get("resolution") or [1200, 1600]
    width, height = int(resolution[0]), int(resolution[1])
    layout_type = frame_conf.get("layout") or "split_half"

    tz_name = config.get("timezone") or "UTC"
    tz = get_timezone(tz_name)
    now = datetime.datetime.now(tz)

    paper_name = config.get("paper_name") or "The Daily Frame"
    edition = config.get("edition") or "Morning Edition"
    max_stories = int(config.get("max_stories") or (10 if height >= width else 7))
    max_stories = max(3, min(14, max_stories))

    # cwd is run_dir for Live skills — write outputs there when --config used
    out_dir = os.path.dirname(os.path.abspath(config_path)) if args.config else script_dir

    print(f"Composing newspaper {width}x{height} ({'landscape' if width > height else 'portrait'})...")
    stories = fetch_stories(config, max_stories=max_stories)
    print(f"Using {len(stories)} stories:")
    for i, s in enumerate(stories):
        print(f"  {i+1}. [{s.get('section')}] {s['title'][:70]}")

    img = render_newspaper(width, height, stories, paper_name, now, edition)

    preview_path = os.path.join(out_dir, "newspaper_preview.png")
    img.save(preview_path, "PNG")
    print(f"Wrote preview: {preview_path}")

    binary_bytes = encode_spectra6_bin(img, layout_type)
    bin_path = os.path.join(out_dir, "newspaper.bin")
    with open(bin_path, "wb") as f:
        f.write(binary_bytes)
    print(f"Wrote binary: {bin_path} ({len(binary_bytes)} bytes)")

    if args.render_only:
        print("--render-only set: skipping upload to frame.")
        return 0

    frame_ip = (frame_conf.get("ip_address") or "").strip()
    if not frame_ip:
        print("No frame.ip_address in config; done.")
        return 0

    ok = upload_bin_to_frame(frame_ip, binary_bytes)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
