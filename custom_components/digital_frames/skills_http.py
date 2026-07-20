"""HTTP API views for Digital Frames skills / Live content.

Endpoints:
    GET    /api/digital_frames/skills                 list skills
    POST   /api/digital_frames/skills                 create a skill ({name, content_mode, config})
    POST   /api/digital_frames/skills/{skill_id}      update a skill ({name, content_mode, config})
    DELETE /api/digital_frames/skills/{skill_id}      delete a skill
    POST   /api/digital_frames/skills/{skill_id}/send send a skill to one frame now ({entry_id})
    POST   /api/digital_frames/live/quick_setup       skill + frame(s) + daily time → schedule(s)
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_skill_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_skills")
    if manager is None:
        raise RuntimeError("Skill manager not initialised")
    return manager


def _parse_skill_body(body: Any) -> tuple[str | None, str | None, dict]:
    if not isinstance(body, dict):
        return None, None, {}
    name = body.get("name")
    content_mode = body.get("content_mode")
    config = body.get("config")
    if not isinstance(config, dict):
        config = {}
    return name, content_mode, config


class DigitalFramesSkillsView(HomeAssistantView):
    """List (GET) or create (POST) skills."""

    url = "/api/digital_frames/skills"
    name = "api:digital_frames:skills"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_skill_manager(hass)
        skills = await manager.async_list_skills()
        return self.json({"skills": skills})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_skill_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, content_mode, config = _parse_skill_body(body)

        from .skills import SkillError  # noqa: PLC0415

        try:
            skill = await manager.async_save_skill(name, content_mode, config)
        except SkillError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to create skill: %s", err)
            return self.json_message(f"Failed to create skill: {err}", status_code=500)

        return self.json({"success": True, "skill": skill})


class DigitalFramesSkillView(HomeAssistantView):
    """Update (POST) or delete (DELETE) a single skill."""

    url = "/api/digital_frames/skills/{skill_id}"
    name = "api:digital_frames:skills:one"
    requires_auth = True

    async def post(self, request: web.Request, skill_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_skill_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, content_mode, config = _parse_skill_body(body)

        from .skills import SkillError  # noqa: PLC0415

        try:
            skill = await manager.async_save_skill(
                name, content_mode, config, skill_id=skill_id
            )
        except SkillError as err:
            status = 404 if "not found" in str(err) else 400
            return self.json_message(str(err), status_code=status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to update skill '%s': %s", skill_id, err)
            return self.json_message(f"Failed to update skill: {err}", status_code=500)

        return self.json({"success": True, "skill": skill})

    async def delete(self, request: web.Request, skill_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_skill_manager(hass)
        try:
            await manager.async_delete_skill(skill_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete skill '%s': %s", skill_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})


class DigitalFramesSkillSendView(HomeAssistantView):
    """Send one skill to one frame now (ad hoc, no scene/schedule needed)."""

    url = "/api/digital_frames/skills/{skill_id}/send"
    name = "api:digital_frames:skills:send"
    requires_auth = True

    async def post(self, request: web.Request, skill_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_skill_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict) or not body.get("entry_id"):
            return self.json_message("Request body needs an entry_id", status_code=400)
        entry_id = body["entry_id"]

        if await manager.async_get_skill(skill_id) is None:
            return self.json_message(f"Skill '{skill_id}' not found", status_code=404)

        scene_manager = hass.data.get(DOMAIN, {}).get("_scenes")
        if scene_manager is None:
            return self.json_message("Scene manager not initialised", status_code=500)

        try:
            result = await scene_manager.async_send_mappings(
                hass, {entry_id: {"type": "skill", "skill_id": skill_id}}
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to send skill '%s': %s", skill_id, err)
            return self.json_message(f"Failed to send skill: {err}", status_code=500)

        results = result.get("results", [])
        success = bool(results) and all(r.get("success") for r in results)
        return self.json({"success": success, "results": results})


class DigitalFramesLiveQuickSetupView(HomeAssistantView):
    """Content Platform Phase 3: one-shot Live routine setup.

    Body:
      skill_id: str (required) — existing Live content preset
      entry_ids: list[str] (required unless on_demand_only)
      time: "HH:MM" daily fire (default "08:00")
      on_demand_only: bool — if true, create no schedules (skill must already exist)

    Creates one daily recurring schedule per frame. Does not clone skills.
    """

    url = "/api/digital_frames/live/quick_setup"
    name = "api:digital_frames:live:quick_setup"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        skill_manager = _get_skill_manager(hass)
        schedule_manager = hass.data.get(DOMAIN, {}).get("_schedules")
        if schedule_manager is None:
            return self.json_message(
                "Schedule manager not initialised", status_code=500
            )

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        skill_id = (body.get("skill_id") or "").strip()
        if not skill_id:
            return self.json_message("skill_id is required", status_code=400)

        skill = await skill_manager.async_get_skill(skill_id)
        if skill is None:
            return self.json_message(f"Skill '{skill_id}' not found", status_code=404)

        if body.get("on_demand_only"):
            return self.json(
                {
                    "success": True,
                    "skill_id": skill_id,
                    "schedules": [],
                    "on_demand_only": True,
                }
            )

        entry_ids = body.get("entry_ids") or body.get("entry_id")
        if isinstance(entry_ids, str):
            entry_ids = [entry_ids]
        if not isinstance(entry_ids, list) or not entry_ids:
            return self.json_message(
                "entry_ids must be a non-empty list of frame entry ids",
                status_code=400,
            )
        entry_ids = [str(e).strip() for e in entry_ids if str(e).strip()]
        if not entry_ids:
            return self.json_message("entry_ids must be non-empty", status_code=400)

        time_str = (body.get("time") or "08:00").strip()
        # Accept HH:MM or HH:MM:SS — schedules validate HH:MM.
        parts = time_str.split(":")
        if len(parts) >= 2:
            time_str = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"

        skill_name = getattr(skill, "name", None) or skill_id

        from .schedules import ScheduleError  # noqa: PLC0415

        created: list[dict] = []
        try:
            for entry_id in entry_ids:
                entry = hass.config_entries.async_get_entry(entry_id)
                frame_label = (
                    entry.title if entry is not None else entry_id
                )
                name = f"{skill_name} → {frame_label}"
                schedule = await schedule_manager.async_create_schedule(
                    name,
                    {
                        "type": "skill",
                        "entry_id": entry_id,
                        "skill_id": skill_id,
                    },
                    {
                        "type": "recurring",
                        "freq": "daily",
                        "time": time_str,
                    },
                    enabled=True,
                )
                created.append(schedule)
        except ScheduleError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Live quick_setup failed: %s", err)
            return self.json_message(
                f"Failed to create schedule(s): {err}", status_code=500
            )

        return self.json(
            {
                "success": True,
                "skill_id": skill_id,
                "schedules": created,
                "on_demand_only": False,
            }
        )
