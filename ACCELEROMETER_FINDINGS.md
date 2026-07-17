# Fraimic Frame Accelerometer — Findings

_Investigated 2026-07-09 against a live frame on the local network: `Fraimic_29488` at `http://192.168.1.117`. No authentication required on the local network._

## TL;DR

The frame has a working 3-axis accelerometer. It can determine its own
orientation (portrait / landscape / which-way-rotated) and tilt. Today it is
**only** readable through the hidden factory-test API at `/test`, and **only**
after you explicitly power the sensor on with a `start` call. There is no
passive/always-on orientation readout, and no other endpoint exposes it.

## How to read it (the exact protocol)

The `/test` page is a factory test console. Accelerometer access is a
three-step sequence:

1. **Start (powers the sensor on):**
   ```
   POST http://<frame-ip>/test?action=accel_start
   → {"status":"ok"}
   ```

2. **Read (poll as often as you want; the built-in page polls every 100 ms):**
   ```
   GET http://<frame-ip>/test?action=accel
   → {"x":-0.988,"y":-0.001,"z":0.183}
   ```

3. **Stop (powers the sensor back off):**
   ```
   POST http://<frame-ip>/test?action=accel_stop
   → {"status":"ok"}
   ```

**Gating behavior:** if you call `accel` without calling `accel_start` first,
you get:
```
{"error":"accel not available","x":0,"y":0,"z":0}
```
So the sensor is off by default. There is no way to sample it passively.

## What the numbers mean

- Values are in **g** (1.0 = one gravity). At rest, the axis pointing "down"
  reads ~±1.0 and the other two read ~0.
- A real reading from the frame standing on the network:
  `x ≈ -0.99, y ≈ 0.00, z ≈ 0.18`
  - Gravity is almost entirely on the **X axis** → the frame is oriented so X
    is vertical.
  - `z ≈ 0.18` → the frame is leaning back about 10° (arcsin(0.18) ≈ 10°),
    consistent with sitting on an easel stand or hung with a slight tilt.

### Deriving orientation (no math needed beyond this)

Whichever of X / Y carries gravity, and its sign, gives you all four
rotations:

| Gravity axis & sign | Orientation |
|---|---|
| X ≈ -1 | (as-tested resting orientation) |
| X ≈ +1 | rotated 180° from that |
| Y ≈ -1 | rotated 90° one way |
| Y ≈ +1 | rotated 90° the other way |

(Exact label-to-sign mapping should be confirmed by physically rotating a
frame and recording readings, but the four cases are unambiguous once you do
that once.) The Z axis is the front-to-back tilt and is not needed for
orientation.

## Other endpoints checked (for completeness)

- `/status` → "Nothing matches the given URI" (does not exist)
- `/state` → "Nothing matches the given URI" (does not exist)
- `/info` → exists (HTML device info page) but contains **no** orientation /
  rotation / accelerometer field. Grepped for orientation/rotate/accel/
  portrait/landscape — nothing.
- The `/test` console also exposes: image upload (`action=upload`, POST .bin),
  LED cycle (`action=led`), microphone level (`action=mic_start` /
  `mic_stats` / `mic_stop`), touch count (`action=touch`), battery charging
  (`action=battery`), and factory reset (`/action?mode=reset`).

## Implications for the Home Assistant integration

- **Zero-config detection is feasible today** without firmware changes: an HA
  action could run `accel_start` → `accel` → `accel_stop` on demand, translate
  the dominant axis into an orientation label, and store it. This fits the
  "must work zero-config" rule — no hand-edited YAML.
- **Constraint:** the frame must be **awake and reachable** for the
  start→read→stop sequence. Mains-powered frames are fine. Battery frames sleep,
  so they can only be sampled opportunistically — e.g. while already awake
  serving another request. Continuous "report orientation at every check-in"
  would require firmware support.
- **Politeness:** always call `accel_stop` after reading so the sensor doesn't
  stay powered. Don't leave a poll loop running against a battery frame.

## Open questions to confirm on hardware later

1. Exact sign→label mapping for the four rotations (rotate a real frame and
   record).
2. Does the firmware debounce/settle the reading, or should the caller average
   a few samples (the values jittered in the third decimal: x -0.988 →
   -0.993 → -0.992)?
3. Does `accel_start` survive across the frame going to sleep, or must it be
   re-issued every wake?
