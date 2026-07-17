# Fraimic Cloud — Image Delivery Goes to the Wrong Frame (Nondeterministic)

**Reporter:** Dale Sackrider
**Date:** 2026-07-09
**Severity:** High (functional) — "Send to Canvas" frequently delivers to a
frame other than the one selected, inconsistently.

## Summary

Sending an image from `app.fraimic.com` ("Send to Canvas") does not reliably
deliver to the chosen frame. Across a controlled test, the destination was
**nondeterministic**: the *same* action (select Frame 159 as the target)
produced different destination frames on different attempts. The image usually
goes to the **last-tapped / currently-active** frame; the on-screen "Select
Canvas" choice only sometimes takes effect. This reproduces the real-world
symptom of images landing on the wrong frame.

## Setup

Account with four 13.3" frames (renamed to match their LAN IPs during testing):

| Frame | LAN IP | Backend |
|---|---|---|
| Frame 117 | .117 | prod |
| Frame 159 | .159 | prod |
| Frame 205 | .205 | prod |
| Frame 240 | .240 | **dev** (cannot receive prod sends) |

Each test image was labelled on-screen with the intended target so the
destination was unambiguous. "Last tapped" = the frame whose lower-right corner
was physically tapped most recently (the send modal's primary instruction is
"tap the lower-right corner of the frame you'd like to send to").

## Results

| # | Selected in "Select Canvas" | Last tapped / active | Landed on | Selection honored? |
|---|---|---|---|---|
| 1 | Frame 205 | 205 | 205 | ambiguous (same) |
| 2 | Frame 240 (dev) | 205 | 205 | no (240 is on dev; can't receive) |
| 3 | Frame 159 | 205 | **205** | **no** |
| 4 | Frame 159 (205 asleep) | 205 | **205** | **no** |
| 5 | *(none)* | 159 | 159 | n/a — went to active |
| 6 | Frame 159 | 117 | **159** | **yes** |
| 7 | *(none — 205 not offered)* | 117 | 117 | n/a — went to active |
| 8 | Frame 159 | 117 | **117** | **no** |

**The decisive comparison is #6 vs #8:** identical inputs (select Frame 159,
last tap 117), opposite outcomes (159 vs 117). The destination is not
deterministic.

## What is reasonably established

1. **A no-selection send goes to the last-tapped / active frame** (#5, #7 —
   consistent).
2. **A physical tap sets that active frame** (#5: tap 159 → 159).
3. **The "Select Canvas" choice is honored only sometimes** — ignored in #3,
   #4, #8; honored in #6. Most sends (5 of 6 with a selection) went to the
   active frame regardless of what was picked.
4. **Delivery is cloud-side, not mDNS/LAN.** The `fraimic.local` owner (Frame
   240) never received sends, including one targeted to it; and 240 is on the
   dev backend so it cannot receive prod sends at all. (Shared `fraimic.local`
   is a real but *separate* defect.)
5. **Delivery does not require the destination to be awake.** In #4 the winning
   frame (205) was asleep — keep-awake off, local web server unreachable — yet
   it displayed the image. The frame receives over a cloud channel that
   persists through sleep.

## Likely mechanism (hypothesis, not proven)

The send (`PUT /api/v1/upload/image/refresh`, which carries **no `device_id`**)
marks a single pending image; both a physical tap and a canvas selection appear
to set a "target"/"active" frame, and delivery is decided by a **race** between
them (and/or by which frame polls/claims the pending image first). Because the
canvas selection is not authoritatively bound to the image server-side, whether
it "wins" over the last-tapped frame is timing-dependent — hence the
inconsistency. The frame→cloud poll itself was not captured (it does not pass
through the browser), so the exact tiebreak is unconfirmed.

## Reproduction

1. Physically tap Frame A's lower-right corner.
2. In the web app, upload/select an image, "Send to Canvas", and pick Frame B
   (≠ A) from the list.
3. Observe: the image lands on A or B unpredictably across repeated attempts.

## Suggested fix

Bind the send to the selected `device_id` authoritatively server-side (include
it in `image/refresh` or a dedicated per-device "set current image" call) so the
chosen frame is the single source of truth. The physical-tap path and the
"Select Canvas" path must not both set a target and race; one must win
deterministically (and the UI should reflect which).

## Note for the Home Assistant integration

The integration's local-first approach (push directly to a frame's LAN
`POST /upload`) targets a specific frame deterministically, avoiding this
cloud-side race entirely.

---
_Method: images sent via the real web-app flow driven by a headless browser;
destinations reported by direct observation of the physical displays. HTTP
captured via HAR. Frame→cloud poll not captured._
