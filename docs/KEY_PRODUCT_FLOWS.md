# Key Product Flows

This is the catalog of **Digital Frames** Key Product Flows (KPFs) — the
user-facing capabilities the integration provides, kept current as the
source of truth for what "the product doing its job" means. (HA domain and
package path remain `fraimic`.) Each entry says what breaks for the end
user if the flow silently fails, and where it's tested today.

**Maintenance rule (binding for all contributors, human or AI):** any change
that adds or alters user-facing behavior must land together with (a) a new
or amended KPF entry here — including an updated test-status line — and
(b) the tests that entry claims. See [AGENTS.md](../AGENTS.md) for the full
requirement. New KPFs are appended (numbers are stable identifiers referenced
from code and test docstrings — never renumber existing entries).

See [TESTING_STRATEGY.md](../TESTING_STRATEGY.md) for the testing standard
this catalog feeds into, and [CONTRIBUTING.md](../CONTRIBUTING.md) for how
the codebase is laid out.

Test status legend:
- **Backend-tested** — `tests/python/` exercises the Python logic directly.
- **Panel-tested** — `tests/panel/` exercises the frontend against a mocked
  backend (see `tests/panel/README.md`); the Python side may still be
  untested.
- **Gap** — no automated coverage yet, backend or frontend.

---

## 1. Frame discovery & add-frame wizard
User chooses **Fraimic / e-ink clone** or **Meural Canvas (local)** from the
add-frame menu. Fraimic path scans the LAN or takes an IP and auto-detects
size/resolution; Meural path probes the local postcard API and stores a
`driver=meural` config entry.

**Background auto-discovery** (every ~20 min + on panel open) is **active
HTTP probing** of the HA host's /24 — not a shared broadcast protocol.
Each IP is asked `GET /api/info` (Fraimic family) then, if that fails,
`GET /remote/identify/` (Meural local). Hits feed HA's
`SOURCE_INTEGRATION_DISCOVERY` pipeline: Fraimic → name-device form;
Meural → `discovery_confirm_meural` form. Already-configured frames are
matched (device_key / Meural unique id / host) and IP is updated if the
frame moved; pending flows dedup via `unique_id`.
- **Entry points**: `config_flow.py` (`DigitalFramesConfigFlow.async_step_user` /
  `add_fraimic` / `add_meural` / `discovery_confirm_meural` / `pick_device` /
  `manual` / `name_device` / `dhcp` / `integration_discovery`),
  `helpers.py` (`probe_frame`, `probe_device_size`, `scan_subnet`,
  `detect_frame_type_from_info`), `meural.py` (`probe_meural`,
  `meural_unique_id`), `discovery.py` (`_async_scan_once`,
  `_match_and_update_meural`).
- **If it silently breaks**: users can't add frames at all, or duplicate
  entries get created for the same physical frame; Meurals never appear
  under Settings → Devices & Services → Discovered.
- **Test status**: Panel-tested (`flow-renderer.spec.js`,
  `frame-manage.spec.js`). **Backend-tested** —
  `tests/python/config_flow/test_config_flow_user_scan.py` (menu,
  Fraimic user/manual/pick_device/DHCP steps, Meural local add, Meural
  integration_discovery + confirm, size auto-detect, dedup);
  `tests/python/unit/test_meural.py` (`meural_unique_id`, dual-probe
  `scan_subnet`); `tests/python/unit/test_discovery_meural.py`
  (background sweep starts Meural discovery flow / skips configured).

## 2. Options flow (scan interval, orientation edge, 180° flip)
User edits power/sleep, flip, hanging edge, and advanced poll settings via HA's
Configure dialog (or the panel's embedded options flow). Labels come from
`strings.json` / `translations/en.json` under domain **digital_frames** (not
the legacy fraimic domain); the panel also has friendly fallbacks if
translations fail.

**Frame Type** (schema key `resolution` → `entry.data` size / packing profile)
is chosen at add time. Configure does **not** re-offer it when size is already
set. Legacy entries without a size still get a one-time Frame Type field.

Advanced settings (scan interval, fast poll when queued, hanging edge) and
actions (Reconnect Frame, Remove from HA) are under expandable Advanced Settings.
- **Entry points**: `config_flow.py` (`DigitalFramesOptionsFlow.async_step_init`), `digital-frames-panel.js` (`_renderFlowStep`, `_flowFieldLabelFallback`).
- **If it silently breaks**: settings don't stick, labels show snake_case
  keys, Frame Type reappears for normal entries, or the orientation lock
  resets when saving an unrelated field.
- **Test status**: Panel-tested (`flow-renderer.spec.js`, `frame-manage.spec.js`).
  **Backend-tested** — `tests/python/config_flow/test_config_flow_options.py`.

## 3. Coordinator polling & IP self-healing
Each frame is polled periodically for battery/wifi/firmware/dimensions; if
it goes silent for 3 polls, a subnet rescan finds its new IP (a DHCP-moved
frame).

**Setup soft-fail:** if the first poll fails (frame asleep / off-network),
the config entry still loads and the coordinator stays in `hass.data` so
send/queue and device_tracker wake-flush work. A hard `ConfigEntryNotReady`
would leave sleeping frames in `setup_retry` with no coordinator — panel
send then fails with "No frame coordinator found".

- **Entry points**: `coordinator.py` (`DigitalFramesCoordinator._async_update_data`,
  `_async_try_find_new_host`, `_maybe_persist_fingerprint`),
  `__init__.py` (`async_setup_entry` first_refresh soft-fail).
- **If it silently breaks**: sensors go "unavailable" forever after a router
  reassigns the frame's IP; the user thinks the frame is dead; or sleeping
  frames cannot accept a queued send because the entry never finishes setup.
- **Test status**: **Backend-tested** —
  `tests/python/coordinator/test_coordinator_polling.py`,
  `test_coordinator_concurrency.py`,
  `tests/python/setup/test_init_setup_entry.py`
  (`test_offline_fraimic_frame_keeps_coordinator_for_send`).

## 4. Send image now (pull-first + optional push) — the core send primitive
Every "send to frame" path (service, raw upload, library send, scene send,
schedule fire) funnels through one delivery mechanism so a **battery /
deep-sleeping** Fraimic-family frame still gets the image without HA having
to "catch" it awake.

**Primary delivery (clone / battery, Fraimic-cloud-style pull):**
1. HA **stages** the packed Spectra `.bin` under
   `config/digital_frames_cache/pull/<entry_id>.bin`.
2. HA exposes it unauthenticated at
   `GET /api/digital_frames/pull/{pull_token}/image.bin`
   (token is stable per config entry; security is unguessability, same idea
   as Samsung's staged content URL).
3. When the frame wakes (timer), it **GETs** that URL and paints, then deep
   sleeps again (unless always-on).
4. On setup / send / options save, HA best-effort **provisions** the frame
   with `POST /sleepconfig` first (`minutes`, `active_sec`, `always_on`)
   then `POST /pullurl`. Sleep/always-on is applied even if pullurl fails.
   Requires clone firmware that understands `always_on` (pre-always-on
   builds ignore the field and keep battery sleep).
5. Once successfully retrieved by the frame (GET pull bin) or successfully pushed (POST /api/image), HA deletes the staged `.bin` from disk and clears the pending send queue metadata.

**Secondary (immediate update if the frame is already online):**
HA still `POST /api/image` after staging so an awake panel updates without
waiting for the next sleep cycle. If push fails because the frame is
asleep, the staged pull payload is enough — success is reported as
`delivery: pull` / `queued: true` rather than "lost send".

**Wake / flush triggers (after a send was queued while the frame slept):**
1. **Network presence (default path for push-on-wake):** the coordinator
   finds a matching `device_tracker.*` by frame IP or MAC (UniFi Network,
   Omada, ASUSWRT, or any other HA network-presence integration — not
   UniFi-specific) and, on `not_home` → `home`, calls
   `_async_flush_pending_send`. No accelerated probing of the frame.
2. **Successful normal status poll** at the user's `scan_interval` (default
   5 minutes) while something is still pending — opportunistic only, not a
   wake hunt.
3. **Advanced option `fast_poll_when_queued` (default off):** while a send
   is queued, poll the frame every 30s until it answers. Intended for
   installs with no network device tracker. Exposed under Advanced Settings
   in the frame options UI.

**On deck (what is waiting):** while `pending_send` is set, the product
surfaces the queued image as "on deck" — not only a boolean:
- `GET /api/digital_frames/frames` includes `queued`, `queued_image_id`,
  `queued_at`
- `sensor.*_queued_image` is `queued`/`idle` with attributes `image_id`,
  `queued_at`
- Wall tiles badge **on deck** (orange) with the waiting thumbnail; Frame
  Information shows an **On deck** row; Lovelace card badge **ON DECK**

Image upload timeout for the push path still comes from the panel profile
(`FrameType.send_timeout_s` / `send_timeout_for_entry`) — default 240s for
slow ESP32 sequential panels (7.3").

- **Entry points**: `coordinator.py` (`async_send_image_or_queue`,
  `async_stage_pull_bin`, `async_provision_frame_pull`, `async_send_image`,
  `_async_flush_pending_send`, `async_clear_pull_bin`,
  `async_setup_tracker_watch`, `async_teardown_tracker_watch`,
  `_async_tracker_state_changed`), `http_api.DigitalFramesFramePullBinView`,
  `frame_types.send_timeout_for_entry`, options
  `const.CONF_FAST_POLL_WHEN_QUEUED`; clone firmware
  (`fraimic-clone-7.3in`) `POST /pullurl`, `POST /sleepconfig`, pull-on-wake.
- **If it silently breaks**: sleeping frames never update; pull URL not
  provisioned; always-on ignored; HA "send" claims success but nothing is
  staged under `digital_frames_cache/pull/`; the staged bin is never cleared,
  causing the frame to repeatedly download and redraw the same image on every
  wake; or push-on-wake never fires because no `device_tracker` matches and
  fast poll is off (clone pull still works; push-only frames wait for a
  successful normal poll or manual wake).
- **Test status**: **Backend-tested** —
  `tests/python/coordinator/test_coordinator_queue_on_sleep.py` (online
  push+pull, offline stage-for-pull, default no fast poll, optional fast
  poll, provision always_on flag, token URL shape, pull-only pending flush,
  pull view cleanup on get),
  `tests/python/coordinator/test_coordinator_device_tracker.py` (IP/MAC
  match, home transition flushes, teardown),
  `tests/python/setup/test_entities.py` (queued sensor attrs image_id /
  queued_at). **Panel-tested** — `tests/panel/dashboard.spec.js` (on deck
  wall badge + Frame Info row), `tests/panel/fraimic-card.spec.js` (ON DECK
  badge).

## 4b. Frame power options (sleep interval + always-on)
User-facing controls on the frame's **Configure / options** form and the
Digital Frames panel frame-settings flow (standard fields, not Advanced).

For official Fraimic hardware (which does not honor deep sleep settings),
these controls are disabled/greyed out. For clones, they are fully editable.
The actual keep-awake setting currently active on the frame is parsed from
its HTML `/info` page during successful polls and displayed in the Frame
Information popup.

| Option key | UI label (en) | Meaning |
|---|---|---|
| `frame_always_on` | Always on (keep-awake, like official Fraimic) | Frame stays on Wi‑Fi; no deep sleep. High battery cost. |
| `frame_sleep_minutes` | Minutes between image checks | Battery: deep-sleep period. Always-on: pull re-check period. |

Defaults: always-on **off**, sleep **15** minutes. Saving options (or a
successful send/setup while the frame is online) POSTs them to the frame
via `/sleepconfig`. If the frame is asleep at save time, the next
successful online provision applies them.

- **Entry points**: `config_flow.DigitalFramesOptionsFlow`,
  `const.CONF_FRAME_ALWAYS_ON` / `CONF_FRAME_SLEEP_MINUTES`,
  `coordinator.async_provision_frame_pull`,
  `helpers.parse_keep_awake_from_html` / `helpers.parse_sleep_minutes_from_html`,
  `digital-frames-panel.js` (standard field order, field disabling/greying),
  `strings.json` / `translations/en.json`.
- **If it silently breaks**: users cannot set sleep cadence; always-on
  never reaches the device; panel hides the field under Advanced only; official
  fraimics let users change options that won't work on the hardware.
- **Test status**: **Backend-tested** —
  `tests/python/config_flow/test_config_flow_options.py` (schema exposes
  both keys, defaults, save round-trip, validation),
  `tests/python/unit/test_helpers_info.py` (HTML parsers for keep-awake),
  `tests/python/coordinator/test_coordinator_polling.py` (coordinator parses and updates settings).
  **Frontend-tested** —
  `tests/panel/frame-manage.spec.js` (greying out options for official Fraimic, displaying actual status in settings popup).

## 4c. Spectra 6 color test pattern (built-in library asset)
On integration load, Digital Frames seeds a **six-box Spectra E6 color test**
into the shared library (album **Test Patterns**, voice name
**color test**, tag `spectra6_color_test`) if it is not already
present. Boxes use the same real-world RGB targets as
`image_converter.SPECTRA6_REAL_WORLD_RGB` (black / white / yellow / red /
blue / green) so each region quantizes to one hardware nibble — useful for
verifying panel wiring, orientation, and packing on clones (e.g. 7.3" ESP32).

- **Entry points**: `test_patterns.py` (`build_spectra6_color_test_png`,
  `async_seed_spectra6_color_test`), packaged
  `assets/spectra6_color_test.png`, seeded from `__init__.async_setup`.
- **If it silently breaks**: library missing Test Patterns after install;
  colours dithered wrong (RGB table drifted from converter).
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_test_patterns.py`.

## 5. HA services (send_image, send_scene, restart, sleep, refresh, generate_ai_image)
Lets automations/scripts drive a frame: send an arbitrary media item, send
a named scene, or issue restart/sleep/refresh commands.
- **Entry points**: `__init__.py` (`_register_services`, `_handle_send_image`,
  `_handle_send_scene`, `_handle_generate_ai_image`, `_resolve_media_path`).
- **If it silently breaks**: automations calling `fraimic.send_image` /
  `send_scene` fail or send the wrong image; a path-traversal bug in media
  resolution could leak files. `_resolve_media_path` only recognizes
  `media-source://` and `/media/`-prefixed content ids — anything else is
  rejected outright (a real bug, fixed in the July 2026 code review: it
  used to fall through unchanged, letting a direct service call read any
  HA-process-readable file via `send_image`).
- **Test status**: **Backend-tested** — `tests/python/setup/test_services.py`
  (command services, send_image media resolution + path-escape rejection,
  send_scene aggregation semantics, rejection of an unprefixed arbitrary
  filesystem path).

## 6. Voice/AI: "generate an image of X...", "show [image name] on [frame]", and "put a picture of [tag name] on [frame]"
Custom Assist/LLM intents to generate an AI image, display a specific library image on a named frame, or randomly select and display an image matching a custom tag by voice.
- **Entry points**: `intent.py` (`DigitalFramesGenerateAIImageIntent`,
  `DigitalFramesShowImageIntent`, `_match_frame_device_id`, `_match_by_tag`).
- **If it silently breaks**: the voice command errors out, fails to find the
  image or tags, or resolves to the wrong frame.
- **Test status**: **Backend-tested** — `tests/python/setup/test_intent.py` (covers exact voice name matches and random tag-based selections).

## 7. Image conversion pipeline (Spectra 6 .bin encoding + decoding)
Converts any Pillow-readable image into the frame's proprietary packed-
nibble binary format: auto-rotate, cover-crop, manual crop, canvas
rotation, dithering, and two PanelCodecs (split-half vs. sequential).
Call sites that produce wire payload for a send should use
`panel_codec.encode_for_panel*` (codec selection by panel geometry);
packing primitives remain in `image_converter.py`. Also the reverse
direction: unpacking a `.bin` back into an image, used to build a preview
thumbnail for sends that only ever see packed bytes (the xOTD/skill text
renderer — see KPF 28/29).
- **Entry points**: `panel_codec.py` (`encode_for_panel`,
  `encode_for_panel_with_preview`, `encode_path_for_panel_with_preview`),
  `image_converter.py` (`convert_image*`, `_process`, `_process_cropped`,
  `_pack_to_spectra6_bin` / `_pack_p_image_fast`, `default_cover_crop_box`,
  `unpack_spectra6_bin`, `preview_png_from_bin`).
- **If it silently breaks**: this is the "garbled/duplicated image on the
  physical frame" failure the module's own docstring calls out — no
  exception, just a wrong picture on real hardware. A broken unpacker is
  the softer cousin: wrong/blank card and panel thumbnails after xOTD sends.
  A real instance of exactly this class, fixed in the July 2026 code
  review: `_resize_cover_centered` floored its scale factor via `int()`
  instead of rounding up, so floating-point error routinely left the
  resized image 1px short on the governing axis — a stray unfilled white
  row/column at the canvas edge on the default (non-manual-crop) pipeline
  every ordinary send uses. Reproduced against the real registered 13.3"
  resolution; fixed via `math.ceil` (any resulting 1px overage is trimmed
  by the existing centered crop, so this can only shrink the gap, never
  introduce one).
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_image_converter.py` (including the cover-crop
  resize fully covering its canvas with no unfilled edge gap, reproduced
  against a known-affected source size and registered resolution),
  `tests/python/unit/test_panel_codec.py`, including pack→unpack
  byte-exact round-trips against both byte layouts. Flagged as the riskiest
  silent-failure surface in the codebase in the initial gap analysis; also
  has a standalone byte-identity script (`scripts/verify_packing.py`) run
  manually against real photos when touching either packer.

## 8. Shared image library: upload, list, stream original, thumbnail, voice name, tags, orientation lock
Users upload photos into one shared pool; images are listed/streamed for
the panel's grids with on-the-fly cached thumbnails, and can carry user-defined
voice names, tags, and orientation locks (for compatibility filtering). Wire-payload (`.bin`) cache keys
include PanelCodec id (`codec_id`) under
`bin/<WxH[variant]>/<codec_id>/` so sequential vs split-half packs never
collide; pre-Phase-2 resolution-only bins still serve as a read fallback.
- **Entry points**: `library.py` (`LibraryManager.async_upload` /
  `list_images` / `get_original` / `get_thumbnail` / `async_get_bin_for_send` /
  `async_set_image_voice_name` / `async_set_image_tags` / `async_set_image_orientation_lock`,
  `LocalLibraryBackend` / Dropbox / Drive `_bin_path` + `bin_file_ids`,
  `_safe_image_id`), `library_http.py` (`DigitalFramesLibraryImageVoiceNameView`,
  `DigitalFramesLibraryImageTagsView`, `DigitalFramesLibraryImageOrientationLockView`).
- **If it silently breaks**: uploads silently fail per-file in a batch,
  thumbnails go stale/broken, voice name/tag/orientation-lock edits fail to persist, a
  7.3" send reuses 13.3"-layout bytes (wrong codec cache), or — a real bug
  found and fixed in the July 2026 code review — an unsanitized `image_id`
  reaching `_bin_path`/`_thumb_path` directly (rather than via a manifest
  lookup) lets a crafted id read or delete a `.bin`/thumbnail file outside
  the library via path traversal. Every call site that builds a path
  straight from a caller-supplied `image_id` must go through
  `_safe_image_id` first. Also fixed in that review: `_openAlbum`/
  `_loadLibrary` had no staleness guard, so switching albums quickly could
  let an older, slower album load resolve after a newer one and leave the
  breadcrumb title naming a different album than the grid actually shows —
  both now share a token that discards a superseded load's result.
- **Test status**: Panel-tested (`dashboard.spec.js` covers grid rendering, album navigation, voice name, and tags configuration/clearing, and switching albums quickly renders the last-picked one even when its response resolves out of order; `lazy-thumbs.spec.js`; `crop-aspect-ratio-lock.spec.js` covers orientation lock picker dimming and sending validation).
  **Backend-tested** (local backend) —
  `tests/python/library/test_library_local_backend.py` (single/multi
  upload, undecodable-bytes tolerance, thumbnail cache generation/reuse,
  delete purges original + thumbnails, voice name and tags updates);
  `tests/python/library/test_library_crop_albums_backfill.py` (codec-keyed
  bin cache + legacy path fallback);
  `tests/python/library/test_crop_aspect_ratio_and_lock.py` (orientation lock persistence and send compatibility blocking);
  `tests/python/library/test_library_image_id_traversal.py` (traversal/malformed
  `image_id` rejected by send/thumbnail, no-ops on delete, a real id still
  works end to end, and — closing a July 2026 code-review test-coverage gap
  (issue #12) where only the local backend's path was exercised —
  `DropboxLibraryBackend._bin_path`/`async_get_bin` reject a traversal
  `image_id` via `_safe_image_id` before any Dropbox API request goes out,
  and `GoogleDriveLibraryBackend.async_get_bin`/`async_delete_image` treat a
  traversal id as an ordinary manifest miss with no Drive request, since
  that backend never builds a path from `image_id` at all).

## 9. Library storage backend switching (Local / Dropbox / Google Drive)
User can point the whole library at Dropbox or Google Drive instead of
local disk, with validation before switching and fallback to local on
failure.
- **Entry points**: `library.py` (`LibraryManager.async_set_backend` /
  `async_load`, `DropboxLibraryBackend`, `GoogleDriveLibraryBackend`),
  `library_http.py` (OAuth start/callback/redirect-uri views).
- **If it silently breaks**: switching backends fails and silently reverts
  to local without the user noticing, stranding photos on the wrong
  storage. The Google OAuth callback (`DigitalFramesLibraryGoogleOAuthCallbackView`)
  is deliberately unauthenticated (a plain browser redirect target,
  protected instead by a one-time `state` token) — its rendered
  error/status message must stay HTML-escaped, or a crafted callback URL
  becomes a pre-auth reflected-XSS vector. Two real bugs fixed in the July
  2026 code review: Dropbox's `async_delete_image` and Google Drive's
  `_delete_file` both discarded their delete response unchecked, so a
  transient failure (expired token, rate limit, 5xx) was treated as
  success and the manifest entry removed regardless — orphaning the file
  remotely with no record left to reference or retry against. Both now
  check the response status and raise `LibraryBackendError` before the
  manifest is touched (tolerating 404/409 "already gone" as success).
  That fix exposed a follow-on bug (found by the July 2026 max-effort code
  review, issues #16/#4): Google Drive's `async_delete_image` and
  `async_delete_bin` batched several real Drive deletes (primary file +
  every cached bin variant) behind a single manifest write at the end, so
  a delete that failed partway through the batch left the deletes that
  *did* succeed unpersisted — a fresh manifest read (HA restart, another
  client) would still reference files already gone from Drive, 404ing on
  next download. Both methods now persist the manifest after each
  individual successful delete, so partial progress is never lost even if
  a later delete in the same call raises.
- **Test status**: **Gap** — Dropbox/Google Drive backends' OAuth
  token exchange/refresh flows and the rest of their read/write paths are
  the remaining, highest-effort slice of Phase 5 (heavy request/response
  mocking); not yet done. **Backend-tested** (narrow) —
  `tests/python/library/test_library_http_oauth_callback.py` covers the
  one security-relevant piece of the callback view: its `_page()` renderer
  HTML-escapes the message it's given.
  `tests/python/library/test_library_cloud_backend_deletes.py` covers the
  delete-failure fix directly: both backends raise on a failed remote
  delete without touching the manifest, both correctly tolerate an
  already-deleted (404/409) response as success, and both Google Drive
  delete methods persist every already-succeeded delete when a later
  delete in the same call fails partway through.

## 10. Library discovery (adopt externally-added files)
Dropbox-only: photos dropped directly into the user's Dropbox get adopted
into the manifest and queued for `.bin` generation.
- **Entry points**: `library.py` (`DropboxLibraryBackend.async_discover_new_files`,
  `LibraryManager.async_discover`), `library_http.py`.
- **If it silently breaks**: dropped photos never appear in the panel, or
  get re-discovered forever if inbox removal fails.
- **Test status**: **Gap** — depends on the Dropbox backend above; same
  remaining slice of Phase 5.

## 11. Library `.bin` cache & background backfill
Every image gets a per-resolution `.bin` pre-generated in the background
across all configured frame resolutions/orientations; a send before
backfill finishes still works via on-demand conversion+cache.
- **Entry points**: `library.py` (`_schedule_backfill`,
  `_async_backfill_worker`, `async_get_bin_for_send`).
- **If it silently breaks**: sends are slow, or a send uses stale bytes
  after a crop change if cache invalidation is missed.
- **Test status**: **Backend-tested** —
  `tests/python/library/test_library_crop_albums_backfill.py` (backfill
  generates bins for configured frame resolutions, on-the-fly generation
  + caching when uncached, cache-hit skips reconversion, `pack_method`
  override bypasses the cache without polluting it).

## 12. Manual crop editing per image/aspect ratio
User can save a manual crop rectangle for one image. Crops are saved by aspect ratio keys (e.g. ratio:1.7778), making them shared across all frames with matching aspect ratios, with exact resolution and orientation fallbacks, invalidating cached renders.
Reachable from three places: the Library shelf's crop editor, the wall
image picker's "✂ Adjust Crop" (hands the staged/on-frame photo to the
same editor pre-targeted at that frame), and the Lovelace card's own
crop editor (KPF 29), whose "Save & Send" persists the crop then
immediately re-sends so the physical frame updates.
- **Entry points**: `library.py` (`async_set_crop`, `async_clear_crop`),
  `library_http.py` (`DigitalFramesLibraryCropView`), `digital-frames-panel.js`
  (`_openEditor`, `_cropFromWallPicker`), `digital-frames-card.js` (`_openCrop`,
  `_cropSaveSend`).
- **If it silently breaks**: a saved crop doesn't apply on next send, or
  clearing a crop leaves stale cached renders for the same orientation.
  Two real bugs in the panel's editor, fixed in the July 2026 code review:
  (1) `_openEditor` had no staleness guard, so closing the editor and
  reopening it for a different image while the first image's fetch was
  still in flight let that stale fetch overwrite the *current* editor's
  blob URL/dimensions after the fact — visibly swapping the picture back
  to the wrong image while the save target stayed the new one, corrupting
  which image a saved crop applied to; (2) the Save Crop/Send buttons
  weren't disabled during that same load window, so clicking either
  immediately after opening could submit `{width: 0, height: 0,
  crop_box: null}`. Both editor open/close now share a per-open state
  object identity check, and the buttons stay disabled until the image
  finishes loading.
- **Test status**: Panel-tested (`walls-crop-button.spec.js` — enable/
  disable rules and the wall-picker → editor handoff with the frame
  pre-targeted; `fraimic-card.spec.js` — the card's full crop flow
  including the save + re-send round trip against the mock server;
  `walls-image-picker.spec.js` covers the surrounding picker UI;
  `dashboard.spec.js` covers the Library shelf's editor: a stale fetch for
  a previously-open image cannot swap the picture back after closing and
  reopening for a different one, and Save Crop stays disabled until the
  image finishes loading; `crop-aspect-ratio-lock.spec.js` covers aspect-ratio target options compatibility disablement).
  **Backend-tested** — `tests/python/library/test_library_crop_albums_backfill.py`
  (exact-resolution save invalidates that bin, fallback-orientation save
  invalidates every matching resolution, clear reverts + invalidates,
  unknown image raises);
  `tests/python/library/test_crop_aspect_ratio_and_lock.py` (saves ratio keys and resolves crops by exact/epsilon aspect ratio).

## 13. Album management (tag, rename, delete, batch-add)
Photos can be tagged into any number of albums; albums are emergent from
tags, with rename/delete affecting every tagged image in one bulk write.
- **Entry points**: `library.py` (`async_list_albums`,
  `async_set_image_albums`, `async_rename_album`, `async_delete_album`),
  `library_http.py`.
- **If it silently breaks**: rename/delete misses images, or the default
  "Images" album gets renamed/deleted, breaking the "always at least one
  album" invariant.
- **Test status**: Panel-tested indirectly (`walls-addon-album-lock.spec.js`).
  **Backend-tested** — `tests/python/library/test_library_crop_albums_backfill.py`
  (create via tagging, rename/delete across multiple images, default-album
  protections, empty-name/empty-selection rejection).

## 14. Send library image to a frame
The panel's "Send to Canvas" — reuses/generates the cached `.bin` for that
frame's resolution and delivers or queues it.
- **Entry points**: `library_http.py` (`DigitalFramesLibrarySendView`),
  `library.py` (`async_get_bin_for_send`), `coordinator.async_send_image_or_queue`.
- **If it silently breaks**: sends the wrong crop/orientation, or the
  packer A/B override leaks into the normal cache.
- **Test status**: Panel-tested (`packtest.spec.js`, `dashboard.spec.js`).
  The underlying `async_get_bin_for_send` (KPF 11) and
  `async_send_image_or_queue` (KPF 4) are both backend-tested; the HTTP
  view wrapper itself (`DigitalFramesLibrarySendView`'s request/response
  marshaling) is still a **Gap**.

## 15. Direct upload-and-send (no library)
Card/API path: upload an image directly to a specific frame via multipart,
bypassing the library entirely (the Lovelace card's and wall picker's
upload buttons). Note: because these bytes never enter the library, the
sent photo can't be re-cropped afterwards (KPF 12's crop editors are
deliberately disabled for it).
- **Entry points**: `http_api.py` (`DigitalFramesSendImageView`,
  `resolve_frame_by_entity`), `digital-frames-card.js` (`_stageFile`/`_send`),
  `digital-frames-panel.js` (`_sendFromWallPicker`).
- **If it silently breaks**: card sends silently fail, or the wrong frame
  receives the image.
- **Test status**: Panel-tested (`fraimic-card.spec.js` — upload staging
  and the multipart `send_image` POST with the right `entity_id`;
  `walls-send-and-offwall.spec.js` for the wall picker side). The Python
  view itself (`DigitalFramesSendImageView`'s request/response marshaling) is
  still a **Gap** along with the rest of the `*_http.py` view layer (see
  the coverage summary below).

## 16. Scenes: named multi-frame image assignments (CRUD + send)
User builds a named "scene" (frame→image mapping) and sends every frame's
assigned image at once; exposed as `scene.*` entities for voice control.
- **Entry points**: `scenes.py` (`SceneManager.async_save_scene` /
  `async_delete_scene` / `async_send_scene` / `async_send_mappings`),
  `scene.py`, `scenes_http.py`.
- **If it silently breaks**: partial-failure semantics could be wrong (one
  dead frame blocking the whole scene, or a fully-failed scene reporting
  success).
- **Test status**: Panel-tested (`walls-scenes-merge.spec.js`,
  `walls-flow.spec.js` — scene CRUD outside the Walls UI isn't directly
  covered). **Backend-tested** — `tests/python/managers/test_scenes.py`
  (CRUD, duplicate-name rejection, send_mappings partial-failure fan-out,
  schedule-disarm on delete).

## 17. Gallery art packs (curated bundles, install/sync/uninstall)
**(Content platform: Gallery tab — was "Add-ons / scene packs".)** One-click
install of a public-domain image collection into the library; optionally
auto-builds an orientation-aware scene (`create_scene=true` default).
Library-only install is supported (`create_scene=false` / panel
"Library only"). Sync repairs partial installs.

**Marketplace foundations (Phase 7):** catalog `schema_version` + per-pack
`version` / `min_integration` / `featured`; packs requiring a newer
integration are hidden; per-image `sha256` verified on download when
present; Gallery UI has search + Featured strip. Community PRs are
images/JSON only (see frame-addons `docs/CATALOG_SCHEMA.md`).
- **Entry points**: `scene_packs.py` (`ScenePackManager.async_install_pack` /
  `async_sync_pack` / `async_uninstall_pack`, `_pack_compatible`, checksum
  in `_async_import_image`), `scene_packs_http.py`
  (`GET` returns `catalog` meta; `POST …/install` body `create_scene`),
  panel Gallery (`_installPack`, `_renderScenePacks`, `#gallery-search`).
- **If it silently breaks**: an interrupted install leaves orphaned images
  untracked, blocking reinstall; uninstall can leave stray images if some
  deletes fail; library-only installs unexpectedly create scenes (or vice
  versa); corrupted CDN bytes install silently (checksum bypassed/missing).
  A real bug fixed in the July 2026 code review: `async_uninstall_pack`
  fetched the pack from the remote catalog (`async_get_pack`) *after*
  already deleting the scene, purely to read a fallback name it never
  actually needed (`installed["album"]` is always recorded at install
  time) — an unreachable catalog, or one that no longer listed this
  `pack_id`, left the scene gone and the pack stuck "installed" forever,
  every retry failing identically. Uninstall no longer touches the
  network at all.
- **Test status**: Panel-tested indirectly (`addons-categories.spec.js`;
  `addons-catalog-refresh.spec.js` covers the catalog re-fetching on tab
  activation and panel revive rather than only once at initial load).
  **Backend-tested** — `tests/python/managers/test_scene_packs.py`
  (install success/partial-failure/all-fail, **library-only create_scene=False**,
  already-installed guard, uninstall scene+image cleanup and untag-vs-delete,
  uninstall succeeds when the remote catalog is unreachable, sync recovery
  by filename, orientation-aware assignment, **checksum mismatch**,
  **min_integration filter**, version tuple helpers).

## 18. Scene-pack "widgets" (RETIRED — use Live Agenda)
**Retired in Content Platform Phases 5–6.** Widget runtime code
(`_async_install_widget` / schedulers / frame-IP subprocess) is **deleted**.
Catalog fetch filters out `type=widget`. Daily Agenda is a Live skill
(`content_mode=agenda`) — see **KPF 28**. One-time migration
`_async_migrate_agenda_widget` still converts leftover `daily_agenda`
widget install records into the built-in Live skill + schedule; uninstall
still rmtree's leftover addon dirs.
- **Entry points (legacy remnants)**: migration in `__init__.py`;
  widget branch in `async_uninstall_pack` only.
- **If it silently breaks**: upgraded users lose their morning agenda after
  upgrade (migration fails).
- **Test status**: **Backend-tested** —
  `tests/python/setup/test_agenda_migration.py` (widget→skill migration,
  catalog filters widgets). Panel widget-form specs removed in Phase 6.

## 19. Walls: virtual multi-frame layout (panel-local state)
User arranges a subset of frames on a free-form canvas mirroring how
they're physically hung; custom walls and a default "All Frames" wall are
selected via visual picker tiles, and the default wall self-syncs with
configured frames (guaranteeing all frames stay placed on the default wall;
exclusions/tombstones are ignored). Hovering over a frame tile displays a translucent overlay
with four corner quadrants for quick actions: selecting an image, removing the tile
from the wall, viewing frame info (name, IP, orientation, battery percentage), or configuring the
frame. Pulling a frame off the default wall removes it from the canvas locally but does not save
that removal to the backend (reverting to showing all frames when switching screens or refreshing).
Save requests for the default wall preserve any omitted frame placements at their last known positions.
When the default wall is modified (moving frames or pulling them off), an inline banner offers to save the configuration as a new custom wall.
An "Align Wall to Grid" option allows users to snap all
placed frames on a wall to a clean structured layout. When aligning selected
frames, if they would overlap each other, they are automatically spaced out
along the other axis rather than producing a collision error.
- **Entry points**: `walls.py` (`WallManager.async_save_wall`,
  `async_ensure_default_wall`, `async_ensure_placement`, `async_prune_entry`), `walls_http.py`,
  `digital-frames-panel.js` (`_renderWallStrip`, `_openWall`, `_alignWallSelection`, `_alignWallToGrid`, `_openFrameSettingsMenu`, `_openFrameConfigureFlow`, `_onWallPointerUp`, `_checkDefaultWallModified`, `_updateWallOfferBanner`, `_saveAsCustomWall`).
- **If it silently breaks**: removed/re-added frames haunt old layouts,
  the default wall stops tracking newly-added frames, or alignment features
  produce layout overlaps or throw unexpected error banners. A real bug
  fixed in the July 2026 code review: `_append_placement`'s "is this row
  empty" check trusted `len(wall.placements) % _MAX_FRAMES_PER_ROW == 0`
  rather than scanning the row's actual occupants — removing one frame
  from a full row of 4 could drop the count back to a multiple of 4 while
  the row still held tiles, so the next auto-placed frame landed directly
  on top of a survivor instead of finding an open slot. The row-occupancy
  scan the non-zero-column case already did correctly is now unconditional.
  Also fixed in that review: `_wallBeginDrag`/`_wallBeginMarquee` had no
  guard against a pre-existing in-progress drag/marquee, so a second
  pointerdown before the first's pointerup (overlapping pointer input —
  multi-touch/stylus+mouse, common on the touchscreen tablets this
  dashboard is often wall-mounted on) overwrote the tracking field without
  removing the first drag's ghost element, leaking it permanently and
  corrupting which drag the eventual pointerup finalized. Both now cancel
  whatever's in flight before starting a new one. A follow-up bug from that
  same fix: `_wallBeginDrag` called the new cancel-in-flight guard *before*
  validating that its `entryId` resolved to a real frame, so a begin-drag
  attempt that itself failed (a stale `entryId`, e.g. its config entry was
  removed elsewhere before this client's wall view re-rendered) still tore
  down a different, legitimately in-progress drag as a side effect. Fixed
  by resolving and validating `frame` before calling
  `_wallCancelInProgressDrag()`, so a failed begin-drag is now a true no-op.
  Cleanup from the same review (issue #14): `_onWallPointerUp` had its own
  inline copy of `_wallCancelInProgressDrag`'s ghost-removal/`dragging`-class
  teardown (one drag/group-drag cleanup implemented twice) — a future
  change to what a drag/group entry needs torn down could be applied to one
  copy and missed on the other, reintroducing the exact leak class this
  review just fixed. `_onWallPointerUp` now calls
  `_wallCancelInProgressDrag()` instead of duplicating its body.
- **Test status**: Extensively panel-tested (`walls-drag.spec.js` —
  including a second pointerdown before the first drag ends no longer
  leaking a ghost element, a failed begin-drag with a stale entryId no
  longer cancelling an unrelated in-progress drag, and — closing a July
  2026 code-review test-coverage gap (issue #13) where only the drag half
  of this fix had a regression test — a second marquee-select start before
  the first ends no longer leaking a `.wall-marquee` box either,
  `walls-default-and-collision.spec.js` (including temporary frame removal
  without backend save, default wall layout reversion on reopen, and the
  "Save as Custom Wall" inline offer banner),
  `walls-multiselect.spec.js` — including
  alignment auto-spacing and Align Wall to Grid logic,
  `walls-flow.spec.js`, `walls-scenes-merge.spec.js`,
  `walls-send-and-offwall.spec.js`, `walls-image-picker.spec.js`,
  `walls-addon-album-lock.spec.js`) — but these exercise the frontend
  canvas/DOM logic against a mock server, not `WallManager` itself.
  **Backend-tested** — `tests/python/managers/test_walls.py` (custom wall
  CRUD, default-wall auto-sync, clearing/ignoring exclusions, default-wall save
  preserving omitted placements, entry removal pruning, auto-layout collision math,
  no placement overlap after removing and re-adding a frame around a full row boundary).

## 20. Schedules: send a scene or image at a future/recurring time
User schedules a one-shot or daily/weekly/monthly recurring send; missed
one-shots fire late on restart; a deleted scene/image target degrades a
schedule to "broken" instead of erroring at fire time.
- **Entry points**: `schedules.py` (`ScheduleManager.async_create_schedule`,
  `_arm`, `_async_fire`, `_async_fire_missed`,
  `async_handle_scene_deleted`, `next_fire_at`), `schedules_http.py`.
- **If it silently breaks**: missed schedules never fire after an outage,
  or a schedule keeps trying to fire against a deleted target forever.
- **Test status**: Panel-tested (`schedules.spec.js` — create/edit/toggle/
  delete, weekly validation). **Backend-tested** —
  `tests/python/managers/test_schedules.py` (trigger/action validation,
  missed-once fires late, recurring fire re-resolves the scene at fire
  time, target-deleted → target_missing + disabled, edit repairs a broken
  schedule, `next_fire_at` math including monthly day-of-month clamping).

## 21. HA entities: sensors + Orientation select + Camera display
Read-only device telemetry (battery/wifi/charging/firmware/IP/queued-on-deck), a per-frame Orientation control that persists into config entry options (supporting lock/unlock and follow-device settings), and a Camera entity representing the frame's dynamic canvas (active photo display).

`sensor.*_queued_image` is `idle` or `queued`; when queued, attributes
include `image_id` (library id when known) and `queued_at` (unix time) so
dashboards and automations can see **what** is on deck.

The panel's Frame Information modal (per-frame gear/info popup) surfaces the
Orientation control as Portrait/Landscape lock icons plus the live
"Discovered" (gsensor/accelerometer) reading. Icon position is fixed
(anchored to the row's right edge) regardless of label text length, so the
icons don't visibly shift as the label changes between "Auto",
"Portrait/Landscape (Locked)", and "Portrait/Landscape (Discovered)".
Clicking a lock icon only stages the change locally (icon highlight +
preview text); nothing is written until "Save Changes" is clicked, matching
the Name field's existing save-on-click behavior. A "Rediscover" button
(disabled for Samsung frames, which have no accelerometer) forces an
immediate coordinator poll via `POST /api/digital_frames/frame/poll_orientation`
instead of waiting for the next scheduled poll (up to `scan_interval`) --
since it's a device read rather than a user edit, that one action always
takes effect immediately, never staged.
The IP address display includes an external link icon opening the frame's UI
(`http://[ip]/portal` for Fraimics/clones, `http://[ip]/remote` for Meurals).
The actual keep-awake status parsed from the frame's HTML `/info` page is
displayed if available.
- **Entry points**: `sensor.py` (all `Fraimic*Sensor` classes), `select.py`
  (`DigitalFramesOrientationSelect`, `MeuralOrientationSelect`), `camera.py` (`DigitalFramesCamera`);
  `digital-frames-panel.js` (`_openFrameSettingsMenu`, `_renderFrameOrientationDisplay`,
  `_stageFrameOrientation`, `_pollFrameOrientation`, the `frame-settings-save` click handler);
  `library_http.py` (`DigitalFramesFramePollOrientationView`).
- **If it silently breaks**: wrong/missing sensor values, selecting an orientation doesn't change rendering, locking/unlocking fails, the camera entity fails to load or serve the active frame image, orientation icons jump around as the label text changes length, an orientation click auto-applies without a Save Changes step (or Save Changes silently drops a staged orientation change), Rediscover does nothing / leaves the frame's displayed orientation stale, or the external link icon or actual keep-awake status is missing or incorrect.
- **Test status**: **Backend-tested** — `tests/python/setup/test_entities.py`, `tests/python/library/test_library_http_frame_poll_orientation.py` (poll_orientation endpoint forces a refresh, 404s on unknown entry, 400s on missing entry_id). **Panel-tested** — `tests/panel/frame-manage.spec.js` (orientation lock staged locally and only applied on Save Changes; icons stay in a fixed position regardless of label length; Rediscover polls immediately without staging/saving; UI link icon matches the frame's type and IP; Keep Awake actual status displayed).

## 22. Render spec resolution (orientation lock + rotation + hanging edge)
Central "how should this image be composed for this frame" resolution —
combines native dimensions, orientation lock, 180° flips, hang-edge, live gsensor/accelerometer reporting, and image natural orientation (surface area crop comparison or aspect ratio fallback) into one `RenderSpec` every send path consults.

`coordinator._async_poll_accelerometer` reads the frame's gravity axes
(`x`, `y`) and picks whichever axis is dominant to decide native-vs-rotated.
Per the real hardware reading in `ACCELEROMETER_FINDINGS.md` (frame sitting
in its normal/native position, `x ≈ -0.99, y ≈ 0.00`), X -- not Y -- is the
dominant axis in the frame's native orientation; a previous version of this
check had that backwards, which made the panel's "Discovered" orientation
report the *opposite* of every native-orientation frame's true physical
orientation (e.g. a portrait-mounted frame always showing "Landscape
(Discovered)").
- **Entry points**: `helpers.py` (`render_spec_for_entry`, `orientation_for_entry`, `RenderSpec.variant`), `library.py` (`_determine_natural_orientation`), `coordinator.py` (`_async_poll_accelerometer`).
- **If it silently breaks**: this is the single riskiest piece of logic in
  the whole integration — a wrong rotation means every image sent from
  every path lands sideways or upside-down on the physical frame, and it's
  invisible until someone looks at hardware. A wrong accelerometer axis
  mapping specifically means the "Discovered" orientation shown in the panel
  (and anything following it in Auto mode) is backwards for every
  native-orientation frame.
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_helpers_render_spec.py`, `tests/python/library/test_crop_aspect_ratio_and_lock.py` (`test_unlocked_frame_natural_orientation_selection`), and `tests/python/coordinator/test_coordinator_polling.py` (`test_accelerometer_polling_success` -- native/portrait reading; `test_accelerometer_polling_rotated_90_degrees` -- rotated reading).

## 23. Frame-type registry, PanelCodec ids & byte-layout dispatch
Declares every supported physical panel (resolution, **codec_id** /
byte layout, send timeout, official/community origin) and validates no
two types sharing a resolution disagree on codec. The 7.3" panel is a
second **PanelCodec** (`spectra6_sequential`) under the local Spectra
HTTP driver, not identical wire bytes to official split-half panels.
Library send/backfill and raw-upload encode go through
`panel_codec.encode_for_panel*` so codec selection is one seam.
- **Entry points**: `frame_types.py` (`FRAME_TYPES`, `codec_id`,
  `frame_type_for_resolution`, `codec_id_for_resolution`,
  `byte_layout_for_resolution`, `send_timeout_for_entry`,
  `_validate_registry`), `panel_codec.py` (`PanelCodec`, `CODECS`,
  `encode_for_panel`, `encode_for_panel_with_preview`,
  `panel_codec_for_resolution` / `_entry`).
- **If it silently breaks**: garbled image on an unregistered/misregistered
  panel size (same failure mode as image conversion, one layer up), or
  7.3" vs 13.3" packing cross-wired.
- **Test status**: **Backend-tested** — `tests/python/unit/test_frame_types.py`,
  `tests/python/unit/test_panel_codec.py`.

## 24. First-run onboarding wizard + server-side completion flag
Six-step first-run tour; "skip"/"complete" retires the wizard for every
admin, forever, via a server-side flag (not localStorage).
- **Entry points**: `http_api.py` (`DigitalFramesOnboardingView`).
- **If it silently breaks**: the wizard reappears every session for every
  admin, or one admin's skip doesn't stick for others.
- **Test status**: Panel-tested (`onboarding.spec.js`, full six-step tour
  and skip variants). **Backend-tested** — `tests/python/setup/test_onboarding.py`
  (admin-gating + Store persistence).

## 25. Domain-level setup wiring
`async_setup` / `async_setup_entry` / `async_unload_entry` /
`async_remove_entry` — bootstraps everything above: registers HTTP views,
the sidebar panel, the Lovelace card, auto-creates the device-less
scenes-hub entry, and tears down cleanly when the last frame is removed.
- **Entry points**: `__init__.py`.
- **If it silently breaks**: this is glue — a failure here means the whole
  integration fails to load, or (subtler) removing the last frame leaves
  scene-pack/schedule timers running forever, or doesn't prune wall
  layouts.
- **Test status**: **Backend-tested** — `tests/python/setup/test_init_setup_entry.py`
  (scenes-hub auto-creation, service lifecycle, wall-placement pruning on
  removal, reload on option change).

## 26. Panel init-load resilience
On open (or after an HA restart/reconnect window), the panel retries each
of its initial data loads (frames, scenes, walls, etc.) with backoff
instead of taking a single failed fetch at face value, and never infers
"nothing configured yet" from a load that errored.
- **Entry points**: `digital-frames-panel.js` (`_withInitRetry`, `_initLoadErrors`,
  `_initRetryDelays`/`_initRetriesActive`).
- **If it silently breaks**: a transient outage (HA restarting, a
  reconnect window) paints a believably-empty dashboard or wrongly opens
  the onboarding tour — Dale hit this in production before the fix (commit
  `a5b1a1b`) landed. The invariant: never make a zero-state claim from a
  load that errored; always distinguish ABSENT from UNKNOWN.
- **Test status**: Panel-tested (`tests/panel/init-retry.spec.js` — a
  transient outage recovers with no refresh needed, a persistent outage
  shows an "incomplete" note and never opens the tour, a broken
  onboarding-flag endpoint fails closed, a not-yet-ready websocket retries
  frame discovery, non-admins never see an admin-only error from an
  errored load). Backend: not applicable — this is frontend-only
  resilience against transient fetch failures.

## 27. Panel element lifecycle (listener/blob cleanup on disconnect)
The panel is a custom element HA recreates per navigation, not reused —
every `window`/`document` listener and every blob URL it creates (crop
editor previews, thumbnails) must be torn down on disconnect, or they leak
across every visit to the Frames panel for the life of the browser tab.
- **Entry points**: `digital-frames-panel.js` (`disconnectedCallback`, the
  `this._abort` AbortController every listener registration is tied to,
  blob URL tracking in `this._thumbUrls`).
- **If it silently breaks**: a slow memory/listener leak that only shows
  up after navigating to the panel repeatedly in one browser session —
  invisible in a quick manual check, which is exactly how it shipped once
  already (commit `71c1b17`, "Sever the panel's global listeners and blob
  URLs on disconnect"), and shipped again the same way in the async-fetch
  gap fixed in the July 2026 code review: `_fetchThumb`'s and
  `_openEditor`'s full-size fetches weren't tied to `this._abort.signal`
  and didn't check a disposed flag before `URL.createObjectURL`, so a
  thumbnail or crop-editor image still loading when the panel disposed
  still created a blob URL afterward — never revocable, since `_dispose()`
  had already reset the tracking dict it would have been recorded in.
  Both fetches now pass the abort signal and check `this._disposed` before
  creating or committing the blob URL.
- **Test status**: Panel-tested (`tests/panel/lifecycle.spec.js` — detach
  severs listeners and revokes blob URLs; reattach after detach revives
  correctly; a same-tick DOM move, as HA sometimes does internally, must
  NOT tear anything down; a thumbnail fetch still in flight at dispose time
  never calls `URL.createObjectURL` at all). Backend: not applicable.

## 28. Live content (skills / xOTD renderer): reusable content generators
**(Content platform: Live tab — was "Daily Content / skills".)** User creates
named presets (word/quote/joke/scripture of the day, image feeds like NASA
APOD / Wikimedia POTD / Bing wallpaper, or random-from-album) and sends one
to any frame — ad hoc ("Send Now" on the Live tab, the Lovelace card's Daily
picker), staged into a scene via the wall picker, or on a schedule.
**Quick setup (Phase 3):** each Live card has frame + time + "Schedule daily"
which calls `POST /api/digital_frames/live/quick_setup` to create one daily
recurring schedule per selected frame (does not clone the skill).
Text modes render through the pinned remote `xotd_renderer.py` subprocess
at the target frame's composition size. The script writes Spectra
`xotd.bin` **and** full RGB `xotd_preview.png` (before pack).
**Agenda mode (Phase 4):** pinned `agenda_renderer.py --render-only` writes
`agenda.bin` + `agenda_preview.png`; HA calendar events are prefetched
into `ha_events.json` before the subprocess. Both prefetching and parsing
handle both dictionary-style and string-style calendar event start/end times
to support different HA versions. Both paths use
`text_skill_payload_for_codec` for Spectra vs Meural JPEG.
Image modes resolve to a library image_id (feeds upload the fetched photo
into the library first) and use the normal library codec path.
- **Entry points**: `skills.py` (`SkillManager.async_save_skill` /
  `async_render_for_entry` / `_async_render_text` / `_async_render_agenda` /
  `_async_fetch_image_feed` / `_async_pick_image_album`),
  `const.py` (`AGENDA_RENDERER_PINNED_BASE`),
  `panel_codec.py` (`text_skill_payload_for_codec`),
  `skills_http.py` (CRUD + `DigitalFramesSkillSendView` +
  `DigitalFramesLiveQuickSetupView`), fan-out via
  `scenes.py` (`async_send_mappings`), panel Live tab
  (`_quickScheduleLive`, agenda mode tile + fields),
  `__init__.py` (`_async_migrate_agenda_widget`).
- **If it silently breaks**: daily content stops arriving (schedules
  no-op), a skill renders blank/stale content, fan-out to several frames
  shows different content per frame, an orientation-locked Spectra frame
  (composition canvas orientation-swapped relative to its native buffer)
  gets a sideways/garbled render because the wire bytes were packed at the
  composition size instead of rotated to the native buffer first (a real
  bug fixed in the July 2026 code review — `text_skill_payload_for_codec`'s
  Spectra branch now rotates + repacks when `rotation != 0`, mirroring
  `image_converter._process`'s canvas-rotation step for ordinary photo
  sends), a Samsung (PNG) frame gets raw Spectra6 bytes mislabeled as valid
  PNG payload (same root cause — only `CODEC_JPEG_Q90` was special-cased
  before the fix; `CODEC_PNG` now gets its own compose/rotate/encode branch
  and a PNG/JPEG encode failure now raises `SkillError` instead of
  silently sending the wrong format), or Meural receives Spectra `.bin` on
  postcard (garbled/fail) instead of JPEG, quick-setup creates no/wrong
  schedules, or — the regression fixed in July 2026 — a text-skill send
  wipes the frame's last-image state so the card/panel thumbnail goes blank
  while the frame shows content. The rotate+repack step itself had a
  follow-on gap (found by the July 2026 max-effort review, issue #6): it
  had no exception handling, unlike the preview generation right below it,
  so a decode/rotate failure (malformed renderer output) propagated to
  `skills.py`'s generic handler, which treated *any* failure on a Spectra
  codec as soft and silently sent the un-rotated raw bin — reintroducing
  the exact garbled render this whole fix exists to prevent, just via a
  different trigger. Both `async_render_for_entry` and
  `async_render_message_for_entry` now treat a failure as hard (raise
  `SkillError`) whenever the frame's `RenderSpec.rotation` is nonzero, not
  only for JPEG/PNG codecs; the soft raw-bin fallback only applies when no
  rotation is needed, where the raw bin genuinely is still valid wire
  bytes. The decode+rotate step itself was also factored into one shared
  helper (`_decode_and_rotate`) reused by both the JPEG/PNG branch and the
  Spectra rotate branch, replacing two separately-written copies of the
  same "unpack bin, then conditionally rotate" sequence.
- **Test status**: **Backend-tested** —
  `tests/python/managers/test_skills.py` (CRUD, per-mode render dispatch,
  feed fetch/upload, subprocess lifecycle + cleanup, preview-PNG
  generation with graceful degradation, Meural JPEG re-encode from
  text-skill bin, Samsung PNG re-encode from text-skill bin never falls
  through to raw Spectra bytes, a rotation-locked Spectra frame with a
  malformed renderer bin raises `SkillError` instead of silently sending
  the un-rotated bin),
  `tests/python/managers/test_live_quick_setup.py` (daily schedule create,
  on_demand_only, missing skill),
  `tests/python/managers/test_scenes.py` (bin renders thread their
  preview through to the coordinator as the send thumbnail);
  `tests/python/unit/test_panel_codec.py` (`text_skill_payload_for_codec`
  rotates + repacks to the native buffer for both the rgb_png and
  bin-fallback paths, byte-exact against a reference rotate-then-pack;
  CODEC_PNG gets its own compose/rotate/encode branch and is exercised the
  same way CODEC_JPEG_Q90 already was; a malformed bin with a nonzero
  rotation raises rather than silently returning un-rotated bytes).
  Panel-tested — `skills.spec.js` (Live tab; internal id still `xotd`),
  `walls-skill-picker.spec.js` (staging into scenes),
  `fraimic-card.spec.js` (card Daily picker send).

## 29. Lovelace card: per-frame dashboard management + last-image preview
The `fraimic-card` custom card: configured by picking a frame from a list
(entry_id; legacy battery-entity configs auto-resolve), it shows the
frame's latest displayed image — library sends via `last_image_id`,
upload/xOTD renders via the coordinator's persisted `last_thumbnail` —
and manages the frame from the dashboard: upload, library picker with
album filter, daily-skill send, orientation toggle, and crop adjustment
(KPF 12). The last-image preview state itself (mutually-exclusive
`last_image_id`/`last_thumbnail`, persisted per frame, exposed through
`/api/digital_frames/frames` and `/api/digital_frames/frame/{entry_id}/thumbnail`) is
part of this flow: every send path must leave it describing what the
frame actually shows.
- **Entry points**: `digital-frames-card.js` (card + `fraimic-card-editor`),
  `coordinator.py` (`async_set_last_image`, `last_image_id` /
  `last_thumbnail` persistence), `library_http.py` (`DigitalFramesFramesView`
  incl. `battery_entity_id`/`orientation_entity_id`/`online`,
  `DigitalFramesFrameThumbnailView`), `http_api.py` (`DigitalFramesFrameStatusView`).
- **If it silently breaks**: the card shows a stale or blank image while
  the frame shows something else (exactly what text-skill sends did
  before July 2026 — see KPF 28), the card picker falls back to raw YAML,
  or sends/orientation changes target the wrong frame. Three real bugs
  fixed in the July 2026 code review: (1) `_cropSaveSend()` never called
  `_unstage()` on success (unlike `_send()`), so cropping a staged-but-
  unsent pick sent it immediately but left the Send/Cancel bar and PREVIEW
  badge stuck showing stale state indefinitely; (2) `setConfig()`/`_build()`
  unconditionally rebuild the whole shadow DOM but never reset `_staged`/
  `_crop` — HA's card-editor live preview calls `setConfig()` on every
  config change (e.g. every keystroke in the Name field, not just
  `entry_id`), so staging a photo then editing the config elsewhere left
  the freshly rebuilt DOM's default-hidden actions bar out of sync with
  `_staged` staying truthy, with nothing left to reach `_unstage()` from;
  (3) the card had no `disconnectedCallback` at all, so a staged preview's
  blob URL (or an open crop session's, or its window listeners) leaked
  until page reload — HA recreates Lovelace cards on dashboard/view
  changes, never reuses one. Fix (1) above introduced a follow-on race
  (found by the July 2026 max-effort review, issue #7): its delayed
  `_unstage()` had no staleness guard, unlike `_stageImage()`'s identity
  check. `cropClose` isn't disabled while a crop save+send is in flight
  (a slow e-ink panel send can take up to 240s), so a user could close the
  overlay, stage an unrelated new photo, and have the original crop-send's
  delayed callback silently wipe out that newer pick when it finally
  resolved. `_send()`'s identical delayed-unstage shape had the same
  latent hazard. Both now capture `_staged` before the async work starts
  and only unstage/refresh if it's still the same reference by the time
  the delayed callback runs.
- **Test status**: Panel-tested — `fraimic-card.spec.js` against the mock
  server + `card-harness.html` (editor frame list and entry_id config
  write, legacy entity resolution, both thumbnail sources incl. ETag'd
  render previews, upload/library/skill send round trips, orientation
  service call, crop flow including Save & Send on a staged pick correctly
  unstaging afterward, a pick staged after the crop overlay is closed
  mid-send surviving rather than being clobbered by the stale crop-send,
  `setConfig` clearing a staged pick instead of
  leaving stale state after rebuild, removing the card revoking a staged
  pick's blob URL). Coordinator preview persistence is
  backend-tested via `test_scenes.py`/`test_skills.py` (KPF 28); the
  frames/thumbnail HTTP views' own marshaling is still a **Gap** with the
  rest of the `*_http.py` layer.

## 30. Media Source integration
Exposes the Fraimic photo library to Home Assistant's native media source system (browsable under the Media browser and playable/resolvable via `media-source://digital_frames/...` URIs) without copying files.
- **Entry points**: `media_source.py` (`async_get_media_source`, `DigitalFramesMediaSource`).
- **If it silently breaks**: Fraimic albums and photos do not appear in the Home Assistant Media tab, or resolving a `media-source://` URI fails.
- **Test status**: **Backend-tested** — `tests/python/library/test_media_source_and_tagging.py`.

## 31. AI Auto-tagging on upload & discovery
Automatically analyzes uploaded or discovered images using Home Assistant's configured multi-modal `ai_task` entity and updates image tags in `manifest.json`.
- **Entry points**: `library.py` (`LibraryManager.async_upload`, `async_discover`, `async_auto_tag_image`).
- **If it silently breaks**: Photos are uploaded or discovered but no tags are generated even when an AI Task entity is active and the option is enabled.
- **Test status**: **Backend-tested** — `tests/python/library/test_media_source_and_tagging.py`.

## 32. Meural Canvas (local + optional cloud pin) as a second FramePort driver
User adds a NETGEAR Meural by LAN IP. The frame gets a `driver=meural`
config entry, JPEG codec (`jpeg_q90`), and participates in walls, scenes,
library send, raw upload, and Live skills like Fraimic frames.

**Send path (two layers):**

1. **Postcard (always):** local `POST /remote/postcard` multipart JPEG/PNG
   for immediate pixels (EXIF Artist/Title preserved; Orientation reset to 1).
2. **Cloud pin (when Netgear account linked):** upload to
   `api.meural.com/v0/items`, place alone in a stable per-frame pin gallery
   (`Digital Frames · {title} · Pin · {landscape|portrait}`), remove/delete
   the previous pin item, load that gallery on the device, set
   `imageDuration=0` / `galleryRotation=false` so the Canvas does not
   rotate. Daily skills (agenda, xOTD) reuse the same pin gallery — each
   render **replaces** the prior cloud item (no stack of stale agendas).

**Gallery reuse (`ensure_named_gallery`):** the Netgear cloud API's
orientation vocabulary on `GET user/galleries` is not guaranteed to match
what we send on create, so name+orientation matching alone was found to
under-match and spawn duplicate galleries with the same name on every push.
`ensure_named_gallery` now checks the stored `gallery_id` from the previous
push first (authoritative reuse, immune to name/orientation drift) before
falling back to a name+orientation scan. A per-gallery-name `asyncio.Lock`
serializes creation so two overlapping sends can't race into duplicate
galleries. If a name+orientation scan still turns up more than one gallery
with the same name (pre-existing duplicates from the old bug), the oldest
(lowest id) is kept and the rest are deleted (items + gallery) so affected
installs self-heal over subsequent pushes.

**Fail-closed when cloud is linked:** postcard alone is not success. If
cloud pin fails after a good postcard, `async_send_image_or_queue` returns
`success: false` (`postcard_ok: true`, `cloud_ok: false`). Unlinked frames
remain postcard-only (local-only).

**Link account:** Meural frame **Configure** options — Netgear email +
password (Cognito, with legacy `/authenticate` fallback). One shared
account for all Meural frames (`meural_cloud_store` + HA Store). Unlink
returns to postcard-only.

**HA album → Meural (rotation on):** panel album tile **Meural** button or
`POST /api/digital_frames/meural/push_album` full-mirrors an HA library
album into a multi-image cloud gallery and loads it live with a non-zero
`imageDuration`.

Sleep-queue does not apply (send resumes if suspended). Meural has no
battery sensor — dashboard/send use `_ip` as the send entity fallback
(UI shows N/A for battery).

**Local device features:**

- **Orientation (gsensor):** Device orientation sensor; follow-device default;
  Orientation select Follow / Portrait / Landscape. Hang change re-sends
  last content via `async_redisplay_last` (postcard + cloud pin when linked).
- **Backlight light entity;** lux; free space; WiFi RSSI.
- **Services:** sleep/wake mapped to suspend/resume. Restart unsupported.

Text skills re-encode to JPEG via `text_skill_payload_for_codec` (KPF 28).

**Not implemented:** next/prev media player chrome, membership gallery
browse, 2FA Netgear login.
- **Entry points**: `config_flow.py` (`async_step_add_meural`, options
  Meural cloud fields),
  `meural.py` (local probe/postcard/control),
  `meural_cloud.py` (Cognito/legacy auth, upload, galleries, device load),
  `meural_cloud_store.py` (shared credentials + pin/album ids),
  `meural_coordinator.py` (`async_send_image` pin pipeline,
  `async_push_ha_album`),
  `library_http.py` (`DigitalFramesMeuralPushAlbumView`, frames
  `meural_cloud` status),
  `light.py` / `sensor.py` / `select.py`,
  `panel_codec.py` (`CODEC_JPEG_Q90`),
  `digital-frames-panel.js` (`_pushAlbumToMeural`, album Meural button).
- **If it silently breaks**: Meural cannot be added; sends fail or send
  Spectra `.bin`; empty-album banner returns because cloud pin never ran
  (unlinked or fail not surfaced); cloud link accepted but device not
  matched to LAN host; pin galleries accumulate items because replace/
  delete failed; duplicate cloud galleries with the same name pile up
  because id-based reuse/dedup in `ensure_named_gallery` regresses; album
  push encodes wrong codec; orientation redisplay double-sends (listener vs
  select — historical fix: listener is sole trigger on real option change;
  select redisplays only when re-selecting the already-active option); or
  options form drops orientation lock when saving cloud fields.
- **Test status**: **Backend-tested** —
  `tests/python/unit/test_meural.py` (JPEG codec/EXIF, orientation,
  follow-device, system stats, command map, redisplay listener once),
  `tests/python/unit/test_meural_cloud.py` (gallery naming, legacy auth
  mock, pin replace + imageDuration 0, empty album reject, fail-closed
  cloud error, postcard-only when unlinked, gallery reuse by id despite
  orientation drift, duplicate-gallery dedup/cleanup, concurrent-create
  lock),
  `tests/python/unit/test_select_meural_orientation.py`,
  `tests/python/config_flow/test_config_flow_user_scan.py` (Meural add).
  **Frontend-tested** — `tests/panel/meural-dashboard.spec.js` (dashboard;
  album Meural button / push flow not Playwright-covered yet — **Gap**).
  Live Canvas + real Netgear cloud is manual (**Gap** for CI).

## 34. Samsung EM32DX local MDC driver (experimental)
User adds a Samsung E-Paper (EM32DX-class) panel by LAN IP, MDC PIN, and
optional Wi‑Fi MAC. Images are composed as PNG and delivered by staging a
short-lived token URL under HA’s HTTP, then sending MDC content-download
(0xC7) over TLS :1515 so the panel pulls the PNG — protocol from
[fayep/Joyous](https://github.com/fayep/Joyous). No Samsung cloud. **Not
validated on real hardware in this repo** (Gap: live panel).
- **Entry points**: `config_flow.py` (`async_step_add_samsung`),
  `samsung.py` (`mdc_content_download_packet`, `send_mdc_content_download`,
  `send_wol`), `samsung_coordinator.py` (`SamsungCoordinator`),
  `panel_codec.py` (`CODEC_PNG`), `http_api.py`
  (`DigitalFramesSamsungContentView`), `sensor.py` (IP + MDC reachable).
- **If it silently breaks**: send fails (auth/PIN, URL >255 bytes, panel
  asleep without Network Standby/WoL), or panel never fetches the token
  URL (HA not reachable from the panel LAN).
- **Test status**: **Backend-tested** — `tests/python/unit/test_samsung.py`
  (packet build, WoL, mock MDC). Live hardware is manual (**Gap**).

## 33. Check for updates from the dashboard Settings modal
Admin opens ⚙ Settings on the Fraimic panel and sees **on-disk** package
version vs latest GitHub release (and, when different, the version HA is
still **running** in memory). Can **Check for updates**, **Install**
(HACS `async_download_repository` when the repo is already installed via
HACS; else GitHub zipball into `custom_components/digital_frames` **plus** a
HACS bookkeeping sync so `installed_version` / the HA update entity match
disk), then **Restart Home Assistant**. After install, status shows disk
vs running and forces the Restart control until they match — HA's loader
cache is not the install source of truth. Opening Settings / checking for
updates also **auto-heals** a HACS `installed_version` that still lags
disk (legacy zipball-only installs) — no user re-sync step.

When a newer release is available and not dismissed for that version,
admins also see a **dashboard banner** (Install + Dismiss). Dismiss is
server-side and per-version (`POST /api/digital_frames/update/dismiss`) so a
later release re-shows the banner; GitHub checks are TTL-cached so the
banner does not hammer the API on every panel open.
- **Entry points**: `update.py` (`get_disk_version`, `get_running_version`,
  `check_for_update`, `install_update`, `dismiss_update_banner`,
  `banner_visible`, `_try_hacs_install`, `_sync_hacs_after_install`,
  `restart_home_assistant`),
  `update_http.py` (`/api/digital_frames/update*`),
  `digital-frames-panel.js` (`_refreshUpdateBanner`, `_renderUpdateBanner`,
  `_dismissUpdateBanner`, `_refreshUpdateStatus`,
  `_installIntegrationUpdate`, `_restartHomeAssistant`).
- **If it silently breaks**: settings claim "up to date" while disk is
  newer than HA's loaded module (or the reverse), install succeeds but UI
  never prompts restart, install updates files but HACS/HA still show the
  old version after restart, the banner never appears (or won't dismiss /
  reappears for the same version after dismiss), users still need HACS +
  System restart, or a botched install leaves a half-written
  `custom_components/digital_frames`. Two real bugs here, fixed in the
  July 2026 code review: (1) `_install_from_zipball`'s write loop had no
  rollback — a failure partway through (disk full, a corrupt/interrupted
  download) left the half-written directory in place with the prior good
  install already moved aside, bricking the integration until a manual
  restore from `.storage/fraimic_update_backup/`; it now restores that
  backup on any extraction failure before re-raising. That fix only
  covered the case where a prior install existed to restore — the July
  2026 max-effort review (issue #5) found a first-time install (or a retry
  after an earlier attempt that never got as far as creating the
  directory) had no backup to restore, so a partial-write failure there
  still left a half-extracted directory with no cleanup at all; the
  extraction failure handler now also removes that half-written directory
  when there was no backup to restore. (2) both
  `install_update` and `_try_hacs_install` substituted `target` for a
  falsy `get_disk_version()` result *before* checking whether disk matches
  target — masking the exact "extraction reported success but
  manifest.json is now missing/unreadable" case the mismatch check exists
  to catch; both now raise instead of reporting success in that case. That
  `_try_hacs_install` raise shipped with its own bug (issue #10, July 2026
  code review): the `raise UpdateError(...)` sat inside that same
  function's pre-existing `except Exception` fallback handler, so it was
  immediately caught, demoted to a "falling back to GitHub" warning, and
  `_try_hacs_install` returned `None` — `install_update` then silently
  proceeded to a from-scratch GitHub zipball install instead of ever
  surfacing the diagnostic, contradicting this very doc entry. Fixed with
  an `except UpdateError: raise` guard ahead of the generic
  `except Exception` handler, so this specific, already-diagnosed failure
  propagates instead of being masked as a generic HACS-API error.
- **Test status**: **Backend-tested** — `tests/python/unit/test_update.py`
  (version compare, disk vs running / needs_restart, HACS sync after
  zipball, auto-heal on check, modern HACS download path, banner_visible
  dismiss rules, zipball extraction restores the prior install on a
  partial-write failure, zipball extraction cleans up a half-written
  directory when there was no prior install to restore, `install_update`
  raises rather than masking a broken post-extract disk version, and now
  `_try_hacs_install` itself — not a stub — raises `UpdateError` rather
  than swallowing it when the on-disk manifest is unreadable after a
  reported-success HACS download).
  **Panel-tested** —
  `tests/panel/update-banner.spec.js` (show / hide / dismiss / non-admin).
  Live GitHub check/install is admin-manual (**Gap** for CI; network +
  filesystem).

## 34. Product branding + domain as Digital Frames
Product and technical identity are **Digital Frames** /
`digital_frames`: HACS name, manifest domain, package
`custom_components/digital_frames/`, sidebar panel URL `/digital_frames`,
services `digital_frames.*`, HTTP `/api/digital_frames/*`, media source
`media-source://digital_frames/…`. Official Spectra hardware still uses
manufacturer **Fraimic** and driver id `fraimic`.

**Albums / library survive the domain rename:** on first load the local
library is renamed `config/fraimic_library/` →
`config/digital_frames_library/` (manifest + originals + album tags).
Dropbox does the same for `/fraimic_library` → `/digital_frames_library`
when possible; Google Drive reuses an existing "Fraimic Library" folder
if present. Library settings migrate
`.storage/fraimic_library_settings` → `digital_frames_library_settings`.
Config entries, walls, scenes, and schedules under the old domain are
**not** migrated — re-add frames after upgrade.

**Panel URL:** primary sidebar path is `/digital_frames`. Setup also
registers a **legacy alias** at `/fraimic` (no second sidebar entry) so
old bookmarks keep working, and logs a warning if leftover
`custom_components/fraimic/` is still present (must be removed).
- **Entry points**: `const.py` (`DOMAIN`, `PRODUCT_NAME`, `LIBRARY_DIRNAME`,
  `LEGACY_DOMAIN`), `manifest.json` / `hacs.json`, `__init__.py` (panel
  path + legacy `/fraimic` alias + leftover-folder warning),
  `library.py` (`async_load` settings migrate), all `*_http.py` view URLs,
  `digital-frames-panel.js` / `digital-frames-card.js`.
- **If it silently breaks**: leftover `custom_components/fraimic/` still
  owns `/fraimic` with old code; users only installed the package under
  the old path; library path renames orphan albums.
- **Test status**: **Backend-tested** — `tests/python/unit/test_branding.py`
  (domain, product name, stable `LIBRARY_DIRNAME`). Full entry migration
  is intentionally out of scope.

## 35. Compose & send a styled text message (frame / scene / wall banner)
User types a message, picks a visual style (plain / 1950s diner ad / movie
poster), and sends it to a single frame, an existing scene, or a wall —
composed from the Live tab's "Compose Message" button, not a persisted
Skill: unlike Word/Joke/Quote/Scripture of the Day, a message never
appears in the Live tab's own card grid, has no name, and can't be
scheduled — it's an ephemeral, inline-config send, exactly like a
`fraimic.send_skill` one-off mapping. Rendering reuses the pinned
`xotd_renderer.py` subprocess (see KPF 28) with a new `"message"`
content_mode and three hardcoded layout functions, one per style.

**Wall target — one banner, cropped per frame:** v1 is scoped to a single
row or column of frames that share the exact same effective resolution
(`wall_geometry.compute_wall_canvas_geometry`) — text is seam-sensitive in
a way photos aren't, so an uneven/2D wall layout is rejected outright
rather than risking a headline silently bisecting a bezel gap. The shared
canvas renders **once**, de-duplicated across every frame's concurrent
`asyncio.gather` resolution via an in-flight `asyncio.Task` map (a plain
check-then-set cache dict would race and re-render once per frame — see
`SkillManager._wall_canvas_renders`), then each frame gets an exact `i/N`
fractional crop of it via `panel_codec.encode_for_panel`'s existing
`crop_box` param — no new compose/crop logic needed there.

**Save to library** (frame/wall targets only — a scene target has no
single canonical image, since each member frame independently re-renders
the text at its own aspect ratio) persists the composed image as a normal
library photo, tagged into a "Messages" album. Re-sending a saved wall
banner from a persisted scene uses a new `{"type": "image_crop", "image_id",
"crop_box"}` mapping rather than the library's per-resolution manual-crop
mechanism (`record.crops["WxH"]`) — that mechanism can only hold one crop
per resolution, which would silently collide when two frames of the
*same* resolution share one saved banner but need different slices of it.
`library.async_get_bin_for_send`'s new `crop_box_override` param bypasses
both the manual-crop lookup and the `.bin` cache (read and write) so this
never happens.
- **Entry points**: `frame-addons/addons/xotd/xotd_renderer.py`
  (`render_message_image`, `_layout_plain` / `_layout_ad_50s` /
  `_layout_movie_poster`), `wall_geometry.py`
  (`compute_wall_canvas_geometry`), `skills.py`
  (`_async_run_renderer_script`, `_async_render_message`,
  `async_render_message_for_entry`, `async_render_message_wall_crop_for_entry`,
  `async_render_message_canvas`, `_wall_canvas_renders`), `scenes.py`
  (`_prepare_one`'s `message` / `message_wall_crop` / `image_crop`
  branches, `_validate_mapping_value`'s `image_crop` acceptance),
  `panel_codec.py` (`encode_for_panel_with_preview`'s `crop_box` param),
  `image_converter.py` (`convert_image_bytes_cropped_with_preview`),
  `library.py` (`async_get_bin_for_send`'s `crop_box_override`),
  `messages_http.py` (`DigitalFramesMessageSendView`), `__init__.py`
  (view registration), panel `_openMessageComposeModal`.
- **If it silently breaks**: a wall banner's frames show non-adjacent or
  misaligned slices; a follow-device frame's crop drifts after it
  physically flips orientation since the wall was last laid out (guarded
  by resolving each member frame's size from the live
  `render_spec_for_hass_entry`, never the wall canvas's static preview-scale
  `tile_dims`); two frames sharing one saved banner image at the same
  resolution collide and one silently shows the other's crop (the exact
  cache-key collision `crop_box_override` exists to prevent); a wall send
  with N frames re-renders the shared canvas N times instead of once,
  defeating the entire "render once, crop many" premise (the in-flight
  `asyncio.Task` de-dup exists to prevent this under `asyncio.gather`
  concurrency); or "save to library" silently picks an arbitrary
  resolution for a scene target instead of being rejected outright.
- **Test status**: **Backend-tested** —
  `tests/python/managers/test_wall_geometry.py` (single-frame degenerate
  crop, row/column detection + sort, mismatched-resolution rejection,
  non-colinear rejection, missing placement/entry rejection, live
  follow-device orientation wins over a stale stored option),
  `tests/python/managers/test_messages.py` (message render returns bin +
  preview, script config carries text/style, nonzero-exit raises,
  canvas-only render for save-to-library, wall-crop concurrent calls
  collapse into exactly one subprocess invocation, distinct crop per
  frame, unknown wall / invalid geometry raise),
  `tests/python/managers/test_scenes.py` (`message` /
  `message_wall_crop` / `image_crop` mapping dispatch and partial-failure
  isolation, `image_crop` scene-save validation, two frames sharing one
  image with different `crop_box_override`s never read back each other's
  cached bytes),
  `tests/python/unit/test_panel_codec.py`
  (`encode_for_panel_with_preview`'s `crop_box` byte-exact against
  `encode_for_panel` for both a Spectra and a JPEG codec),
  `tests/python/unit/test_image_converter.py`
  (`convert_image_bytes_cropped_with_preview` byte-exact against
  `convert_image_bytes_cropped`),
  `tests/python/library/test_library_crop_albums_backfill.py`
  (`crop_box_override` wins over a saved manual crop and bypasses the
  `.bin` cache read and write).
  **Panel-tested** — `tests/panel/messages.spec.js` (compose modal
  defaults, all three styles selectable, target-type toggle switches the
  visible picker, save-to-library disabled + hinted for a scene target,
  frame-target and wall-target-with-save-to-library send bodies, empty
  text rejected client-side, backend failure surfaced in the feedback
  div).

---

## Coverage summary

| Phase | Scope | Status |
|---|---|---|
| 0 | Backend pytest infrastructure | Done |
| 1 | Image conversion, render spec, frame-type registry (KPFs 7, 22, 23) | Done |
| 2 | Coordinator: polling, IP healing, pull-first send / provision, concurrency (KPFs 3, 4, 4b) | Done |
| 3 | Config flow, setup lifecycle, services, intent, entities, onboarding backend (KPFs 1, 2, 5, 6, 21, 24, 25) | Done |
| 4 | Scenes, scene packs, walls, schedules, skills managers (KPFs 16, 17, 19, 20, 28) | Done (KPF 18's widget scheduling/subprocess execution still a gap) |
| 5 | Library: local backend, crop, albums, backfill (KPFs 8, 11, 12, 13) | Done |
| 5b | Library: Dropbox/Google Drive cloud backends + OAuth, discovery (KPFs 9, 10), and the `*_http.py` view layer (KPFs 14, 15, 29's views + the rest) | Planned |
| — | Panel init-load resilience, panel element lifecycle, Lovelace card (KPFs 26, 27, 29) | Done — frontend side; KPF 29's HTTP views fold into 5b |
| — | Media Source & AI Auto-tagging (KPFs 30, 31) | Done |
| — | Compose & send a styled text message (KPF 35) | Done |

Phase 5b (plus KPF 18's widget scheduling) is scoped here but not yet
implemented — see [TESTING_STRATEGY.md](../TESTING_STRATEGY.md) for the
checkpoint tracker.
