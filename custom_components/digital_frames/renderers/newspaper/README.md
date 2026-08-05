# Newspaper Front Page (Live renderer)

Renders an **authentic multi-column newspaper front page** from free RSS
feeds onto Spectra 6 (or full-RGB preview) for Digital Frames.

This is a **first-party Live generator**, not a Gallery art pack. Home
Assistant runs it via `--render-only`; core owns delivery to the frame.

## Why not AI images?

E-ink (Spectra 6) has six fixed colors. Generative “newspaper look” images
dither, blur type, and need API keys. Real newspapers are **type + rules +
columns**. This renderer draws that natively in the panel palette—sharp
headlines, Scotch rules, kickers, bylines, justified body copy.

## Content sources (no API keys)

| Source id | Feed |
|-----------|------|
| `bbc`, `bbc_world`, `bbc_tech`, `bbc_politics` | BBC RSS |
| `npr`, `npr_politics` | NPR RSS |
| `guardian`, `nyt`, `politico` | Publisher RSS |
| `techcrunch`, `wired`, `ars`, `hn` | Tech desks |
| `tmz` | Gossip |
| `espn`, `sciam` | Sports / science |
| `reuters`, `ap` | Via Google News search RSS |
| `gnews_*` | Google News topic sections |

**Topic presets (`news_mix`):** `general`, `tech`, `politics`, `gossip`,
`world`, `business`, `science`, `sports`, `entertainment`.

**Fine control:** comma-separated `topics` (`tech,politics,gossip`) and/or
`sources` (`bbc,tmz,techcrunch`). Optional `custom_rss_url` for any RSS/Atom.

## Orientation

- **Portrait** (`height >= width`, e.g. 1200×1600): full-width hero + 3-column secondary.
- **Landscape** (`width > height`, e.g. 800×480): hero left, secondary stack right.

The Live skill path passes the **assigned frame’s** render resolution, so the
correct layout is chosen automatically.

## Standalone run

```bash
pip install Pillow
cp config.example.json config.json
# edit paper_name, news_mix, frame.ip_address, resolution, layout
python3 newspaper_renderer.py
```

Outputs: `newspaper_preview.png`, `newspaper.bin`.

Render only (HA skill contract):

```bash
python3 newspaper_renderer.py --render-only --config /path/to/config.json
```

Writes `newspaper_preview.png` + `newspaper.bin` next to the config.

## Config fields

| Field | Meaning |
|-------|---------|
| `paper_name` | Masthead title |
| `edition` | e.g. Morning Edition |
| `news_mix` | Preset topic bundle |
| `topics` | Optional override list |
| `sources` | Optional explicit feed ids |
| `custom_rss_url` | Extra RSS/Atom URL |
| `max_stories` | 3–12 (default 8) |
| `timezone` | IANA zone for dateline |
| `frame.resolution` | `[w, h]` |
| `frame.layout` | `split_half` or `sequential` |
| `frame.ip_address` | Standalone upload only |

## Dependencies

- Python 3.10+
- Pillow
- Network access to chosen RSS hosts (offline → built-in fallback edition)
