"""Unit tests for AI prompt injection and soft fallback (ai_enhancer.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.digital_frames.ai_enhancer import (
    SPECTRA6_EINK_PROMPT_DIRECTIVE,
    STYLES,
    async_generate_ai_enhanced_image,
    build_ai_prompt,
    has_ai_image_service,
)


def test_styles_tuple_has_eight_styles():
    assert len(STYLES) == 8
    assert "plain" in STYLES
    assert "ad_50s" in STYLES
    assert "movie_poster" in STYLES
    assert "neon_noir" in STYLES
    assert "chalkboard" in STYLES
    assert "gothic_gold" in STYLES
    assert "pop_art" in STYLES
    assert "nature_zen" in STYLES


def test_build_ai_prompt_contains_eink_directive_and_typography_mandate():
    prompt = build_ai_prompt("I think, therefore I am.", attribution="Descartes", style="movie_poster")
    assert "I think, therefore I am. — Descartes" in prompt
    assert "Bebas Neue" in prompt
    assert SPECTRA6_EINK_PROMPT_DIRECTIVE in prompt
    assert "NO people, NO physical furniture or desks" in prompt


def test_build_ai_prompt_handles_all_styles():
    for style in STYLES:
        prompt = build_ai_prompt("Test Message", style=style)
        assert "Test Message" in prompt
        assert SPECTRA6_EINK_PROMPT_DIRECTIVE in prompt


def test_has_ai_image_service_returns_false_when_missing(hass):
    assert has_ai_image_service(hass) is False


def test_has_ai_image_service_returns_true_when_present(hass):
    hass.services.async_register("ai_task", "generate_image", AsyncMock())
    assert has_ai_image_service(hass) is True


@pytest.mark.asyncio
async def test_async_generate_ai_enhanced_image_fallback_when_no_service(hass):
    result = await async_generate_ai_enhanced_image(
        hass, "Hello World", style="neon_noir"
    )
    assert result is None
