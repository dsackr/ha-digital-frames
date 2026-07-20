"""Live quick-setup API (Content Platform Phase 3 / KPF 28).

If this silently breaks: users can't one-shot schedule daily Live content
from the Live tab without using the Schedules UI.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.skills_http import DigitalFramesLiveQuickSetupView


class _FakeRequest:
    def __init__(self, hass, body):
        self.app = {"hass": hass}
        self._body = body

    async def json(self):
        return self._body


def _payload(resp) -> dict:
    body = resp.body
    if isinstance(body, (bytes, bytearray)):
        return json.loads(body.decode())
    return json.loads(body)


@pytest.mark.asyncio
async def test_quick_setup_creates_daily_skill_schedule(hass, make_frame_entry):
    entry = make_frame_entry(entry_id="frame_kitchen", name="Kitchen")
    entry.add_to_hass(hass)

    skill = SimpleNamespace(
        skill_id="joke_of_the_day",
        name="Joke of the Day",
        to_dict=lambda: {
            "skill_id": "joke_of_the_day",
            "name": "Joke of the Day",
        },
    )

    created = []

    async def _create(name, action, trigger, enabled=True):
        rec = {
            "schedule_id": f"sch_{len(created) + 1}",
            "name": name,
            "action": action,
            "trigger": trigger,
            "enabled": enabled,
        }
        created.append(rec)
        return rec

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["_skills"] = SimpleNamespace(
        async_get_skill=AsyncMock(return_value=skill)
    )
    hass.data[DOMAIN]["_schedules"] = SimpleNamespace(async_create_schedule=_create)

    view = DigitalFramesLiveQuickSetupView()
    resp = await view.post(
        _FakeRequest(
            hass,
            {
                "skill_id": "joke_of_the_day",
                "entry_ids": ["frame_kitchen"],
                "time": "07:30",
            },
        )
    )
    payload = _payload(resp)
    assert payload["success"] is True
    assert payload["skill_id"] == "joke_of_the_day"
    assert len(payload["schedules"]) == 1
    assert created[0]["action"] == {
        "type": "skill",
        "entry_id": "frame_kitchen",
        "skill_id": "joke_of_the_day",
    }
    assert created[0]["trigger"] == {
        "type": "recurring",
        "freq": "daily",
        "time": "07:30",
    }


@pytest.mark.asyncio
async def test_quick_setup_on_demand_only_no_schedules(hass):
    skill = SimpleNamespace(
        skill_id="word_of_the_day",
        name="Word of the Day",
        to_dict=lambda: {"skill_id": "word_of_the_day", "name": "Word of the Day"},
    )
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["_skills"] = SimpleNamespace(
        async_get_skill=AsyncMock(return_value=skill)
    )
    hass.data[DOMAIN]["_schedules"] = SimpleNamespace(
        async_create_schedule=AsyncMock()
    )

    view = DigitalFramesLiveQuickSetupView()
    resp = await view.post(
        _FakeRequest(
            hass,
            {"skill_id": "word_of_the_day", "on_demand_only": True},
        )
    )
    payload = _payload(resp)
    assert payload["success"] is True
    assert payload["schedules"] == []
    assert payload["on_demand_only"] is True
    hass.data[DOMAIN]["_schedules"].async_create_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_quick_setup_missing_skill_404(hass):
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["_skills"] = SimpleNamespace(
        async_get_skill=AsyncMock(return_value=None)
    )
    hass.data[DOMAIN]["_schedules"] = SimpleNamespace(
        async_create_schedule=AsyncMock()
    )
    view = DigitalFramesLiveQuickSetupView()
    resp = await view.post(
        _FakeRequest(hass, {"skill_id": "nope", "entry_ids": ["e1"]})
    )
    assert resp.status == 404
