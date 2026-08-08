# Digital Frames REST API Reference

The **Digital Frames** Home Assistant custom component exposes a comprehensive set of REST HTTP API endpoints under `/api/digital_frames/*`. These endpoints power the frontend sidebar panel, Lovelace cards, and external automation scripts.

An OpenAPI 3.0 specification file is available at [`docs/openapi.yaml`](file:///Users/skippy/repos/ha-digital-frames/docs/openapi.yaml).

---

## Authentication & Headers

All requests (unless specified as public unauthenticated endpoints) require Home Assistant authentication via a Long-Lived Access Token.

### Request Headers

```http
Authorization: Bearer <YOUR_HA_LONG_LIVED_ACCESS_TOKEN>
Content-Type: application/json
```

For file uploads (e.g., direct image sends or library uploads), use `multipart/form-data`.

---

## Unauthenticated Endpoints

Some endpoints are intentionally unauthenticated to allow local hardware frames (such as Samsung Frame TVs or e-ink frames in pull mode) to fetch their image binary payload:

- `GET /api/digital_frames/pull/{token}/image.bin`
- `GET /api/digital_frames/samsung/{token}/content.png`
- `GET /api/digital_frames/library/oauth/google/callback`

---

## Endpoint Catalog

### 1. Frame Management & Discovery

#### `GET /api/digital_frames/openapi.json`
Returns the machine-readable OpenAPI 3.0 specification for automated API discovery by AI systems, API gateways, and developer tools (Swagger UI, Postman, Insomnia).

- **Headers**: Requires `Authorization: Bearer <TOKEN>`
- **Response `200 OK`**: `application/json` object containing full OpenAPI 3.0 specification.

#### `GET /api/digital_frames/frames`
Retrieves a list of all configured digital frames, including their entity status, screen dimensions, rotation, battery level, online/offline status, active thumbnail, and queued image delivery state.

- **Response `200 OK`**:
  ```json
  [
    {
      "entry_id": "8f7e6d5c...",
      "name": "Living Room Frame",
      "model": "Fraimic 13.3",
      "width": 1600,
      "height": 1200,
      "rotation": 0,
      "online": true,
      "last_image_id": "img_12345",
      "queued": false
    }
  ]
  ```

#### `GET /api/digital_frames/frame/{entry_id}/thumbnail`
Returns the raw binary JPEG image thumbnail preview currently staged or active on the specified frame.

- **Path Parameters**: `entry_id` (string) — Home Assistant config entry ID.
- **Response `200 OK`**: `image/jpeg` binary data.

#### `GET /api/digital_frames/frame_status`
Retrieves detailed status metrics for all frames registered with the integration.

#### `POST /api/digital_frames/frame/reload`
Forces an immediate reload/refresh of frame entities and state coordinators.

#### `POST /api/digital_frames/frame/poll_orientation`
Triggers an immediate hardware orientation/accelerometer check for frames that support hardware orientation sensing.

#### `GET /api/digital_frames/onboarding`
Returns onboarding and setup wizard status.

#### `POST /api/digital_frames/onboarding`
Updates or dismisses onboarding configuration states.

#### `POST /api/digital_frames/discovery/scan`
Triggers a local subnet scan to discover supported e-ink or smart frame hardware.

---

### 2. Direct Image Sending

#### `POST /api/digital_frames/send_image`
Converts and sends/queues an image directly to a targeted frame without storing it in the persistent photo library.

- **Content-Type**: `multipart/form-data`
- **Form Fields**:
  - `entity_id` (string, optional) — Target frame entity ID (e.g. `sensor.living_room_frame_status`).
  - `entry_id` (string, optional) — Target frame config entry ID. *(One of `entity_id` or `entry_id` required)*.
  - `image` (file, required) — The image file binary to send.
- **Response `200 OK`**:
  ```json
  {
    "success": true,
    "queued": false,
    "bytes_sent": 245890
  }
  ```

#### `GET /api/digital_frames/pull/{token}/image.bin` *(Unauthenticated)*
Serves the rendered binary image payload for pull-mode frames.

#### `GET /api/digital_frames/samsung/{token}/content.png` *(Unauthenticated)*
Serves the current PNG content payload for Samsung Frame devices.

---

### 3. Library & Media Management

#### `GET /api/digital_frames/library/list`
Lists stored library images with optional filtering and sorting.

- **Query Parameters**:
  - `album` (string, optional) — Filter images by album name.
  - `tag` (string, optional) — Filter images by tag.
  - `sort` (string, optional) — Sort order (`newest`, `oldest`, `name`).
  - `search` (string, optional) — Search term for filtering image names/tags.

#### `POST /api/digital_frames/library/upload`
Uploads one or more images into the permanent photo library.

- **Content-Type**: `multipart/form-data`
- **Form Fields**:
  - `file` (file, required) — Image file to upload.
  - `album` (string, optional) — Initial album assignment.

#### `GET /api/digital_frames/library/image/{image_id}`
Retrieves metadata or binary image data for a library image.

- **Query Parameters**:
  - `thumb` (integer, optional) — Set thumbnail width (e.g., `?thumb=480`).

#### `DELETE /api/digital_frames/library/image/{image_id}`
Deletes an image from the photo library.

#### `POST /api/digital_frames/library/image/{image_id}/albums`
Updates the album assignments for a specific library image.

#### `POST /api/digital_frames/library/image/{image_id}/voice_name`
Sets a custom voice/speech command name for an image.

#### `POST /api/digital_frames/library/image/{image_id}/tags`
Updates tags assigned to an image.

#### `POST /api/digital_frames/library/image/{image_id}/orientation_lock`
Sets or clears orientation lock (`portrait`, `landscape`, `auto`) for a specific image.

#### `POST /api/digital_frames/library/send`
Sends an existing library image to one or more frames.

- **Form / JSON Fields**:
  - `image_id` (string, required) — ID of the library image.
  - `entity_id` / `entry_id` (string, required) — Target frame target.
  - `packer` (string, optional) — Fast or legacy packing algorithm override.

#### `POST /api/digital_frames/library/crop`
Applies cropping coordinates to a library image.

#### `GET /api/digital_frames/library/albums`
Lists all photo library albums.

#### `POST /api/digital_frames/library/albums`
Creates or renames an album.

#### `DELETE /api/digital_frames/library/albums`
Deletes an album.

#### `POST /api/digital_frames/library/albums/{name}/images`
Adds or removes images to/from a named album.

#### `GET /api/digital_frames/library/settings`
Retrieves library configuration settings.

#### `POST /api/digital_frames/library/settings`
Updates library settings.

#### `POST /api/digital_frames/library/discover`
Triggers catalog/discovery updates for public domain art.

#### `GET /api/digital_frames/library/oauth/google/redirect_uri`
Returns configured OAuth redirect URI for Google Photos integration.

#### `POST /api/digital_frames/library/oauth/google/start`
Initiates Google Photos OAuth flow.

#### `GET /api/digital_frames/library/oauth/google/callback` *(Unauthenticated)*
Handles Google Photos OAuth redirect callback.

#### `POST /api/digital_frames/meural/push_album`
Pushes a library album to Netgear Meural Cloud for slideshow playback.

---

### 4. Messages & Announcements

#### `POST /api/digital_frames/messages/send`
Renders a custom formatted text announcement or alert message into an image and sends it to a frame.

- **JSON Body**:
  - `entity_id` or `entry_id` (string, required) — Target frame.
  - `message` (string, required) — Text content of the announcement.
  - `title` (string, optional) — Heading/title.
  - `theme` (string, optional) — Visual style theme (`dark`, `light`, `accent`).
  - `duration` (integer, optional) — Display duration in seconds.

---

### 5. Scenes & Scene Packs

#### `GET /api/digital_frames/scenes`
Lists configured wall scenes.

#### `POST /api/digital_frames/scenes`
Creates a new wall scene definition.

#### `POST /api/digital_frames/scenes/{scene_id}`
Updates an existing scene definition.

#### `DELETE /api/digital_frames/scenes/{scene_id}`
Deletes a scene definition.

#### `POST /api/digital_frames/scenes/{scene_id}/send`
Activates and sends a scene layout to its designated target frames.

#### `GET /api/digital_frames/scene_packs`
Lists installed and available public-domain art scene packs.

#### `POST /api/digital_frames/scene_packs/{pack_id}/install`
Installs a scene pack into the local library.

#### `POST /api/digital_frames/scene_packs/{pack_id}/sync`
Synchronizes installed scene pack assets.

#### `DELETE /api/digital_frames/scene_packs/{pack_id}`
Uninstalls a scene pack.

---

### 6. Skills & Interactive Widgets

#### `GET /api/digital_frames/skills`
Lists configured interactive skills (calendar, weather, quotes, news dashboard widgets).

#### `POST /api/digital_frames/skills`
Creates a skill widget configuration.

#### `POST /api/digital_frames/skills/{skill_id}`
Updates a skill configuration.

#### `DELETE /api/digital_frames/skills/{skill_id}`
Deletes a skill configuration.

#### `POST /api/digital_frames/skills/{skill_id}/send`
Renders the skill widget layout into an image and sends it to a target frame.

#### `POST /api/digital_frames/live/quick_setup`
Quickly configures automated daily schedule generation for dynamic skills.

---

### 7. Schedules & Timers

#### `GET /api/digital_frames/schedules`
Lists frame automation schedules.

#### `POST /api/digital_frames/schedules`
Creates a new display schedule.

#### `POST /api/digital_frames/schedules/{schedule_id}`
Updates an existing schedule.

#### `DELETE /api/digital_frames/schedules/{schedule_id}`
Deletes a schedule.

---

### 8. Virtual Walls & Multi-Frame Layouts

#### `GET /api/digital_frames/walls`
Lists multi-frame virtual wall layouts.

#### `POST /api/digital_frames/walls`
Creates a new virtual wall configuration.

#### `POST /api/digital_frames/walls/{wall_id}`
Updates an existing wall configuration.

#### `DELETE /api/digital_frames/walls/{wall_id}`
Deletes a virtual wall configuration.

---

### 9. System Updates & Maintenance

#### `GET /api/digital_frames/update`
Checks current component release update status.

#### `POST /api/digital_frames/update/check`
Forces a remote check for new integration updates on GitHub.

#### `POST /api/digital_frames/update/install`
Triggers an automated update installation.

#### `POST /api/digital_frames/update/restart`
Requests Home Assistant restart after updating.

#### `POST /api/digital_frames/update/dismiss`
Dismisses update notification for the current version.

---

## Response Status Codes

| Code | Description |
|---|---|
| `200 OK` | Request succeeded; returns data payload or binary stream. |
| `400 Bad Request` | Missing required fields or invalid parameters. |
| `401 Unauthorized` | Invalid or missing Home Assistant Bearer token. |
| `404 Not Found` | Requested frame, image, scene, or resource not found. |
| `500 Internal Error` | Image rendering or conversion failure. |
| `502 Bad Gateway` | Communication failure with target frame hardware. |
