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
# Newspaper composition — scale-aware metrics
# ---------------------------------------------------------------------------
# Design reference is the 13.3" portrait canvas. All type and spacing scale
# with the actual panel so a 31.5" (1440×2560) page is not a postage stamp
# of 13.3" type floating in empty column space.
_REF_PORTRAIT = (1200, 1600)
_REF_LANDSCAPE = (800, 480)


def _clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def layout_scale(width: int, height: int) -> float:
    """Type/spacing scale vs reference orientation canvas.

    Portrait pages weight height more (31.5\" is much taller than 13.3\")
    so type and leading grow with the page, not just a mild geometric mean
    that still looks like postage-stamp copy on a tall panel.
    """
    import math

    is_landscape = width > height
    ref_w, ref_h = _REF_LANDSCAPE if is_landscape else _REF_PORTRAIT
    sw = max(0.01, width / ref_w)
    sh = max(0.01, height / ref_h)
    if is_landscape:
        s = math.sqrt(sw * sh)
    else:
        # ~width^0.4 * height^0.6 — 1440×2560 ≈ 1.48 vs geometric 1.39
        s = (sw ** 0.4) * (sh ** 0.6)
    return _clamp(s, 0.65, 2.6)


def _sz(base: float, scale: float, lo: int = 8, hi: int = 220) -> int:
    return int(_clamp(round(base * scale), lo, hi))


def _draw_scotch_rule(
    draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int, thick: int = 3, gap: int = 2
) -> int:
    """Classic double rule (thick over thin). Returns y below rule."""
    draw.line([(x0, y), (x1, y)], fill=COLOR_BLACK, width=max(1, thick))
    thin_y = y + thick + gap
    draw.line([(x0, thin_y), (x1, thin_y)], fill=COLOR_BLACK, width=1)
    return thin_y + max(4, thick + 2)


def _draw_thin_rule(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int, scale: float = 1.0) -> int:
    draw.line([(x0, y), (x1, y)], fill=COLOR_BLACK, width=1)
    return y + _sz(4, scale, 3, 10)


def _draw_column_rule(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int, width: int = 1) -> None:
    draw.line([(x, y0), (x, y1)], fill=COLOR_BLACK, width=max(1, width))


def render_masthead(
    draw: ImageDraw.ImageDraw,
    width: int,
    margin: int,
    paper_name: str,
    when: datetime.datetime,
    edition: str,
    is_landscape: bool,
    scale: float,
) -> int:
    """Draw nameplate + dateline. Returns y below masthead block."""
    y = margin
    name = (paper_name or "THE DAILY FRAME").strip().upper()
    max_name_w = width - 2 * margin

    if is_landscape:
        name_size_max = _sz(54, scale, 28, 120)
        name_size_min = _sz(22, scale, 14, 48)
        meta_size = _sz(11, scale, 9, 28)
        vol_size = _sz(10, scale, 8, 24)
        rule_thick = _sz(2, scale, 1, 5)
        gap_sm = _sz(4, scale, 2, 12)
        gap_md = _sz(6, scale, 3, 14)
    else:
        name_size_max = _sz(96, scale, 48, 200)
        name_size_min = _sz(36, scale, 22, 80)
        meta_size = _sz(16, scale, 12, 36)
        vol_size = _sz(14, scale, 10, 32)
        rule_thick = _sz(3, scale, 2, 8)
        gap_sm = _sz(8, scale, 4, 18)
        gap_md = _sz(10, scale, 5, 22)

    # Fit masthead name to full width (size already scaled; shrink only if needed)
    name_font = load_font("PlayfairDisplay", "Black", name_size_max)
    size = name_size_max
    while size >= name_size_min and draw.textlength(name, font=name_font) > max_name_w:
        size -= 2
        name_font = load_font("PlayfairDisplay", "Black", size)

    vol_font = load_font("LibreBaskerville", "Regular", vol_size)
    day_num = when.timetuple().tm_yday
    vol_left = f"VOL. {when.year - 2020}  —  NO. {day_num}"
    vol_right = edition.upper() if edition else "MORNING EDITION"
    price = "PRICELESS"
    draw.text((margin, y), vol_left, font=vol_font, fill=COLOR_BLACK)
    draw.text((width // 2, y), price, font=vol_font, fill=COLOR_BLACK, anchor="ma")
    draw.text((width - margin, y), vol_right, font=vol_font, fill=COLOR_BLACK, anchor="ra")
    y += text_height(draw, vol_font) + gap_sm

    y = _draw_thin_rule(draw, margin, y, width - margin, scale)
    y += gap_sm // 2

    name_h = text_height(draw, name_font, name)
    draw.text((width // 2, y), name, font=name_font, fill=COLOR_BLACK, anchor="ma")
    y += name_h + gap_md

    y = _draw_scotch_rule(draw, margin, y, width - margin, thick=rule_thick, gap=max(2, int(2 * scale)))

    meta_font = load_font("LibreBaskerville", "Italic", meta_size)
    date_str = when.strftime("%A, %B ") + str(when.day) + when.strftime(", %Y")
    city = "HOME EDITION"
    draw.text((margin, y), city, font=meta_font, fill=COLOR_BLACK)
    draw.text((width // 2, y), date_str, font=meta_font, fill=COLOR_BLACK, anchor="ma")
    draw.text((width - margin, y), when.strftime("%H:%M"), font=meta_font, fill=COLOR_BLACK, anchor="ra")
    y += text_height(draw, meta_font) + gap_sm

    y = _draw_scotch_rule(draw, margin, y, width - margin, thick=max(2, rule_thick - 1), gap=max(2, int(2 * scale)))
    return y + gap_sm // 2


def _draw_kicker(draw, text: str, font, x: int, y: int, color=COLOR_RED, scale: float = 1.0) -> int:
    kicker = (text or "").upper()
    draw.text((x, y), kicker, font=font, fill=color)
    return y + text_height(draw, font) + _sz(2, scale, 1, 8)


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
    scale: float,
    fill_body: bool = True,
) -> int:
    """Draw one story into a column box. Fills remaining vertical room with
    body copy when *fill_body* is True (no hard line caps that leave holes)."""
    pad = _sz(20, scale, 12, 40)
    if y >= max_y - pad:
        return y

    if is_hero:
        kicker_size = _sz(11 if is_landscape else 16, scale, 10, 36)
        head_max = _sz(34 if is_landscape else 52, scale, 22, 140)
        head_min = _sz(15 if is_landscape else 24, scale, 12, 48)
        deck_size = _sz(11 if is_landscape else 17, scale, 10, 36)
        body_size = _sz(11 if is_landscape else 16, scale, 10, 34)
        max_head_lines = 4 if is_landscape else 6
        head_frac = 0.42
    else:
        kicker_size = _sz(10 if is_landscape else 13, scale, 9, 28)
        head_max = _sz(18 if is_landscape else 28, scale, 14, 64)
        head_min = _sz(12 if is_landscape else 16, scale, 11, 32)
        deck_size = _sz(10 if is_landscape else 14, scale, 9, 28)
        body_size = _sz(10 if is_landscape else 15, scale, 9, 30)
        max_head_lines = 3 if is_landscape else 5
        head_frac = 0.35

    kicker_font = load_font("LibreBaskerville", "Bold", kicker_size)
    body_font = load_font("LibreBaskerville", "Regular", body_size)
    deck_font = load_font("LibreBaskerville", "Italic", deck_size)
    byline_font = load_font("LibreBaskerville", "Italic", max(9, body_size - 1))

    y = _draw_kicker(draw, story.get("section", "News"), kicker_font, x, y, scale=scale)
    if y >= max_y:
        return y

    room = max_y - y
    head_budget = max(
        _sz(48, scale, 36, 200),
        min(int(room * head_frac), _sz(220 if is_hero else 140, scale, 80, 400)),
    )
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
    y += _sz(4 if is_landscape else 6, scale, 2, 14)

    byline = f"By {story.get('source', 'Wire')}"
    if y + text_height(draw, byline_font) < max_y:
        draw.text((x, y), byline, font=byline_font, fill=COLOR_BLACK)
        y += text_height(draw, byline_font) + _sz(3, scale, 2, 10)

    if y + _sz(6, scale) < max_y:
        rule_w = min(_sz(48, scale, 28, 100), col_w // 3)
        draw.line([(x, y), (x + rule_w, y)], fill=COLOR_BLACK, width=max(1, _sz(1, scale, 1, 3)))
        y += _sz(6 if is_landscape else 8, scale, 4, 16)

    summary = (story.get("summary") or "").strip()

    if summary and y < max_y - _sz(12, scale):
        # Deck: first sentence or a short lead — never repeat below as body.
        deck = summary
        cut = summary.find(". ")
        if 40 < cut < 200:
            deck = summary[: cut + 1]
        elif len(summary) > 180:
            deck = summary[:177].rsplit(" ", 1)[0] + "…"

        deck_line_h = text_height(draw, deck_font) + _sz(2, scale, 1, 6)
        max_deck = min(3 if is_landscape else 4, max(1, (max_y - y) // max(1, deck_line_h) // 2))
        deck_lines = wrap_text(draw, deck, deck_font, col_w)[:max_deck]
        for line in deck_lines:
            if y + deck_line_h > max_y:
                break
            draw.text((x, y), line, font=deck_font, fill=COLOR_BLACK)
            y += deck_line_h
        y += _sz(3, scale, 2, 10)

        # Body: only the remainder of the summary after the deck sentence.
        rest = ""
        if cut >= 40 and deck.endswith("."):
            rest = summary[cut + 1 :].strip()
        elif len(summary) > len(deck) + 10:
            rest = summary[len(deck) :].strip(" …")

        if fill_body and rest and y < max_y - _sz(14, scale):
            body_lh = text_height(draw, body_font) + _sz(
                3 if not is_landscape else 2, scale, 2, 8
            )
            # Cap body by remaining room AND a modest max so short RSS
            # blurbs don't get stretched with crazy justification gaps.
            max_body_lines = max(1, (max_y - y - _sz(8, scale)) // max(1, body_lh))
            soft_cap = 18 if scale >= 1.35 else (14 if not is_landscape else 8)
            max_body_lines = min(max_body_lines, soft_cap)

            body_lines = wrap_text(draw, rest, body_font, col_w)[:max_body_lines]
            for i, line in enumerate(body_lines):
                if y + body_lh > max_y:
                    break
                # Only fully justify lines that are nearly full-width; short
                # lines (end of graf) stay flush-left to avoid rivers of space.
                natural = draw.textlength(line, font=body_font)
                last = i == len(body_lines) - 1 or natural < col_w * 0.82
                draw_justified_line(
                    draw, line, body_font, x, y, col_w, COLOR_BLACK, last_line=last
                )
                y += body_lh

    return y


def recommended_story_count(width: int, height: int) -> int:
    """More stories on larger canvases so columns stay full."""
    area = width * height
    # 13.3" ~ 1.92e6 → ~11; 31.5" ~ 3.7e6 → ~16
    if area >= 3_200_000:
        return 16
    if area >= 2_400_000:
        return 13
    if width > height and area < 500_000:
        return 6
    return 11


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
    scale = layout_scale(width, height)
    print(f"Layout scale {scale:.2f} for {width}x{height} ({'landscape' if is_landscape else 'portrait'})")

    margin = _sz(16 if is_landscape else 36, scale, 12, 72)
    footer_reserve = _sz(14 if is_landscape else 24, scale, 12, 48)
    y = render_masthead(
        draw, width, margin, paper_name, when, edition, is_landscape, scale
    )
    content_bottom = height - margin - footer_reserve

    if not stories:
        stories = list(FALLBACK_STORIES)

    hero = stories[0]
    rest = stories[1:]

    if is_landscape:
        gap = _sz(12, scale, 8, 28)
        left_w = int((width - 2 * margin - gap) * 0.58)
        right_x = margin + left_w + gap
        right_w = width - margin - right_x
        col_top = y
        _draw_column_rule(
            draw,
            margin + left_w + gap // 2,
            col_top,
            content_bottom,
            width=max(1, _sz(1, scale, 1, 3)),
        )

        n_right = min(len(rest), 4 if scale >= 1.2 else 3)
        y_left = _draw_story_block(
            draw, hero, margin, col_top, left_w, content_bottom,
            is_hero=True, is_landscape=True, scale=scale,
        )

        y_right = col_top
        for i, story in enumerate(rest[:n_right]):
            if y_right >= content_bottom - _sz(24, scale):
                break
            # Equal-ish slices; last story takes remainder to folio.
            remaining = n_right - i
            slice_h = max(
                _sz(80, scale),
                (content_bottom - y_right) // max(1, remaining),
            )
            soft_max = content_bottom if i == n_right - 1 else min(
                content_bottom, y_right + slice_h
            )
            y_right = _draw_story_block(
                draw, story, right_x, y_right, right_w, soft_max,
                is_hero=False, is_landscape=True, scale=scale,
            )
            if i < n_right - 1 and y_right < content_bottom - _sz(16, scale):
                y_right = _draw_thin_rule(
                    draw, right_x, y_right + _sz(4, scale), right_x + right_w, scale
                ) + _sz(4, scale)

        if rest[n_right:] and y_left < content_bottom - _sz(48, scale):
            y_left = _draw_thin_rule(
                draw, margin, y_left + _sz(6, scale), margin + left_w, scale
            ) + _sz(4, scale)
            _draw_story_block(
                draw, rest[n_right], margin, y_left, left_w, content_bottom,
                is_hero=False, is_landscape=True, scale=scale,
            )
    else:
        # Portrait: hero band, then multi-column secondary.
        hero_frac = 0.30 if scale >= 1.25 else 0.34
        hero_bottom_limit = y + int((content_bottom - y) * hero_frac)
        y = _draw_story_block(
            draw, hero, margin, y, width - 2 * margin, hero_bottom_limit,
            is_hero=True, is_landscape=False, scale=scale,
        )
        y += _sz(8, scale, 4, 18)
        y = _draw_scotch_rule(
            draw, margin, y, width - margin, thick=_sz(2, scale, 2, 6), gap=max(2, int(2 * scale))
        )
        y += _sz(8, scale, 4, 18)

        # Wider/taller pages can carry a fourth column.
        if width >= 1800:
            cols = 4
        elif width >= 1000:
            cols = 3
        else:
            cols = 2
        gap = _sz(16, scale, 10, 36)
        usable = width - 2 * margin - gap * (cols - 1)
        col_w = usable // cols
        col_top = y
        col_ys = [col_top] * cols

        rule_w = max(1, _sz(1, scale, 1, 3))
        for c in range(1, cols):
            rx = margin + c * (col_w + gap) - gap // 2
            _draw_column_rule(draw, rx, col_top, content_bottom, width=rule_w)

        # Round-robin into shortest column; last wave of stories extend to bottom.
        n_rest = len(rest)
        for i, story in enumerate(rest):
            c = min(range(cols), key=lambda idx: col_ys[idx])
            if col_ys[c] >= content_bottom - _sz(36, scale):
                continue
            cx = margin + c * (col_w + gap)
            # How many stories still need a home in the shortest-column sense
            remaining = max(1, n_rest - i)
            open_cols = sum(1 for cy in col_ys if cy < content_bottom - _sz(36, scale))
            per_open = max(1, (remaining + open_cols - 1) // max(1, open_cols))
            col_room = content_bottom - col_ys[c]
            share = max(_sz(160, scale, 100, 400), col_room // per_open)
            soft_max = min(content_bottom, col_ys[c] + share)
            # Final stories in each column run to the folio line.
            if i >= n_rest - cols or col_room < _sz(240, scale, 160, 500):
                soft_max = content_bottom
            if col_ys[c] > col_top + _sz(8, scale):
                col_ys[c] = _draw_thin_rule(
                    draw, cx, col_ys[c] + _sz(6, scale), cx + col_w, scale
                ) + _sz(6, scale)
            col_ys[c] = _draw_story_block(
                draw, story, cx, col_ys[c], col_w, soft_max,
                is_hero=False, is_landscape=False, scale=scale,
            )

        # Fill leftover column space with scaled "Also today" briefs.
        brief_font = load_font("LibreBaskerville", "Regular", _sz(12, scale, 10, 28))
        brief_head = load_font("LibreBaskerville", "Bold", _sz(13, scale, 11, 30))
        brief_lh = text_height(draw, brief_font) + _sz(3, scale, 2, 8)
        for c in range(cols):
            if col_ys[c] >= content_bottom - _sz(72, scale, 48, 140):
                continue
            cx = margin + c * (col_w + gap)
            yb = col_ys[c] + _sz(10, scale, 6, 20)
            yb = _draw_thin_rule(draw, cx, yb, cx + col_w, scale) + _sz(6, scale)
            draw.text((cx, yb), "ALSO TODAY", font=brief_head, fill=COLOR_RED)
            yb += text_height(draw, brief_head) + _sz(6, scale, 4, 14)
            # Unique briefs only — never recycle titles in one column.
            seen_brief: set[str] = set()
            briefs: list[dict[str, str]] = []
            for s in [hero] + rest:
                key = s["title"].lower()[:60]
                if key in seen_brief:
                    continue
                seen_brief.add(key)
                briefs.append(s)
            for b in briefs:
                if yb >= content_bottom - brief_lh:
                    break
                line = f"• {b['title']}"
                wrapped = wrap_text(draw, line, brief_font, col_w)[:2]
                for wl in wrapped:
                    if yb >= content_bottom - brief_lh:
                        break
                    draw.text((cx, yb), wl, font=brief_font, fill=COLOR_BLACK)
                    yb += brief_lh
                yb += _sz(4, scale, 2, 10)

    footer_font = load_font(
        "LibreBaskerville", "Regular", _sz(10 if is_landscape else 13, scale, 9, 28)
    )
    folio = (
        f"{(paper_name or 'THE DAILY FRAME').upper()}  ·  PAGE 1  ·  "
        f"{when.strftime('%B %d, %Y')}"
    )
    draw.text(
        (width // 2, height - margin // 2 - 2),
        folio,
        font=footer_font,
        fill=COLOR_BLACK,
        anchor="md",
    )

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
    # Default story count tracks canvas area (more on 31.5", fewer on 7.3").
    default_n = recommended_story_count(width, height)
    raw_max = config.get("max_stories")
    if raw_max in (None, "", 0, "0"):
        max_stories = default_n
    else:
        try:
            max_stories = int(raw_max)
        except (TypeError, ValueError):
            max_stories = default_n
    max_stories = max(3, min(18, max_stories))
    print(f"Story budget: {max_stories} (canvas default would be {default_n})")

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
