"""Unit tests for xotd_renderer.py message styles rendering."""

import pytest
from custom_components.digital_frames.renderers.xotd.xotd_renderer import (
    render_message_image,
)
from custom_components.digital_frames.ai_enhancer import STYLES


def test_render_message_image_all_styles():
    for style in STYLES:
        img = render_message_image(800, 480, "Test quote or message", style=style)
        assert img.size == (800, 480)
        assert img.mode == "RGB"
