# Digital Frames for Home Assistant

Turn your digital photo frames into a gallery wall that Home Assistant actually controls — no vendor app, no cloud account required. Point it at your frames and start sending photos in minutes.

**Digital Frames** is the product name and HA domain (`digital_frames`, package `custom_components/digital_frames/`). Official Spectra e‑ink panels remain manufacturer **Fraimic** in the device registry. The photo library lives under `config/digital_frames_library/` (a leftover `config/fraimic_library/` is renamed on first load).

**Scope is local LAN only.** Meural cloud / Cognito is **out of scope** — use [HA-meural](https://github.com/GuySie/ha-meural) if you need cloud playlists. Drivers talk to devices on your network.

## Why you'll want this

- **No cloud in the loop.** Talk to frames over your own WiFi.
- **One tap turns a wall into a scene.** Match photos to frames and flip the whole wall from a dashboard, voice, or automation.
- **Your library, not a photo dump.** Upload once, organize into albums, reuse across frames and scenes.
- **A gallery wall out of the box.** Curated public-domain art packs install with one click.
- **Set it and forget it.** Daily agenda, skills, schedules.
- **Multi-vendor local drivers.** Fraimic / community e‑ink, Meural Canvas (local), experimental Samsung EM32DX.

## Quick start

1. Install through HACS: add [`https://github.com/dsackr/ha-digital-frames`](https://github.com/dsackr/ha-digital-frames) as a custom repository (category: Integration), then install **Digital Frames**.
2. Restart Home Assistant.
3. **Settings → Integrations → Add Integration**, search **Digital Frames**, add a frame. Wake the frame first so it's discoverable.

Sidebar panel: **Digital Frames** at `/digital_frames` (legacy `/fraimic` still opens the same panel).

More detail: [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Hardware & testing

We develop against hardware the maintainers own. Other vendors (and panel sizes we don't have) are **community-validated**.

**If you run Digital Frames on real hardware — especially Meural, Samsung EM32DX, or community e‑ink clones — please volunteer a smoke test and file an issue or PR with results.** That is the primary path for “does this work on device X?” coverage; CI cannot replace it.

| Driver | Status |
|--------|--------|
| Fraimic / Spectra e‑ink (official + common clones) | Primary development target |
| Meural Canvas **local** LAN | Implemented; volunteer reports welcome |
| Samsung EM32DX (MDC local) | Experimental; **needs volunteer hardware** |
| InkJoy | Out of scope for now (MQTT control plane) |
| Meural **cloud** | **Out of scope** (use HA-meural) |

## Credits

**Meural Canvas local protocol** — endpoint inventory for the on-device
`/remote/` HTTP API was published by **Guy Sie** in
[HA-meural](https://github.com/GuySie/ha-meural) (MIT). Our driver is
**local-only**, inspired by that documentation; we do not use Meural cloud
and do not vendor HA-meural code.

**Samsung EM32DX (experimental)** — MDC layout and WoL notes from
[fayep/Joyous](https://github.com/fayep/Joyous). Independent HA reimplementation;
not validated on real Samsung hardware in this project.

## License

MIT — see [LICENSE](LICENSE).

## Get involved

- ⭐ Star the repo if this is useful
- 🧪 **Volunteer hardware testing** — open an issue with device model + what worked
- 🐛 [Report an issue](https://github.com/dsackr/ha-digital-frames/issues)
- 🤝 Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)

## How this project tests itself

See [docs/KEY_PRODUCT_FLOWS.md](docs/KEY_PRODUCT_FLOWS.md) and
[TESTING_STRATEGY.md](TESTING_STRATEGY.md).
