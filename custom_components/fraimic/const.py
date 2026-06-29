"""Constants for the Fraimic integration."""

from homeassistant.const import Platform

DOMAIN = "fraimic"

# Polling interval in seconds (5 minutes default)
DEFAULT_SCAN_INTERVAL = 300

DEFAULT_PORT = 80

# API endpoints
API_INFO = "/api/info"
API_RESTART = "/api/restart"
API_SLEEP = "/api/sleep"
API_REFRESH = "/api/refresh"
API_IMAGE = "/api/image"

# Config entry keys
CONF_HOST = "host"
CONF_NAME = "name"
CONF_WIDTH = "width"
CONF_HEIGHT = "height"
CONF_MODE = "mode"

# Frame display modes
MODE_MANUAL = "manual"
MODE_AGENDA = "agenda"
MODE_ROTATION = "rotation"

# Frame resolutions: name → (width_px, height_px)
# TODO: Validate these pixel dimensions against real hardware — they are
# placeholder estimates and may not match the actual Fraimic device output.
FRAME_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "14x18": (1200, 1600),
    "24x36": (1600, 2400),
}

# HA platforms this integration provides
PLATFORMS = [Platform.SENSOR]
