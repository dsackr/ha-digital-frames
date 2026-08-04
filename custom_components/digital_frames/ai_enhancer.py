"""AI Prompt Injection & Enhancement for Live Content and Messages.

Provides AI prompt decorators and runtime detection for Home Assistant's
AI Image Generation services (e.g. ai_task / image_generator). Designed
with a Soft AI Fallback pattern: if no AI integration is present or if an
AI API call fails, execution falls back silently to the local PIL canvas engine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# The 8 supported visual styles for live content & messages
STYLES: tuple[str, ...] = (
    "plain",
    "ad_50s",
    "movie_poster",
    "neon_noir",
    "chalkboard",
    "gothic_gold",
    "pop_art",
    "nature_zen",
)

# E-Ink Spectra 6 palette directive appended to all AI prompt injections
SPECTRA6_EINK_PROMPT_DIRECTIVE: str = (
    "Color palette specifically optimized for 6-color E-Ink displays (Spectra 6): "
    "Use bold, saturated, high-contrast primary color blocking with pure deep black, "
    "crisp white, vibrant cardinal red, bright sunflower yellow, deep royal blue, "
    "and rich emerald green. Sharp vector graphic poster style with heavy outlines "
    "and maximum text contrast against solid background fills. ABSOLUTELY NO subtle "
    "grey gradients, pastel washouts, low-contrast drop shadows, tiny illegible text, "
    "or fine photorealistic skin-tone dithering."
)

_STYLE_TEMPLATES: dict[str, str] = {
    "plain": (
        "A high-impact graphic design typography poster. The text '{text_content}' "
        "is rendered in large, bold, highly legible, high-contrast lettering in the center of the frame. "
        "Clean monochrome gallery wall art style with elegant typography."
    ),
    "ad_50s": (
        "A vintage 1950s retro mid-century diner advertisement sign displaying the text '{text_content}'. "
        "Bold vintage block typography framed by yellow and red marquee banners and double accent borders. "
        "Authentic 1950s pop art commercial signboard style."
    ),
    "movie_poster": (
        "A dramatic Hollywood movie title poster. The text '{text_content}' "
        "is rendered in massive, bold all-caps condensed typography (Bebas Neue style) in the center of the frame. "
        "Deep cinematic black canvas with subtle golden spotlight accents and a cardinal red rule divider."
    ),
    "neon_noir": (
        "A striking cyberpunk neon light sign mounted on a dark brick wall. The text '{text_content}' "
        "glows in vibrant electric neon tube typography. High contrast, ultra-legible glowing letterforms."
    ),
    "chalkboard": (
        "A rustic cafe chalkboard poster. The text '{text_content}' is hand-lettered in crisp white and yellow "
        "chalk artwork centered on a dark slate board with decorative chalk scrollwork borders."
    ),
    "gothic_gold": (
        "An ornate illuminated manuscript graphic poster. The text '{text_content}' is rendered in opulent "
        "metallic gold foil typography centered on a deep royal blue background with gold accent filigree."
    ),
    "pop_art": (
        "A bold 1960s comic book graphic design poster. The text '{text_content}' is set in heavy black-outlined "
        "pop-art typography over a yellow and cyan halftone dot pattern background. High impact visual art."
    ),
    "nature_zen": (
        "A minimalist botanical graphic art poster. The text '{text_content}' is set in clean elegant typography "
        "inside a sharp geometric frame, surrounded by subtle emerald green leaf and nature silhouettes."
    ),
}


def build_ai_prompt(
    text: str,
    attribution: str | None = None,
    style: str = "plain",
    content_mode: str = "message",
) -> str:
    """Construct an e-ink-optimized AI image generation prompt for a quote/message.

    Guarantees that the message text itself is the centerpiece typography subject,
    avoiding literal scene depictions (e.g. a person at a desk with speech bubbles).
    """
    style = style if style in _STYLE_TEMPLATES else "plain"
    template = _STYLE_TEMPLATES[style]

    if attribution and attribution.strip():
        text_content = f"{text.strip()} — {attribution.strip()}"
    else:
        text_content = text.strip()

    base_prompt = template.format(text_content=text_content)

    return (
        f"{base_prompt} {SPECTRA6_EINK_PROMPT_DIRECTIVE} "
        "NO people, NO physical furniture or desks, NO tiny speech bubbles, "
        "NO illegible text. Focus strictly on readable central graphic typography."
    )


def has_ai_image_service(hass: "HomeAssistant") -> bool:
    """Return True if Home Assistant has an active AI image generation service."""
    return (
        hass.services.has_service("ai_task", "generate_image")
        or hass.services.has_service("image_generator", "generate_image")
        or hass.services.has_service("openai", "generate_image")
    )


async def async_generate_ai_enhanced_image(
    hass: "HomeAssistant",
    text: str,
    attribution: str | None = None,
    style: str = "plain",
    content_mode: str = "message",
    ai_task_entity_id: str | None = None,
) -> bytes | None:
    """Attempt AI image generation using Home Assistant's AI services.

    Returns raw RGB image bytes if successful, or None if AI is unavailable
    or fails (triggering soft fallback to the local PIL engine).
    """
    if not has_ai_image_service(hass):
        _LOGGER.debug("No AI image service available; falling back to local PIL renderer")
        return None

    prompt = build_ai_prompt(text, attribution, style, content_mode)

    try:
        if hass.services.has_service("ai_task", "generate_image"):
            if not ai_task_entity_id:
                # Find first supported entity
                from . import _AI_TASK_GENERATE_IMAGE_FEATURE, _find_ai_task_image_entity  # noqa: PLC0415
                try:
                    ai_task_entity_id = _find_ai_task_image_entity(hass)
                except Exception:  # noqa: BLE001
                    return None

            gen_result = await hass.services.async_call(
                "ai_task",
                "generate_image",
                {
                    "entity_id": ai_task_entity_id,
                    "task_name": "Digital Frames AI Visual Enhancement",
                    "instructions": prompt,
                },
                blocking=True,
                return_response=True,
            )

            if isinstance(gen_result, dict) and "media_source_id" in gen_result:
                from homeassistant.components.media_source import async_resolve_media  # noqa: PLC0415
                from . import _fetch_media_bytes  # noqa: PLC0415

                media_item = await async_resolve_media(hass, gen_result["media_source_id"], None)
                return await _fetch_media_bytes(hass, media_item.url)

    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("AI image generation failed (%s); falling back to local PIL renderer", err)
        return None

    return None
