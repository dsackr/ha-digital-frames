"""Domain-level setup wiring (KPF 25): async_setup / async_setup_entry /
async_unload_entry / async_remove_entry.

If this silently breaks: the whole integration fails to load, or (subtler)
removing the last frame leaves scene-pack/schedule timers running forever,
or doesn't prune wall layouts.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.const import DOMAIN, KIND_SCENES_HUB


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    monkeypatch.setattr(
        "custom_components.digital_frames.coordinator.async_get_clientsession",
        lambda hass: _FakeSession(),
    )


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return {"battery": 90, "width": 1200, "height": 1600}

    async def text(self):
        return ""


class _FakeSession:
    def get(self, *a, **kw):
        return _FakeResponse()

    def post(self, *a, **kw):
        return _FakeResponse()


async def test_fresh_install_auto_creates_scenes_hub_once(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hub_entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get("kind") == KIND_SCENES_HUB
    ]
    assert len(hub_entries) == 1


async def test_late_bound_tracker_watch_does_not_violate_thread_safety(
    hass, make_frame_entry, caplog
):
    """Regression: __init__._bind_tracker (the EVENT_HOMEASSISTANT_STARTED
    listener that (re)binds the device_tracker wake-watch for entries set up
    before HA finished starting) was a plain, undecorated function. Home
    Assistant's HassJob auto-detection runs an undecorated listener in the
    executor thread pool rather than on the event loop -- so the moment it
    ran, coordinator.py's `self.hass.async_create_task(...)` (inside
    `_async_on_network_home`, reached here because the tracker starts
    already home) executed from a worker thread instead of the event loop.
    HA's own thread-safety guard flags this as able to "crash or data to
    corrupt" -- confirmed in production logs as the actual trigger behind
    repeated Supervisor watchdog restarts. Missing `@callback` was the fix;
    this reproduces the exact late-bind path (hass not yet running at setup)
    that only exercises it.
    """
    from homeassistant.const import STATE_HOME, EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    entry = make_frame_entry(host="192.168.1.50", mac="aabbccddeeff")
    entry.add_to_hass(hass)

    hass.states.async_set(
        "device_tracker.frame_wifi",
        STATE_HOME,
        {"ip": "192.168.1.50", "mac": "aa:bb:cc:dd:ee:ff"},
    )

    hass.set_state(CoreState.not_running)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert "thread other than the event loop" not in caplog.text


async def test_unload_removes_services_only_when_last_frame_gone(
    hass, make_frame_entry
):
    entry1 = make_frame_entry(host="192.168.1.50", entry_id="entry-1")
    entry2 = make_frame_entry(host="192.168.1.51", entry_id="entry-2")
    entry1.add_to_hass(hass)
    entry2.add_to_hass(hass)

    # Setting up the "fraimic" component for the first time sets up every
    # already-added entry for that domain in one pass (see
    # ConfigEntries.async_setup) -- a second explicit async_setup() call for
    # entry2 would raise since it's already loaded by this point.
    assert await hass.config_entries.async_setup(entry1.entry_id)
    await hass.async_block_till_done()
    from homeassistant.config_entries import ConfigEntryState

    assert entry2.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "send_image")

    await hass.config_entries.async_unload(entry1.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "send_image"), (
        "services must survive as long as any frame entry remains"
    )

    await hass.config_entries.async_unload(entry2.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "send_image")


async def test_remove_entry_prunes_wall_placement(hass, make_frame_entry):
    from custom_components.digital_frames.walls import DEFAULT_WALL_ID

    entry = make_frame_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    wall_manager = hass.data[DOMAIN]["_walls"]
    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    assert entry.entry_id in default_wall.placements

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    default_wall = await wall_manager.async_get_wall(DEFAULT_WALL_ID)
    assert entry.entry_id not in default_wall.placements


async def test_reload_picks_up_scan_interval_option_change(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(entry, options={"scan_interval": 900})
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    from datetime import timedelta

    assert coordinator.update_interval == timedelta(seconds=900)


async def test_scenes_hub_entry_has_no_coordinator(hass, make_scenes_hub_entry):
    entry = make_scenes_hub_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]


async def test_offline_fraimic_frame_keeps_coordinator_for_send(
    hass, make_frame_entry, monkeypatch
):
    """Sleeping frames must still load — otherwise send/queue has no coordinator.

    Regression: first_refresh ConfigEntryNotReady used to put Fraimic entries
    in setup_retry and remove them from hass.data, so "Send to Frames" failed
    with "No frame coordinator found" while Desktop/Meural (online or soft-
    fail) still worked.
    """
    import aiohttp
    from homeassistant.config_entries import ConfigEntryState

    class _OfflineResponse:
        async def __aenter__(self):
            raise aiohttp.ClientConnectionError("frame asleep")

        async def __aexit__(self, *a):
            return False

    class _OfflineSession:
        def get(self, *a, **kw):
            return _OfflineResponse()

        def post(self, *a, **kw):
            return _OfflineResponse()

    monkeypatch.setattr(
        "custom_components.digital_frames.coordinator.async_get_clientsession",
        lambda hass: _OfflineSession(),
    )

    entry = make_frame_entry(host="192.168.1.99", entry_id="asleep-frame")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id in hass.data[DOMAIN]
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator is not None
    assert coordinator.last_update_success is False


async def test_31_5_entry_auto_migrates_resolution(hass, make_frame_entry):
    """31.5" entries created at 2560x1440 before resolution fix auto-migrate to 2560x1800."""
    from custom_components.digital_frames.const import CONF_HEIGHT, CONF_SIZE, CONF_WIDTH

    entry = make_frame_entry(size="31.5", width=2560, height=1440)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    migrated_entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert migrated_entry.data[CONF_WIDTH] == 2560
    assert migrated_entry.data[CONF_HEIGHT] == 1800

