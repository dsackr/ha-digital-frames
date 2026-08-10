"""HTTP API views for Fraimic walls.

Endpoints:
    GET    /api/digital_frames/walls               list walls
    POST   /api/digital_frames/walls               create a wall ({name, placements})
    POST   /api/digital_frames/walls/{wall_id}     update a wall ({name, placements})
    DELETE /api/digital_frames/walls/{wall_id}     delete a wall
    POST   /api/digital_frames/walls/{wall_id}/wallpaper   save/send a wallpaper scene
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_wall_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_walls")
    if manager is None:
        raise RuntimeError("Wall manager not initialised")
    return manager


def _parse_wall_body(body: Any) -> tuple[str | None, dict, list | None]:
    # body is whatever request.json() decoded -- could be a list, number, or
    # string for a syntactically-valid but wrongly-shaped request.
    if not isinstance(body, dict):
        return None, {}, None
    name = body.get("name")
    placements = body.get("placements")
    if not isinstance(placements, dict):
        placements = {}
    # None (absent) means "leave stored tombstones unchanged"; a list
    # replaces them -- see WallManager.async_save_wall.
    excluded = body.get("excluded")
    if excluded is not None and not isinstance(excluded, list):
        excluded = None
    return name, placements, excluded


class DigitalFramesWallsView(HomeAssistantView):
    """List (GET) or create (POST) walls."""

    url = "/api/digital_frames/walls"
    name = "api:digital_frames:walls"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)
        walls = await manager.async_list_walls()
        return self.json({"walls": walls})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, placements, excluded = _parse_wall_body(body)

        from .walls import WallError  # noqa: PLC0415

        try:
            wall = await manager.async_save_wall(name, placements, excluded=excluded)
        except WallError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to create wall: %s", err)
            return self.json_message(f"Failed to create wall: {err}", status_code=500)

        return self.json({"success": True, "wall": wall})


class DigitalFramesWallView(HomeAssistantView):
    """Update (POST) or delete (DELETE) a single wall."""

    url = "/api/digital_frames/walls/{wall_id}"
    name = "api:digital_frames:walls:one"
    requires_auth = True

    async def post(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name, placements, excluded = _parse_wall_body(body)

        from .walls import WallError  # noqa: PLC0415

        try:
            wall = await manager.async_save_wall(
                name, placements, wall_id=wall_id, excluded=excluded
            )
        except WallError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to update wall '%s': %s", wall_id, err)
            return self.json_message(f"Failed to update wall: {err}", status_code=500)

        return self.json({"success": True, "wall": wall})

    async def delete(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_wall_manager(hass)

        from .walls import WallError  # noqa: PLC0415

        try:
            await manager.async_delete_wall(wall_id)
        except WallError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete wall '%s': %s", wall_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})


class DigitalFramesWallWallpaperView(HomeAssistantView):
    """Save (as a scene) and/or send a wallpaper: one library image placed
    on the wall's canvas at an explicit, independent rect, sliced into
    each frame's own crop by wherever that frame currently sits (see
    wall_geometry.compute_wallpaper_crop_boxes). A "wallpaper" is not a
    separate entity -- it's an ordinary Scene whose mappings are all
    `image_crop` entries sharing this image_id, plus a `wallpaper` field
    recording the image's rect purely so the editor can restore it later
    (see Scene.wallpaper's docstring)."""

    url = "/api/digital_frames/walls/{wall_id}/wallpaper"
    name = "api:digital_frames:walls:wallpaper"
    requires_auth = True

    async def post(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        wall_mgr = _get_wall_manager(hass)

        wall = await wall_mgr.async_get_wall(wall_id)
        if wall is None:
            return self.json_message(f"Wall '{wall_id}' not found", status_code=404)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        image_id = body.get("image_id")
        if not image_id:
            return self.json_message("image_id is required", status_code=400)

        image_rect = body.get("image_rect")
        if not isinstance(image_rect, dict):
            return self.json_message("image_rect ({x, y, width, height}) is required", status_code=400)

        save_scene = body.get("save_scene", False)
        if isinstance(save_scene, str):
            save_scene = save_scene.lower() in ("true", "1", "yes")

        # Whether to actually push wire bytes to the physical frames right
        # now. Defaults True so a bare "send" call does what it says;
        # the wallpaper editor's "Save as Scene" action sets this False so
        # building/previewing a scene never touches hardware.
        push_now = body.get("push_now", True)
        if isinstance(push_now, str):
            push_now = push_now.lower() in ("true", "1", "yes")

        scene_name = (body.get("scene_name") or f"{wall.name} Wallpaper").strip()
        # When editing a previously-saved wallpaper scene, the caller passes
        # its id back so this save updates it in place -- without this,
        # async_save_scene(scene_id=None) treats every save as "create new"
        # and rejects a name that already belongs to a different scene_id.
        existing_scene_id = body.get("scene_id") or None

        member_entry_ids = body.get("member_entry_ids")
        if not isinstance(member_entry_ids, list):
            member_entry_ids = None

        lib_mgr = hass.data.get(DOMAIN, {}).get("_library")
        if lib_mgr is None:
            return self.json_message("Library manager not initialised", status_code=500)
        try:
            master_bytes, _content_type = await lib_mgr.async_get_original(image_id)
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Failed to read image '{image_id}': {err}", status_code=400)

        from .wall_geometry import WallGeometryError, compute_wallpaper_crop_boxes  # noqa: PLC0415

        try:
            crop_boxes = compute_wallpaper_crop_boxes(hass, wall, image_rect, member_entry_ids)
        except WallGeometryError as err:
            return self.json_message(str(err), status_code=400)

        from .helpers import render_spec_for_hass_entry  # noqa: PLC0415
        from .panel_codec import (  # noqa: PLC0415
            encode_for_panel_with_preview,
            panel_codec_for_entry,
        )

        scene_mappings: dict[str, Any] = {}
        results: list[dict[str, Any]] = []

        for entry_id, boxes in crop_boxes.items():
            if boxes is None:
                # No overlap between this frame and the image rect -- it
                # isn't part of this wallpaper (see compute_wallpaper_crop_
                # boxes's docstring); skip it rather than send/store a
                # degenerate crop.
                continue
            crop_box = boxes["crop_box"]
            dest_box = boxes["dest_box"]

            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                continue

            sent = False
            send_error: str | None = None
            if push_now:
                try:
                    try:
                        codec_id = panel_codec_for_entry(entry).id
                    except Exception:  # noqa: BLE001
                        codec_id = None

                    spec = render_spec_for_hass_entry(hass, entry)
                    wire_bytes, preview_png = encode_for_panel_with_preview(
                        source_bytes=master_bytes,
                        width=spec.width,
                        height=spec.height,
                        rotation=spec.rotation,
                        locked=spec.locked,
                        codec_id=codec_id,
                        crop_box=crop_box,
                        dest_box=dest_box,
                    )

                    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
                    if coordinator is not None and hasattr(coordinator, "async_send_image_or_queue"):
                        # image_id deliberately omitted: this frame is
                        # showing a *crop* of image_id, not the whole image,
                        # and async_set_last_image's contract is to pass
                        # exactly one of image_id/thumbnail (the other is
                        # cleared) -- passing the shared background's
                        # image_id here previously made every frame on the
                        # wall's tile thumbnail resolve to that one shared
                        # (uncropped) image instead of each frame's own
                        # correctly-cropped preview_png, even though the
                        # actual wire_bytes sent to each panel were already
                        # correct.
                        await coordinator.async_send_image_or_queue(
                            wire_bytes,
                            thumbnail=preview_png,
                        )
                    sent = True
                except Exception as err:  # noqa: BLE001
                    # One frame's encode/send failure (a bad crop, an
                    # unreachable coordinator, ...) must not abort every
                    # other frame's delivery -- each is independent, same as
                    # scenes.py's async_send_mappings.
                    send_error = str(err)
                    _LOGGER.error(
                        "Wallpaper send failed for frame %s: %s", entry_id, err
                    )

            result_entry: dict[str, Any] = {
                "entry_id": entry_id,
                "crop_box": crop_box,
                "dest_box": dest_box,
                "sent": sent,
            }
            if send_error:
                result_entry["message"] = send_error
            results.append(result_entry)

            scene_mappings[entry_id] = {
                "type": "image_crop",
                "image_id": image_id,
                "crop_box": list(crop_box),
                "dest_box": list(dest_box),
            }

        # Save Scene if requested
        scene_id: str | None = None
        scene_save_error: str | None = None
        if save_scene and scene_mappings:
            scene_mgr = hass.data.get(DOMAIN, {}).get("_scenes")
            if scene_mgr is not None:
                try:
                    scene_record = await scene_mgr.async_save_scene(
                        name=scene_name,
                        mappings=scene_mappings,
                        scene_id=existing_scene_id,
                        album="Wallpapers",
                        wallpaper={"image_id": image_id, **image_rect},
                    )
                    scene_id = scene_record.get("scene_id")
                except Exception as err:  # noqa: BLE001
                    # Surfaced to the caller (not just logged) -- silently
                    # swallowing this left the wallpaper editor's "Save as
                    # Scene" reporting success even when e.g. the scene
                    # being edited had been deleted elsewhere since it was
                    # loaded, or its name collided with an unrelated scene.
                    scene_save_error = str(err)
                    _LOGGER.warning("Failed to save wallpaper scene: %s", err)

        failed = [r for r in results if push_now and not r.get("sent")]

        response: dict[str, Any] = {
            "success": True,
            "wall_id": wall_id,
            "scene_id": scene_id,
            "frames_updated": len(results),
            "crop_boxes": crop_boxes,
            "results": results,
            "frames_failed": len(failed),
        }
        if scene_save_error:
            response["scene_save_error"] = scene_save_error
        return self.json(response)

