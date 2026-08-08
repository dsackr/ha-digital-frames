"""Art Factory HTTP Views: Standalone AI Prompt-to-Image Generation (KPF 37).

Provides a dedicated AI art generation hub. Uses Home Assistant's native
`ai_task` / `image_generator` service when present in the user's HA instance,
and provides a zero-config fallback (Pollinations.ai public generator or PIL
canvas) when no HA AI integration is configured.
"""

from __future__ import annotations

import io
import logging
import urllib.parse
import uuid
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .ai_enhancer import (
    SPECTRA6_EINK_PROMPT_DIRECTIVE,
    _STYLE_TEMPLATES,
    has_ai_image_service,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

AI_ART_ALBUM = "AI Art"


def _find_ai_task_entity(hass) -> str | None:
    """Find first supported ai_task image generation entity."""
    try:
        from . import _find_ai_task_image_entity  # noqa: PLC0415
        return _find_ai_task_image_entity(hass)
    except Exception:  # noqa: BLE001
        return None


async def async_generate_ai_art_image(
    hass,
    prompt: str,
    style: str = "plain",
    width: int = 1024,
    height: int = 1024,
    ai_task_entity_id: str | None = None,
) -> tuple[bytes, str]:
    """Generate image bytes from prompt.

    Returns (image_bytes, engine_used).
    Primary path: HA `ai_task` service call.
    Fallback path: External public AI image generator (Pollinations.ai).
    """
    clean_prompt = prompt.strip()
    style_desc = _STYLE_TEMPLATES.get(style, "")
    if style_desc and "{text_content}" in style_desc:
        full_prompt = style_desc.format(text_content=clean_prompt)
    elif style_desc:
        full_prompt = f"{clean_prompt}. {style_desc}"
    else:
        full_prompt = clean_prompt

    # Append E-ink color directive for maximum frame visual impact
    full_prompt += f" {SPECTRA6_EINK_PROMPT_DIRECTIVE}"

    # 1. Primary path: HA native ai_task service
    if has_ai_image_service(hass):
        entity_id = ai_task_entity_id or _find_ai_task_entity(hass)
        if entity_id:
            try:
                _LOGGER.info("Generating AI art via HA ai_task entity '%s'", entity_id)
                gen_result = await hass.services.async_call(
                    "ai_task",
                    "generate_image",
                    {
                        "entity_id": entity_id,
                        "task_name": "Digital Frames Art Factory",
                        "instructions": full_prompt,
                    },
                    blocking=True,
                    return_response=True,
                )

                if isinstance(gen_result, dict) and "media_source_id" in gen_result:
                    from homeassistant.components.media_source import (  # noqa: PLC0415
                        async_resolve_media,
                    )
                    from . import _fetch_media_bytes  # noqa: PLC0415

                    media_item = await async_resolve_media(
                        hass, gen_result["media_source_id"], None
                    )
                    raw_bytes = await _fetch_media_bytes(hass, media_item.url)
                    if raw_bytes and len(raw_bytes) > 0:
                        return raw_bytes, f"Home Assistant AI ({entity_id})"
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("HA ai_task service failed (%s); switching to public AI generator", err)

    # 2. Secondary fallback path: Public AI Image Generator (Pollinations.ai)
    try:
        encoded_prompt = urllib.parse.quote(full_prompt)
        seed = uuid.uuid4().int % 1000000
        pollinations_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&seed={seed}&nologo=true"
        )
        _LOGGER.info("Generating AI art via Public AI Engine (Pollinations.ai)")

        from . import _fetch_media_bytes  # noqa: PLC0415
        img_bytes = await _fetch_media_bytes(hass, pollinations_url)
        if img_bytes and len(img_bytes) > 100:
            return img_bytes, "Public AI Engine (Pollinations.ai)"
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Public AI engine generation failed (%s); generating PIL poster", err)

    # 3. Last fallback: Local PIL Poster fallback canvas
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size=36)
    except IOError:
        font = ImageFont.load_default()

    header = "🎨 Art Factory"
    draw.text((40, 40), header, fill=(244, 63, 94), font=font)
    draw.text((40, 100), f"Prompt: {clean_prompt[:60]}...", fill=(226, 232, 240), font=font)
    draw.text((40, 160), "Style: " + style.upper(), fill=(56, 189, 248), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "Local PIL Engine"


class DigitalFramesArtFactoryStatusView(HomeAssistantView):
    """GET /api/digital_frames/art_factory/status -> Report AI capabilities."""

    url = "/api/digital_frames/art_factory/status"
    name = "api:digital_frames:art_factory:status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        has_ha_ai = has_ai_image_service(hass)
        ai_entity_id = _find_ai_task_entity(hass) if has_ha_ai else None

        return self.json(
            {
                "success": True,
                "has_ha_ai": has_ha_ai,
                "ai_entity_id": ai_entity_id,
                "active_engine": (
                    f"Home Assistant AI Task ({ai_entity_id})"
                    if has_ha_ai and ai_entity_id
                    else "Public AI Generator (Pollinations.ai)"
                ),
            }
        )


class DigitalFramesArtFactoryGenerateView(HomeAssistantView):
    """POST /api/digital_frames/art_factory/generate -> Generate AI Art from prompt."""

    url = "/api/digital_frames/art_factory/generate"
    name = "api:digital_frames:art_factory:generate"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return self.json({"success": False, "message": "Invalid JSON body"}, status_code=400)

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return self.json({"success": False, "message": "Prompt can't be empty"}, status_code=400)

        style = body.get("style", "plain")
        width = int(body.get("width", 1024))
        height = int(body.get("height", 1024))
        save_to_library = bool(body.get("save_to_library", True))
        send_to_entry_id = body.get("send_to_entry_id")

        try:
            img_bytes, engine_used = await async_generate_ai_art_image(
                hass, prompt, style=style, width=width, height=height
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Art Factory generation failed: %s", err)
            return self.json({"success": False, "message": f"Generation failed: {err}"}, status_code=500)

        saved_image_id: str | None = None
        lib_mgr = hass.data.get(DOMAIN, {}).get("_library")

        if save_to_library and lib_mgr is not None:
            filename = f"art_factory_{uuid.uuid4().hex[:8]}.png"
            try:
                record = await lib_mgr.async_upload(filename, img_bytes, [AI_ART_ALBUM])
                saved_image_id = (
                    record.get("image_id")
                    if isinstance(record, dict)
                    else getattr(record, "image_id", None)
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to save generated art to library: %s", err)

        # Optionally send directly to a targeted frame if requested
        if send_to_entry_id:
            coordinator = hass.data.get(DOMAIN, {}).get(send_to_entry_id)
            entry = hass.config_entries.async_get_entry(send_to_entry_id)
            if coordinator is not None and entry is not None:
                from .helpers import render_spec_for_hass_entry  # noqa: PLC0415
                from .panel_codec import (  # noqa: PLC0415
                    encode_for_panel_with_preview,
                    panel_codec_for_entry,
                )

                try:
                    codec_id = panel_codec_for_entry(entry).id
                except Exception:  # noqa: BLE001
                    codec_id = None

                spec = render_spec_for_hass_entry(hass, entry)
                wire_bytes, preview_png = encode_for_panel_with_preview(
                    source_bytes=img_bytes,
                    width=spec.width,
                    height=spec.height,
                    rotation=spec.rotation,
                    locked=spec.locked,
                    codec_id=codec_id,
                )
                await coordinator.async_send_image_or_queue(
                    wire_bytes=wire_bytes,
                    preview_png=preview_png,
                    image_id=saved_image_id,
                )

        import base64  # noqa: PLC0415
        preview_b64 = f"data:image/png;base64,{base64.b64encode(img_bytes).decode('ascii')}"

        return self.json(
            {
                "success": True,
                "prompt": prompt,
                "style": style,
                "engine_used": engine_used,
                "image_id": saved_image_id,
                "preview_url": preview_b64,
            }
        )
