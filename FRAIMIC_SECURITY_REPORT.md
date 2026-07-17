# Fraimic Frame — Local HTTP Security Report

**Reporter:** Dale Sackrider
**Date observed:** 2026-07-09
**Affected:** Fraimic digital canvas frames, current firmware, local HTTP
interface on port 80 (device's own web UI at `http://<frame-ip>/`)
**Discovered:** accidentally, while inspecting a frame's local endpoints on my
own network — a single unauthenticated request factory-reset the device.

---

## Summary

Every endpoint on a Fraimic frame's local web interface is served **without any
authentication**. Any device on the same network can read device/account
information and perform destructive actions. Most seriously, the **factory-reset
action is reachable via an unauthenticated HTTP `GET`**, which not only removes
the "must be on the network" barrier in practice (via CSRF) but also wipes the
device with no confirmation and no credentials.

I was able to factory-reset a fully set-up, signed-in frame with one ordinary
GET request and no authentication of any kind.

## Severity

**High.** Combines trivial exploitability, no authentication, a destructive
outcome (full device wipe requiring re-setup), and a remote attack path (CSRF).
Additional endpoints expose privacy-sensitive capabilities (microphone,
accelerometer) and personal data (linked account email).

---

## Findings

### 1. Factory reset via unauthenticated GET (most critical)

- `GET http://<frame-ip>/action` triggered a **full factory reset**: settings
  cleared, display blanked, Wi-Fi dropped, device returned to first-run setup.
- No authentication, no session/cookie, no CSRF token, and no confirmation step
  were required. A bare GET with **no parameters** was sufficient (the device's
  own test UI uses `/action?mode=reset`, but the reset also fired without the
  parameter).

**Why GET makes this much worse than "someone on your Wi-Fi could do it":**
Because the destructive action is a side-effect-bearing `GET` with no CSRF
protection, it is exploitable by a **malicious web page**, not only by someone
already on the network. A page the frame's owner visits can embed
`<img src="http://.../action">` (or issue `fetch(..., {mode:'no-cors'})`); the
browser fires the request from inside the victim's LAN, and any reachable frame
is reset — with the attacker never touching the local network. This is the same
class as the well-known "drive-by router reset" CSRF attacks.

**Amplifier — the predictable mDNS name removes the last barrier.** In the
general case a CSRF attacker must guess the frame's LAN IP. Fraimic frames do
not require guessing: they advertise a **fixed mDNS/Bonjour hostname,
`fraimic.local`**, which resolves from the browser context on the local network.
A single static payload works everywhere:

```html
<img src="http://fraimic.local/action">
```

Verified: `fraimic.local` resolved via mDNS to a live frame and served requests
normally. (Separately, all frames advertising the **same** `fraimic.local` name
is its own defect — already reported — but combined with this reset bug it makes
the CSRF attack a reliable, zero-knowledge one-liner rather than an IP-guessing
spray. The two issues compound.)

**State-changing actions must never be exposed over GET**, and must require
authentication plus a CSRF token.

### 2. No authentication on any local endpoint

Every endpoint responds to unauthenticated requests from any LAN client:

| Endpoint | Method | Effect | Risk |
|---|---|---|---|
| `/action` | GET | Factory reset | Destructive, CSRF-able |
| `/upload` | POST (multipart, field `image`, `.bin`) | Replace displayed image | Content spoofing / abuse |
| `/wifi` | GET/POST | Reconfigure Wi-Fi | Can move device onto attacker network |
| `/sign-in` | GET/POST | Account sign-in; **GET page pre-fills the linked account email** | Personal data disclosure |
| `/test` | GET + actions | Microphone capture, accelerometer, LED, touch, battery | **Privacy** (mic/motion), device control |
| `/battery/status` | GET | Battery voltage, %, current, temp, cycle count | Info disclosure |
| `/info` | GET | Device information | Info disclosure |
| `/logs` | GET/POST | View / clear logs | Info disclosure, tampering |

Anyone on the same network — a guest, a neighbor within Wi-Fi range on an open
or shared network, another device on a compromised LAN — can do all of the
above.

### 3. Microphone accessible without authorization

The `/test` interface can start the microphone and stream amplitude data
(`?action=mic_start` / `?action=mic_stats`) with no authentication. Unauthorized
activation of a microphone in someone's home is a serious privacy concern on its
own.

### 4. Account email disclosure

The `/sign-in` page returns the **linked Fraimic account email pre-filled** in
the form to any unauthenticated caller, leaking the owner's identity/email to
anyone on the network.

### 5. Read endpoints exposed to DNS-rebinding

Because read endpoints require no auth and don't validate the `Host`/`Origin`
header, they are also reachable via **DNS rebinding**, letting a remote web page
read `/info`, `/battery/status`, `/sign-in` (email), etc., from outside the LAN.

---

## Reproduction

1. On the same network as a set-up frame, note its IP (e.g. `192.168.1.205`).
2. Request `http://192.168.1.205/action` with no auth and no parameters
   (e.g. paste in a browser, or `curl http://192.168.1.205/action`).
3. Observe the frame perform a full factory reset — display blanks, Wi-Fi drops,
   device returns to first-run setup and requires complete re-configuration.

No credentials, tokens, confirmation, or network privileges beyond basic LAN
reachability were required.

---

## Recommended remediation

1. **Never perform state changes on GET.** Move reset, Wi-Fi changes, upload,
   sign-in, and log-clear to POST only.
2. **Require authentication** for all control and sensitive-read endpoints
   (a device password / pairing token set during setup).
3. **Add CSRF protection** (per-session token; reject cross-origin requests) and
   **validate `Origin`/`Host`** to defeat CSRF and DNS-rebinding.
4. **Confirm destructive actions** (reset) with an explicit authenticated,
   non-GET, token-bearing request.
5. **Gate the microphone and factory-test interface** behind authentication and
   ideally a physical action (button press) to enter test mode.
6. **Do not disclose the account email** to unauthenticated callers.

## Disclosure

Reported privately to Fraimic. No third-party frames were accessed; the only
device affected was my own, which has been restored.
