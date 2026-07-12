"""HTTP API views for xOTD content instances.

Endpoints:
    GET    /api/fraimic/xotd                  {"enabled": bool, "instances": [...]}
    POST   /api/fraimic/xotd                  create instance ({content_mode, frame_id, schedule, mode_config[, enabled]})
    POST   /api/fraimic/xotd/{instance_id}    update instance (any of content_mode/frame_id/schedule/mode_config/enabled)
    DELETE /api/fraimic/xotd/{instance_id}    delete instance + disarm
    POST   /api/fraimic/xotd/{instance_id}/run  fire this instance immediately, independent of its schedule
    POST   /api/fraimic/xotd/enabled          install/uninstall the add-on itself ({"enabled": bool}) --
                                               uninstalling (enabled: false) cascades to delete every instance
"""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_xotd_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_xotd")
    if manager is None:
        raise RuntimeError("Xotd manager not initialised")
    return manager


class FraimicXotdInstancesView(HomeAssistantView):
    """List (GET) or create (POST) xOTD instances."""

    url = "/api/fraimic/xotd"
    name = "api:fraimic:xotd"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_xotd_manager(hass)
        instances = await manager.async_list_instances()
        enabled = await manager.async_is_enabled()
        return self.json({"enabled": enabled, "instances": instances})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_xotd_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        from .xotd import XotdError  # noqa: PLC0415

        try:
            instance = await manager.async_create_instance(
                body.get("content_mode"),
                body.get("frame_id"),
                body.get("schedule"),
                body.get("mode_config"),
                enabled=body.get("enabled", True),
            )
        except XotdError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to create xOTD instance: %s", err)
            return self.json_message(
                f"Failed to create xOTD instance: {err}", status_code=500
            )

        return self.json({"success": True, "instance": instance})


class FraimicXotdInstanceView(HomeAssistantView):
    """Update (POST) or delete (DELETE) a single xOTD instance."""

    url = "/api/fraimic/xotd/{instance_id}"
    name = "api:fraimic:xotd:one"
    requires_auth = True

    async def post(self, request: web.Request, instance_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_xotd_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        from .xotd import XotdError  # noqa: PLC0415

        changes = {
            key: body[key]
            for key in ("content_mode", "frame_id", "schedule", "mode_config", "enabled")
            if key in body
        }
        try:
            instance = await manager.async_update_instance(instance_id, changes)
        except XotdError as err:
            status = 404 if "not found" in str(err) else 400
            return self.json_message(str(err), status_code=status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to update xOTD instance '%s': %s", instance_id, err)
            return self.json_message(
                f"Failed to update xOTD instance: {err}", status_code=500
            )

        return self.json({"success": True, "instance": instance})

    async def delete(self, request: web.Request, instance_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_xotd_manager(hass)

        from .xotd import XotdError  # noqa: PLC0415

        try:
            await manager.async_delete_instance(instance_id)
        except XotdError as err:
            return self.json_message(str(err), status_code=404)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete xOTD instance '%s': %s", instance_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})


class FraimicXotdRunView(HomeAssistantView):
    """Fire one instance immediately ("Send Now" on its card), independent
    of its schedule."""

    url = "/api/fraimic/xotd/{instance_id}/run"
    name = "api:fraimic:xotd:run"
    requires_auth = True

    async def post(self, request: web.Request, instance_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_xotd_manager(hass)

        from .xotd import XotdError  # noqa: PLC0415

        try:
            await manager.async_run_now(instance_id)
        except XotdError as err:
            return self.json_message(str(err), status_code=404)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to run xOTD instance '%s': %s", instance_id, err)
            return self.json_message(f"Run failed: {err}", status_code=500)
        return self.json({"success": True})


class FraimicXotdEnabledView(HomeAssistantView):
    """Install (enabled: true) or uninstall (enabled: false) the xOTD
    add-on itself -- the binary switch shown as a normal pack card in the
    Add-ons tab, independent of any instance. Uninstalling cascades to
    delete every instance (see XotdManager.async_set_enabled)."""

    url = "/api/fraimic/xotd/enabled"
    name = "api:fraimic:xotd:enabled"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_xotd_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        try:
            await manager.async_set_enabled(bool(body.get("enabled")))
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to set xOTD enabled state: %s", err)
            return self.json_message(f"Failed: {err}", status_code=500)

        return self.json({"success": True, "enabled": await manager.async_is_enabled()})
