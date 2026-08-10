"""HTTP API views for Fraimic walls.

Endpoints:
    GET    /api/digital_frames/walls               list walls
    POST   /api/digital_frames/walls               create a wall ({name, placements})
    POST   /api/digital_frames/walls/{wall_id}     update a wall ({name, placements})
    DELETE /api/digital_frames/walls/{wall_id}     delete a wall
    GET    /api/digital_frames/walls/{wall_id}/geometry   read-only aggregate canvas size + crop boxes
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


class DigitalFramesWallGeometryView(HomeAssistantView):
    """GET a wall's aggregate spanned-canvas size + per-frame crop boxes,
    with no generation or send side effects -- the wallpaper editor uses
    this purely to size a "generate for this wall" request and to preview
    what a save/send would compute, before either happens."""

    url = "/api/digital_frames/walls/{wall_id}/geometry"
    name = "api:digital_frames:walls:geometry"
    requires_auth = True

    async def get(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        wall_mgr = _get_wall_manager(hass)

        wall = await wall_mgr.async_get_wall(wall_id)
        if wall is None:
            return self.json_message(f"Wall '{wall_id}' not found", status_code=404)

        member_entry_ids = request.query.get("member_entry_ids")
        if member_entry_ids:
            member_entry_ids = [eid for eid in member_entry_ids.split(",") if eid]
        else:
            member_entry_ids = None

        preserve_bezel_gaps = request.query.get("preserve_bezel_gaps", "true")
        preserve_bezel_gaps = preserve_bezel_gaps.lower() in ("true", "1", "yes")

        from .wall_geometry import WallGeometryError, compute_2d_wall_canvas_geometry  # noqa: PLC0415

        try:
            geometry = compute_2d_wall_canvas_geometry(
                hass, wall, member_entry_ids, preserve_bezel_gaps=preserve_bezel_gaps
            )
        except WallGeometryError as err:
            return self.json_message(str(err), status_code=400)

        return self.json({
            "success": True,
            "wall_id": wall_id,
            "canvas_width": geometry.canvas_width,
            "canvas_height": geometry.canvas_height,
            "crop_boxes": geometry.crop_boxes,
        })


class DigitalFramesWallSpanImageView(HomeAssistantView):
    """Span an image (AI generated, library photo, or upload) across a 2D wall layout."""

    url = "/api/digital_frames/walls/{wall_id}/span_image"
    name = "api:digital_frames:walls:span_image"
    requires_auth = True

    async def post(self, request: web.Request, wall_id: str) -> web.Response:
        hass = request.app["hass"]
        wall_mgr = _get_wall_manager(hass)

        wall = await wall_mgr.async_get_wall(wall_id)
        if wall is None:
            return self.json_message(f"Wall '{wall_id}' not found", status_code=404)

        # Parse request body (JSON or multipart)
        content_type = request.headers.get("Content-Type", "")
        file_bytes: bytes | None = None
        if "multipart/form-data" in content_type:
            reader = await request.multipart()
            body: dict[str, Any] = {}
            async for part in reader:
                if part.name == "file":
                    file_bytes = await part.read()
                else:
                    val = await part.text()
                    body[part.name] = val
        else:
            try:
                body = await request.json()
            except Exception as err:  # noqa: BLE001
                return self.json_message(f"Invalid JSON body: {err}", status_code=400)
            if not isinstance(body, dict):
                return self.json_message("Request body must be an object", status_code=400)

        source_type = body.get("source_type") or "ai"
        prompt = (body.get("prompt") or "").strip()
        image_id = body.get("image_id")
        preserve_bezel_gaps = body.get("preserve_bezel_gaps", True)
        if isinstance(preserve_bezel_gaps, str):
            preserve_bezel_gaps = preserve_bezel_gaps.lower() in ("true", "1", "yes")

        save_scene = body.get("save_scene", False)
        if isinstance(save_scene, str):
            save_scene = save_scene.lower() in ("true", "1", "yes")

        # Whether to actually push wire bytes to the physical frames right
        # now. Defaults True so existing "Send to Frames" callers (and the
        # old span_image behavior) are unaffected; the wallpaper editor's
        # "Save as Scene" action sets this False so building/previewing a
        # scene never touches hardware.
        push_now = body.get("push_now", True)
        if isinstance(push_now, str):
            push_now = push_now.lower() in ("true", "1", "yes")

        scene_name = (body.get("scene_name") or f"{wall.name} Spanned").strip()
        # When editing a previously-saved wallpaper scene, the caller passes
        # its id back so this save updates it in place -- without this,
        # async_save_scene(scene_id=None) treats every save as "create new"
        # and rejects a name that already belongs to a different scene_id.
        existing_scene_id = body.get("scene_id") or None

        save_to_library = body.get("save_to_library", False)
        if isinstance(save_to_library, str):
            save_to_library = save_to_library.lower() in ("true", "1", "yes")

        member_entry_ids = body.get("member_entry_ids")
        if isinstance(member_entry_ids, str):
            import json as _json  # noqa: PLC0415
            try:
                member_entry_ids = _json.loads(member_entry_ids)
            except Exception:  # noqa: BLE001
                member_entry_ids = None

        from .wall_geometry import WallGeometryError, compute_2d_wall_canvas_geometry  # noqa: PLC0415

        try:
            geometry = compute_2d_wall_canvas_geometry(
                hass, wall, member_entry_ids, preserve_bezel_gaps=preserve_bezel_gaps
            )
        except WallGeometryError as err:
            return self.json_message(str(err), status_code=400)

        # Retrieve or generate master image bytes
        master_bytes: bytes | None = None

        if source_type == "upload":
            if not file_bytes:
                return self.json_message("No uploaded file provided", status_code=400)
            master_bytes = file_bytes

        elif source_type == "library":
            if not image_id:
                return self.json_message("image_id is required for library source", status_code=400)
            lib_mgr = hass.data.get(DOMAIN, {}).get("_library")
            if lib_mgr is None:
                return self.json_message("Library manager not initialised", status_code=500)
            try:
                master_bytes, _content_type = await lib_mgr.async_get_original(image_id)
            except Exception as err:  # noqa: BLE001
                return self.json_message(f"Failed to read image '{image_id}': {err}", status_code=400)

        elif source_type == "ai":
            if not prompt:
                prompt = f"Abstract geometric gallery art for wall {wall.name}"

            # Try AI task generation if service is available
            from .ai_enhancer import has_ai_image_service  # noqa: PLC0415
            if has_ai_image_service(hass):
                try:
                    ai_task_entity_id = body.get("ai_task_entity_id")
                    if not ai_task_entity_id:
                        from . import _find_ai_task_image_entity  # noqa: PLC0415
                        ai_task_entity_id = _find_ai_task_image_entity(hass)

                    gen_result = await hass.services.async_call(
                        "ai_task",
                        "generate_image",
                        {
                            "entity_id": ai_task_entity_id,
                            "task_name": f"Digital Frames Spanned Wall Art - {wall.name}",
                            "instructions": prompt,
                        },
                        blocking=True,
                        return_response=True,
                    )
                    if isinstance(gen_result, dict) and "media_source_id" in gen_result:
                        from homeassistant.components.media_source import async_resolve_media  # noqa: PLC0415
                        from . import _fetch_media_bytes  # noqa: PLC0415
                        media_item = await async_resolve_media(hass, gen_result["media_source_id"], None)
                        master_bytes = await _fetch_media_bytes(hass, media_item.url)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("AI image generation failed for wall span (%s); generating PIL canvas", err)

            if master_bytes is None:
                # Fall back to high-res PIL artwork canvas
                master_bytes = await hass.async_add_executor_job(
                    _generate_pil_wall_span_image,
                    geometry.canvas_width,
                    geometry.canvas_height,
                    prompt,
                )

        else:
            return self.json_message(f"Invalid source_type: {source_type!r}", status_code=400)

        if not master_bytes:
            return self.json_message("Failed to produce master image for wall span", status_code=500)

        # Save master image to library if requested or if saving a scene --
        # unless it's already a library image (source_type "library"), in
        # which case that image_id IS the saved image; re-uploading it as a
        # new "wall_span_*.png" record every save would pile up duplicate
        # copies of the same background (e.g. every time an existing
        # wallpaper scene is re-opened and re-saved) instead of referencing
        # the one original -- exactly the duplicate-asset-per-save the
        # crop-based scene model exists to avoid.
        saved_image_id: str | None = image_id if source_type == "library" else None
        lib_mgr = hass.data.get(DOMAIN, {}).get("_library")
        if saved_image_id is None and (save_to_library or save_scene) and lib_mgr is not None:
            import uuid  # noqa: PLC0415
            filename = f"wall_span_{uuid.uuid4().hex[:8]}.png"
            try:
                record = await lib_mgr.async_upload(filename, master_bytes, ["Wall Spans"])
                saved_image_id = record.get("image_id") if isinstance(record, dict) else getattr(record, "image_id", None)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to save master image to library: %s", err)

        # Dispatch slices to frames
        from .helpers import render_spec_for_hass_entry  # noqa: PLC0415
        from .panel_codec import (  # noqa: PLC0415
            encode_for_panel_with_preview,
            panel_codec_for_entry,
        )

        scene_mappings: dict[str, Any] = {}
        results: list[dict[str, Any]] = []

        for entry_id, crop_box in geometry.crop_boxes.items():
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
                    )

                    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
                    if coordinator is not None and hasattr(coordinator, "async_send_image_or_queue"):
                        await coordinator.async_send_image_or_queue(
                            wire_bytes,
                            image_id=saved_image_id,
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
                        "Wall span send failed for frame %s: %s", entry_id, err
                    )

            result_entry: dict[str, Any] = {
                "entry_id": entry_id,
                "crop_box": crop_box,
                "sent": sent,
            }
            if send_error:
                result_entry["message"] = send_error
            results.append(result_entry)

            if saved_image_id:
                scene_mappings[entry_id] = {
                    "type": "image_crop",
                    "image_id": saved_image_id,
                    "crop_box": list(crop_box),
                }

        # Save Scene if requested
        scene_id: str | None = None
        scene_save_error: str | None = None
        if save_scene and saved_image_id and scene_mappings:
            scene_mgr = hass.data.get(DOMAIN, {}).get("_scenes")
            if scene_mgr is not None:
                try:
                    scene_record = await scene_mgr.async_save_scene(
                        name=scene_name,
                        mappings=scene_mappings,
                        scene_id=existing_scene_id,
                        album="Wall Spans",
                    )
                    scene_id = scene_record.get("scene_id")
                except Exception as err:  # noqa: BLE001
                    # Surfaced to the caller (not just logged) -- silently
                    # swallowing this left the wallpaper editor's "Save as
                    # Scene" reporting success even when e.g. the scene
                    # being edited had been deleted elsewhere since it was
                    # loaded, or its name collided with an unrelated scene.
                    scene_save_error = str(err)
                    _LOGGER.warning("Failed to save scene for wall span: %s", err)

        failed = [r for r in results if push_now and not r.get("sent")]

        response: dict[str, Any] = {
            "success": True,
            "wall_id": wall_id,
            "saved_image_id": saved_image_id,
            "scene_id": scene_id,
            "frames_updated": len(results),
            "crop_boxes": geometry.crop_boxes,
            "results": results,
            "frames_failed": len(failed),
        }
        if scene_save_error:
            response["scene_save_error"] = scene_save_error
        return self.json(response)


def _generate_pil_wall_span_image(width: int, height: int, prompt: str) -> bytes:
    """Generate a crisp, vibrant PIL graphic image for wall spanning fallback."""
    import io  # noqa: PLC0415
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    im = Image.new("RGB", (width, height), (18, 20, 28))
    draw = ImageDraw.Draw(im)

    # Draw smooth gradient backdrop
    for y in range(height):
        r = int(24 + (180 - 24) * (y / max(height, 1)))
        g = int(32 + (100 - 32) * (x_val := y / max(height, 1)))
        b = int(60 + (220 - 60) * x_val)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Decorative geometric accent shapes
    cx, cy = width // 2, height // 2
    r_max = min(width, height) // 3
    draw.ellipse([cx - r_max, cy - r_max, cx + r_max, cy + r_max], outline=(255, 215, 0), width=8)
    draw.ellipse([cx - r_max * 0.7, cy - r_max * 0.7, cx + r_max * 0.7, cy + r_max * 0.7], outline=(235, 64, 52), width=6)

    # Headline text banner
    title = f"SPANNED ART: {prompt[:30].upper()}"
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None

    draw.rectangle([cx - 300, cy - 25, cx + 300, cy + 25], fill=(0, 0, 0, 180), outline=(255, 255, 255), width=2)
    draw.text((cx, cy), title, fill=(255, 255, 255), font=font, anchor="mm")

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()

