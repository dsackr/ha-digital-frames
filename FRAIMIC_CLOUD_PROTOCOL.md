# Fraimic Cloud Protocol — Captured Findings

_Captured 2026-07-09 by driving `app.fraimic.com` under a headless browser
(Playwright) and recording the full HTTP transcript (HAR) while performing real
operations: sign-in, upload image, "Send to Canvas", and create a scheduled
slideshow. Account: dale.sackrider@gmail.com. All observations are from actual
requests/responses, not guesses. The one inferred piece (frame→cloud polling)
is labelled as such._

> Note: the Home Assistant integration does **not** use any of this — it talks
> to frames locally (see `reference_frame_local_http_api` / the local `/upload`
> endpoint). This document is about how Fraimic's **own** cloud drives frames,
> captured to understand capabilities (esp. slideshow scheduling) we may want to
> reproduce locally.

## Architecture at a glance

```
Browser (app.fraimic.com SPA, React)
   │  1. Auth ───────────────►  Supabase  (sclpedxwezoiwzesfdps.supabase.co)
   │                             POST /auth/v1/token?grant_type=password → JWT
   │  2. App API (Bearer JWT) ►  origin.fraimic.com/api/v1/...   (REST/JSON)
   │  3. Image bytes ─────────►  S3  (fraimic-prod-user-files.s3.amazonaws.com)
   │                             via presigned POST policy
   │  4. Live device status ──►  Supabase Realtime (WebSocket)  → online dots
   ▼
Frame  ◄── pulls prepared image from cloud on tap / poll (INFERRED, see below)
```

- **Frontend:** SPA at `https://app.fraimic.com` (title "Fraimic Dashboard";
  routes `/home`, `/albums`, `/gallery`, `/gallery/{id}`). Fonts via typekit.
- **Auth:** Supabase GoTrue. `POST /auth/v1/token?grant_type=password` with
  `{email,password}` → JWT. Subsequent API calls send it as a Bearer token.
- **App API base:** `https://origin.fraimic.com/api/v1`.
- **Image storage:** S3 bucket `fraimic-prod-user-files`, keyed per user:
  `users/{user_id}/YYYY/MM/DD/{ts}-{uuid}/original.jpg`.

## API endpoints observed

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/v1/token?grant_type=password` (Supabase) | Login → JWT |
| GET | `/api/v1/account/devices` | List frames on the account (full device records) |
| GET | `/api/v1/gallery?page=&page_size=` | User's saved images (paged) |
| GET | `/api/v1/gallery/{upload_id}` | Single image detail |
| GET | `/api/v1/discover?limit=&offset=` | Curated art (The Met Collection, etc.) |
| GET | `/api/v1/albums` | List albums (= slideshows) |
| POST | `/api/v1/albums` | **Create album / schedule slideshow** (see below) |
| DELETE | `/api/v1/albums/{id}` | Delete an album (immediate, no confirm call) → 200 |
| POST | `/api/v1/upload/image/presign?content_type=&mark_for_check_for_upload=` | Get S3 presigned upload |
| PUT | `/api/v1/upload/image/refresh` | **Prepare an image for a frame** (crop + orientation); "Send to Canvas" |

## Image upload (2-step, presigned S3)

1. `POST /api/v1/upload/image/presign?content_type=image%2Fjpeg&mark_for_check_for_upload=false`
   → response:
   ```json
   {"success":true,
    "url":"https://fraimic-prod-user-files.s3.amazonaws.com/",
    "fields":{"Content-Type":"image/jpeg","x-amz-server-side-encryption":"AES256",
              "key":"users/{user_id}/2026/07/09/{ts}-{uuid}/original.jpg",
              "AWSAccessKeyId":"...","x-amz-security-token":"...","policy":"...","signature":"..."}}
   ```
2. Browser POSTs the file directly to the S3 `url` with those `fields`
   (standard S3 browser POST-policy upload).
3. The image is thereafter referenced by its **`upload_id`** (a UUID, also
   called `upload_public_id`).

The `mark_for_check_for_upload` query flag is the tell that **frames poll the
cloud for pending content** (see delivery, below).

## Send a single image to a frame ("Send to Canvas")

Selecting an image opens a crop editor with **Frame size** (13.3" / 31.5"),
**Orientation** (portrait / landscape), and a **Send to Canvas** button.

Clicking **Send to Canvas** issues exactly one write:

```
PUT /api/v1/upload/image/refresh
{"upload_public_id":"{upload_id}",
 "orientation":"portrait",              // or "landscape"
 "crop_params":{"unit":"percent","x":13.114,"y":24.523,
                "width":73.164,"height":65.034,
                "display_type":"133","orientation":"portrait"}}
→ true
```

This prepares/renders the image for the target display type. It does **not**
name a device. A modal then says:

> "Tap the lower-right-hand corner of the frame you'd like to send your image
> to."
> Tip: Enable "Keep Device Awake" in Account Settings to send images without
> tapping the frame.
> — plus a **Select Canvas** list of the account's frames (each with a
> green online dot).

**Selecting a canvas from that list issued NO further API call** we could
capture. Conclusion: delivery is **frame-initiated** — the prepared image
becomes the pending image, and the frame fetches it when it (a) is physically
tapped on the lower-right corner, or (b) is awake and polling ("Keep Device
Awake"). This matches the `mark_for_check_for_upload` flag. (The exact poll
request is frame→cloud and was not captured here — see "Not captured".)

Note the orientation control ties directly to the on-device accelerometer
finding (`ACCELEROMETER_FINDINGS.md`): the frame knows its own orientation, and
the cloud crop/render is orientation-aware.

## Create / schedule a slideshow (album)

A "slideshow" is an **album with slideshow mode on**. Creating one is a single
write that fully expresses the schedule:

```
POST /api/v1/albums
{"name":"HA Protocol Test",
 "description":"...",
 "active":true,
 "device_assignments":[{"device_id":"862305bf-...643d3"}],
 "schedule":{"type":"interval","interval_value":24,"interval_unit":"hours"},
 "playback_mode":"sequential",
 "upload_ids":["d4b35c98-...49b0"]}
```

Response echoes it and adds `id`, `image_count`, `images[]` (with S3 URLs), and
normalizes the schedule to include `days:null`:

```json
{"id":"a334fd82-...","schedule":{"type":"interval","interval_value":24,
 "interval_unit":"hours","days":null}, ...}
```

**Schedule model (from the UI + payload):**
- `schedule.type`:
  - `"interval"` — the "Every X Time" option: rotate every
    `interval_value` × `interval_unit` (unit seen: `"hours"`).
  - `"days"`(implied) — the "Specific Days" option; would populate `days`.
- `playback_mode`: `"sequential"` or `"random"`.
- `device_assignments`: array of `{device_id}` — which frames run the slideshow.
- `upload_ids`: the images in the slideshow.
- `active`: on/off.

## Device model (`GET /api/v1/account/devices`)

Each frame record:
```json
{"device_id":"1d7c8b2a-...","user_id":"df3d310b-...","device_name":"assylCanvas 4A",
 "display_type":"133","battery_pct":54,"wifi_ssid":"TheMachine",
 "ip_address":"192.168.1.240","last_seen_at":"2026-07-08T21:37:38",
 "settings":{"style":"NONE","keepAwakeEnabled":true,"chargingLedEnabled":false,
             "voiceRecordingEnabled":false},
 "pending_settings":{...}}
```
Notable: the cloud stores each frame's **LAN `ip_address`**, battery, Wi-Fi SSID,
last-seen, and toggles including **`voiceRecordingEnabled`** and
`keepAwakeEnabled`. `pending_settings` vs `settings` implies settings are staged
and applied on the frame's next check-in (again consistent with polling).

The account here has four 13.3" frames: ZanderaCanvas 1ZanderZ, ixeCanvas 2L,
AidenedinediCanvas 3AA, assylCanvas 4A.

## Not captured (the frame↔cloud half)

The one thing not directly observed is the **frame→cloud poll** — the request a
frame makes to discover and download its pending image / slideshow / settings.
Everything above is consistent with such a poll (`mark_for_check_for_upload`,
`pending_settings`, tap-to-pull, "Keep Device Awake"), but the actual request
shape is server↔device and doesn't pass through the browser. Capturing it needs
network-level interception (transparent proxy) on a frame's own traffic —
feasibility depends on whether the frame validates TLS. Deferred.

## Reproduction / tooling

Captured with the Playwright harness in `scratchpad-capture/` (gitignored):
`drive.mjs` logs in (creds via `FR_EMAIL`/`FR_PASS` env), reuses `state.json`,
and records `<phase>.har` with full request/response bodies. Re-runnable.
