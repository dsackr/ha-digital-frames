# GitHub Issue: Virtual Wall Frame Hover Overlay & Options Flow Redesign

## Goal
Improve the usability, responsiveness, and layout of the virtual wall frame tiles and the configuration settings. Instead of a single gear icon in the footer that opens a dialog with miscellaneous actions, hovering over a frame on the virtual wall will display a translucent overlay divided into four functional corner quadrants. Additionally, the configuration options are reorganized to hide advanced parameters and integration-level actions under an expandable advanced settings section.

---

## 1. User Interface Specifications

### A. Virtual Wall Hover Overlay
* **Activation**: Appears on hover over any active `.wall-tile` on the virtual wall.
* **Appearance**: A translucent grey overlay (`rgba(15, 23, 42, 0.7)`) covering the entire tile.
* **Layout**: Split evenly into four quadrants using a CSS Grid:
  * **Top-Left (Image Selection)**: Uses a solid white picture SVG icon. Clicking it opens the Image Picker (identical to clicking the image/tile today).
  * **Top-Right (Remove Tile)**: Uses a solid white `✕` SVG icon. Clicking it removes the frame from the virtual wall and returns it to the palette (identical to clicking the small `✕` in the top right corner today).
  * **Bottom-Left (Frame Info)**: Uses a solid white Info SVG icon (`ℹ`). Clicking it opens the new **Frame Info Popup**.
  * **Bottom-Right (Configuration)**: Uses a solid white Gear SVG icon (`⚙`). Clicking it directly launches the **Configure options flow modal**.
* **Visual Polish**: Icons should be styled with a default opacity (e.g., `0.75`) that transitions to bright white (`1.0`) and slightly scales on hover to feel premium and alive.

### B. Frame Info Popup (Bottom-Left Action)
* **Replacement**: Replaces the old settings menu (gear icon popup) which contained "Save Name", "Configure", "Reload", "Remove", and "Close".
* **Content Displayed**:
  * **Frame Name**: Displayed at the top.
  * **IP Address**: The frame's hostname/IP (`frame.host`).
  * **Orientation**: The current orientation (`Portrait` or `Landscape`).
  * **Battery Percentage**: The current battery level read dynamically from the state machine (`this._hass.states[frame.entityId]`). If not available or not a number, show "N/A" (or "AC Powered" where appropriate).
* **Interactive Elements**:
  * **Name Input Field**: Editable text box populated with the frame's current title.
  * **Save Name Button**: Saves the renamed frame title.
  * **Close Button**: Closes the popup.
* **Excluded Elements**: The "Reload" (now "Reconnect Frame") and "Remove (from HA)" actions are moved out of this popup and into the Configure modal's Advanced section.

### C. Configure Screen / Options Flow Modal (Bottom-Right Action)
* **Options Schema Relabeling**:
  * The `resolution` (Physical Size) dropdown must be labeled **"Frame Type"**.
  * `rotate_portrait_180` is renamed to **"Flip Portrait Image"** (visible immediately).
  * `rotate_landscape_180` is renamed to **"Flip Landscape Image"** (visible immediately).
* **Advanced Settings Section**:
  * A clickable, clean text link **"▸ Advanced Settings"** that toggles to **"▾ Advanced Settings"** and expands when clicked.
  * Hides the following parameters under this section:
    * `scan_interval` (Update Interval)
    * `rotation_edge` (Rotated hanging edge)
  * Moves the following integration-level actions to the bottom of this section:
    * **"Reconnect Frame"** (formerly Reload): Triggers a connection/config entry reload.
    * **"Remove from HA"** (formerly Remove): Completely deletes the frame integration instance from Home Assistant after a confirmation prompt.

---

## 2. Technical Implementation Plan

### A. Translation Updates (`strings.json` & `translations/en.json`)
* Update option step translations:
  * `"resolution"`: `"Frame Type"`
  * `"rotate_portrait_180"`: `"Flip Portrait Image"`
  * `"rotate_landscape_180"`: `"Flip Landscape Image"`

### B. Dynamic Options Flow Customization (`digital-frames-panel.js`)
* In `_renderFlowStep`, intercept options flow step `init` rendering:
  * Separate fields into two groups: standard and advanced.
  * Standard fields: `resolution`, `rotate_portrait_180`, `rotate_landscape_180`.
  * Advanced fields: `scan_interval`, `rotation_edge`.
  * Wrap advanced fields in a toggleable container (`.advanced-settings-section`).
  * Inject the "Reconnect Frame" and "Remove from HA" actions within the expanded advanced settings container.

### C. Hover Overlay Implementation (`digital-frames-panel.js`)
* Create `#wall-tile-hover-overlay` elements inside each `.wall-tile`.
* Style with absolute positioning, `z-index`, translucent backdrop, grid layout, and custom white/grey SVG icons.
* Attach click event handlers that route to the respective image selection, remove tile, frame info, and configure options flow actions.

---

## 3. Key Product Flow (KPF) Updates
* **KPF 2 (Options Flow)**: Amend this entry to describe the new layout of the options flow (collapsible Advanced Settings section, Frame Type label, renamed flip checkboxes, and relocated Reconnect/Remove actions).
* **KPF 8 (Shared image library / Wall interactive actions)**: Update or add details describing the new hover overlay and the unified Frame Info popup.

---

## 4. Testing Requirements
* **Playwright Suite**: Expand `tests/panel/frame-manage.spec.js` to cover:
  * Hover overlay interaction (verifying layout, quadrant icons, and clicks).
  * Opening the new Frame Info popup and verifying it displays the editable Name, IP, Orientation, and Battery percentage.
  * Testing renaming from the new Frame Info popup.
  * Testing options flow expansion (Advanced Settings toggle).
  * Testing the "Reconnect Frame" and "Remove from HA" buttons nested inside Advanced Settings.
