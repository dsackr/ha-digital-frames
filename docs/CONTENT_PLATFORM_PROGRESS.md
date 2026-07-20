# Content platform — implementation progress / handoff

**Read this first if resuming work.** Full plan: [CONTENT_PLATFORM_ROADMAP.md](CONTENT_PLATFORM_ROADMAP.md).

| Field | Value |
|---|---|
| **Last updated** | 2026-07-19 |
| **Active phase** | **Phase 4 next** (Agenda → Live generator) |
| **Branch** | working tree on `main` (not necessarily committed — check `git status`) |
| **Repos** | this repo + `/Users/dsackrider/repos/frame-addons` |

## Status board

| Phase | Status | Notes |
|:---:|---|---|
| 0 Contract | **done** | Roadmap + this handoff file |
| 1 Surface rename | **done** | Gallery / Live labels; Tools section; xotd removed from catalog |
| 2 Gallery install UX | **done** | `create_scene` flag + Install + scene / Library only |
| 3 Live quick-setup | **done** | `POST …/live/quick_setup` + Schedule daily on Live cards |
| 4 Agenda as Live | **pending** | Start here next |
| 5 Retire widgets | **pending** | After 4 |
| 6 Catalog split | **pending** | After 5 |
| 7 Marketplace | not started | Later |

## Resume checklist for the next agent

1. Read this file + [CONTENT_PLATFORM_ROADMAP.md](CONTENT_PLATFORM_ROADMAP.md) Phase **4**.
2. `git status` / `git diff` in **both**:
   - `ha-digital-frames` / `fraimic-homeassistant` (this repo)
   - `../frame-addons` (xotd catalog entry removed; README rewritten — **may need commit/push** so HA installs that pull raw `main` see the catalog change)
3. Run:
   ```bash
   .venv/bin/python -m pytest -q tests/python/managers/test_scene_packs.py \
     tests/python/managers/test_live_quick_setup.py tests/python/managers/test_skills.py
   cd tests/panel && npx playwright test skills.spec.js addons-categories.spec.js addons-catalog-refresh.spec.js
   ```
4. **Do not** delete widget runtime (Phase 5) until Agenda migration ships.
5. When finishing a phase: update this board, tick roadmap ship criteria, amend KPF Test status, commit.

## What shipped in this session (Phases 1–3)

### Phase 1 — Surface rename
- Panel tabs: **Gallery** / **Live** (internal `data-tab` still `addons` / `xotd`).
- Copy: art collections, Tools (legacy agenda), live content (not “skills” as primary noun).
- `PANEL_VERSION` → `0.11.0`.
- Card empty state: Live tab wording.
- **frame-addons:** removed pack id `xotd` from `scene_packs/index.json`; README rewritten for Digital Frames / Gallery / Live. Widget left: `daily_agenda` only.

### Phase 2 — Gallery install
- `ScenePackManager.async_install_pack(..., create_scene=True)`.
- HTTP `POST …/install` accepts `{ "create_scene": bool }`.
- Panel: **Install + scene** / **Library only** on art cards; widgets still **Set up**.
- Test: `test_install_pack_library_only_skips_scene`.

### Phase 3 — Live quick-setup
- `DigitalFramesLiveQuickSetupView` → `POST /api/digital_frames/live/quick_setup`.
- Registered in `__init__.py`.
- Panel Live cards: time input + **Schedule daily** → creates schedule(s).
- Tests: `tests/python/managers/test_live_quick_setup.py`.

### Docs updated
- KPF 17, 18, 28 amended.
- CONTRIBUTING points at roadmap/progress.
- This file + roadmap status should stay in sync.

## Phase 4 — next work (do this next)

**Goal:** Daily Agenda is a Live generator (skill + schedule + FramePort send), not a widget.

Concrete steps (from roadmap):

1. **frame-addons** `addons/daily_agenda/agenda_renderer.py`: add `--render-only` / `--config` contract like xOTD (write preview PNG + spectra bin; **no frame HTTP** in that mode).
2. **ha-digital-frames** `skills.py`: new `content_mode` e.g. `agenda`; pin script SHA in `const.py` (mirror `XOTD_RENDERER_*`).
3. Render path → `text_skill_payload_for_codec` / library send as appropriate.
4. **Migration** from installed widget `daily_agenda` → skill + schedule(s); one-shot storage flag (mirror `_async_migrate_xotd_instances`).
5. Live UI: agenda config (calendars, weather) — reuse schema engine.
6. Keep widget path as fallback until Phase 5.
7. Tests: migration + render mock; amend KPF 18 → superseded by 28 or rewrite.
8. Update this progress file when 4 is done.

## Open risks / notes

- Catalog change only affects users after **frame-addons `main` is pushed**. Local HA still hits GitHub raw.
- Internal tab ids not renamed (Playwright still uses `data-tab="addons"` / `xotd`) — intentional Phase 1 choice.
- Widget scheduler still exists for Agenda only.
- Uncommitted Meural discovery work may also be in the tree from an earlier session — separate from this roadmap; don’t mix commits carelessly.

## Working notes (append-only)

### 2026-07-19 — kickoff + Phases 1–3
- User: execute workover; update docs for handoff if tokens run out.
- Implemented Phases 1–3; left Phase 4+ for next session.
