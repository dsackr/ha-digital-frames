// PROTOTYPE — THROWAWAY CODE (do not ship to production)
// "Three variants of the Digital Frames panel (A: Mobile App Shell & Frame Deck, B: Spatial Wall Stage & Contextual Drawer, C: Channel Stream & Broadcast Timeline), switchable via ?variant=, on the existing panel route."

(function () {
  const params = new URLSearchParams(window.location.search);
  if (!params.has('variant')) return;

  const VARIANTS = [
    { key: 'A', name: 'Mobile App Shell & Frame Deck', fn: renderVariantA },
    { key: 'B', name: 'Spatial Wall Stage & Contextual Drawer', fn: renderVariantB },
    { key: 'C', name: 'Channel Stream & Broadcast Timeline', fn: renderVariantC },
  ];

  // Rich SVG data-URI artwork so thumbnails look like real photography & art
  const ARTWORK_SVGS = {
    img_waves: svgDataUri('#0c2d48', '#145da0', '#b1d4e0', 'Kanagawa Great Wave', 'landscape', '🌊'),
    img_fuji: svgDataUri('#3d1e6d', '#c85250', '#f7d08a', 'Red Fuji at Dawn', 'landscape', '🗻'),
    img_botanical: svgDataUri('#1b3b2b', '#2e6f40', '#c8e6c9', 'Monstera Botanical Study', 'portrait', '🌿'),
    img_arch: svgDataUri('#2b2d42', '#8d99ae', '#edf2f4', 'Kyoto Cedar Pavilion', 'landscape', '⛩️'),
    img_family: svgDataUri('#4a2545', '#d97757', '#fbeec1', 'Big Sur Coastline 2026', 'portrait', '🌅'),
    img_bauhaus: svgDataUri('#1d1e22', '#e04f5f', '#f9c74f', 'Bauhaus Exhibition 1923', 'portrait', '📐'),
    img_starry: svgDataUri('#0f172a', '#1e40af', '#facc15', 'Alps Starlight Panorama', 'landscape', '✨'),
    img_cafe: svgDataUri('#3b2314', '#b45309', '#fef3c7', 'Morning Espresso Still Life', 'landscape', '☕'),
  };

  function svgDataUri(bg1, bg2, accent, title, orient, emoji) {
    const w = orient === 'portrait' ? 480 : 800;
    const h = orient === 'portrait' ? 800 : 480;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}">
      <defs>
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="${bg1}"/>
          <stop offset="100%" stop-color="${bg2}"/>
        </linearGradient>
      </defs>
      <rect width="${w}" height="${h}" fill="url(#g)"/>
      <circle cx="${w * 0.72}" cy="${h * 0.32}" r="${Math.min(w, h) * 0.22}" fill="${accent}" fill-opacity="0.22"/>
      <path d="M0 ${h * 0.72} Q ${w * 0.35} ${h * 0.52} ${w * 0.65} ${h * 0.7} T ${w} ${h * 0.62} L ${w} ${h} L 0 ${h} Z" fill="${accent}" fill-opacity="0.16"/>
      <text x="${w * 0.08}" y="${h * 0.48}" font-size="${Math.min(w, h) * 0.16}" font-family="system-ui">${emoji}</text>
      <text x="${w * 0.08}" y="${h * 0.84}" fill="#ffffff" font-family="system-ui, -apple-system, sans-serif" font-size="${Math.min(w, h) * 0.055}" font-weight="700">${title}</text>
      <text x="${w * 0.08}" y="${h * 0.91}" fill="${accent}" font-family="system-ui, -apple-system, sans-serif" font-size="${Math.min(w, h) * 0.036}" font-weight="500">${w}×${h} · ${orient.toUpperCase()}</text>
    </svg>`;
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
  }

  // In-memory prototype state (seeded from the live panel + mock server)
  const state = {
    variant: normalizeVariant(params.get('variant')),
    viewport: params.get('vp') || 'mobile', // 'mobile' (390px phone bezel) | 'desktop' (full width)
    stateInspectorOpen: false,
    lastAction: 'Initialized prototype from live panel data',

    // Variant A state
    aTab: 'walls', // 'walls' | 'library' | 'automations' | 'discover'
    aWallLayoutEdit: false,
    aAutoSubTab: 'widgets', // 'widgets' | 'schedules'

    // Variant B state
    bMode: 'content', // 'content' | 'layout'
    bDrawerTab: 'library', // 'library' | 'scenes' | 'widgets' | 'schedule' | 'config'
    bDrawerExpanded: true,

    // Variant C state
    cChannelId: 'all', // 'all' or frame.entryId

    // Shared domain state across all variants
    activeWallId: 'wall_living',
    selectedFrameIds: ['entry_living_main'],
    activeSceneId: null,
    wallpaperSpanImageId: null,
    libraryFilter: 'all', // 'all' | 'uploads' | 'albums' | 'curated'
    selectedAlbum: null,
    batchSelectedPhotos: [],

    // Active sheet / modal state
    cropSheet: null, // { imageId, targetFrameId, tab: 'crop' | 'voice' | 'albums', zoom: 1.0, panX: 0, panY: 0, aspect: 'landscape' }
    frameConfigSheet: null, // entryId
    promptModal: null, // { title, label, value, onConfirm }
    activeWidgetDraft: {
      type: 'newspaper',
      title: 'The Home Chronicle',
      weatherEntity: 'weather.home',
      calendarEntity: 'calendar.family',
      headline: 'Sunny 72°F · 3 events on family calendar · Trash pickup tomorrow',
    },

    // Domain records (hydrated from panel / mock-server)
    frames: [],
    walls: [],
    scenes: [],
    images: [],
    albums: [],
    schedules: [],
    discoveredUnconfigured: [
      { flow_id: 'disc_1', title: 'Fraimic 7.3" (Bedroom East)', host: '192.168.1.88', size: '7.3"' },
    ],
  };

  function normalizeVariant(v) {
    const upper = (v || 'A').toUpperCase();
    return VARIANTS.some((x) => x.key === upper) ? upper : 'A';
  }

  function seedRichDefaults(panel) {
    state.frames = [
      {
        entryId: 'entry_living_main',
        title: 'Living Room 13.3"',
        size: '13.3"',
        width: 1600,
        height: 1200,
        orientation: 'landscape',
        orientationMode: 'auto',
        battery: 88,
        online: false,
        wakeInMinutes: 34,
        sleepMinutes: 60,
        host: '192.168.1.41',
        driver: 'fraimic',
        currentImageId: 'img_waves',
        queuedImageId: 'img_fuji',
        stagedImageId: null,
      },
      {
        entryId: 'entry_living_side',
        title: 'Reading Nook 7.3"',
        size: '7.3"',
        width: 480,
        height: 800,
        orientation: 'portrait',
        orientationMode: 'portrait',
        battery: 64,
        online: false,
        wakeInMinutes: 12,
        sleepMinutes: 30,
        host: '192.168.1.42',
        driver: 'fraimic',
        currentImageId: 'img_botanical',
        queuedImageId: null,
        stagedImageId: null,
      },
      {
        entryId: 'entry_kitchen',
        title: 'Kitchen Counter 10.3"',
        size: '10.3"',
        width: 1872,
        height: 1404,
        orientation: 'landscape',
        orientationMode: 'landscape',
        battery: 100,
        online: true,
        wakeInMinutes: 0,
        sleepMinutes: 15,
        host: '192.168.1.49',
        driver: 'fraimic',
        currentImageId: 'img_cafe',
        queuedImageId: null,
        stagedImageId: null,
      },
      {
        entryId: 'entry_study_meural',
        title: 'Study Meural 27"',
        size: '27"',
        width: 1920,
        height: 1080,
        orientation: 'landscape',
        orientationMode: 'auto',
        battery: null,
        online: true,
        wakeInMinutes: 0,
        sleepMinutes: 0,
        host: '192.168.1.55',
        driver: 'meural',
        currentImageId: 'img_arch',
        queuedImageId: null,
        stagedImageId: null,
      },
    ];

    state.walls = [
      {
        wall_id: 'wall_living',
        name: 'Living Room Gallery',
        placements: {
          entry_living_main: { x: 24, y: 28, w: 150, h: 112 },
          entry_living_side: { x: 192, y: 22, w: 76, h: 124 },
          entry_kitchen: { x: 286, y: 34, w: 124, h: 94 },
        },
      },
      {
        wall_id: 'default',
        name: 'All Frames (4)',
        placements: {
          entry_living_main: { x: 16, y: 28, w: 128, h: 96 },
          entry_living_side: { x: 156, y: 20, w: 68, h: 110 },
          entry_kitchen: { x: 236, y: 32, w: 112, h: 84 },
          entry_study_meural: { x: 360, y: 18, w: 164, h: 96 },
        },
      },
    ];

    state.images = [
      { image_id: 'img_waves', title: 'Kanagawa Great Wave', voiceName: 'great wave', tags: ['ukiyo-e', 'ocean'], albums: ['Ukiyo-e Woodblocks', 'Favorites'], orientation: 'landscape', curated: true },
      { image_id: 'img_fuji', title: 'Red Fuji at Dawn', voiceName: 'red fuji', tags: ['ukiyo-e', 'mountain'], albums: ['Ukiyo-e Woodblocks', 'Favorites'], orientation: 'landscape', curated: true },
      { image_id: 'img_botanical', title: 'Monstera Botanical Study', voiceName: 'monstera leaf', tags: ['plants', 'green'], albums: ['Botanical Prints'], orientation: 'portrait', curated: true },
      { image_id: 'img_arch', title: 'Kyoto Cedar Pavilion', voiceName: 'kyoto pavilion', tags: ['japan', 'travel'], albums: ['Family 2026', 'Favorites'], orientation: 'landscape', curated: false },
      { image_id: 'img_family', title: 'Big Sur Coastline 2026', voiceName: 'big sur sunset', tags: ['california', 'sunset'], albums: ['Family 2026', 'Favorites'], orientation: 'portrait', curated: false },
      { image_id: 'img_bauhaus', title: 'Bauhaus Exhibition 1923', voiceName: 'bauhaus poster', tags: ['modernism', 'poster'], albums: ['Botanical Prints'], orientation: 'portrait', curated: true },
      { image_id: 'img_starry', title: 'Alps Starlight Panorama', voiceName: 'starlight alps', tags: ['night', 'panorama'], albums: ['Family 2026'], orientation: 'landscape', curated: false },
      { image_id: 'img_cafe', title: 'Morning Espresso Still Life', voiceName: 'morning coffee', tags: ['kitchen', 'warm'], albums: ['Favorites'], orientation: 'landscape', curated: false },
    ];

    state.albums = [
      { name: 'Favorites', count: 5, cover: 'img_waves', source: 'user' },
      { name: 'Family 2026', count: 3, cover: 'img_family', source: 'user' },
      { name: 'Ukiyo-e Woodblocks', count: 2, cover: 'img_fuji', source: 'curated' },
      { name: 'Botanical Prints', count: 2, cover: 'img_botanical', source: 'curated' },
    ];

    state.scenes = [
      {
        scene_id: 'sc_edo',
        name: 'Edo Woodblock Triptych',
        kind: 'scene',
        mappings: {
          entry_living_main: 'img_waves',
          entry_living_side: 'img_botanical',
          entry_kitchen: 'img_fuji',
        },
      },
      {
        scene_id: 'sc_panorama',
        name: 'Alps Panorama Wallpaper',
        kind: 'wallpaper',
        wallpaperImageId: 'img_starry',
        mappings: {
          entry_living_main: 'img_starry',
          entry_living_side: 'img_starry',
          entry_kitchen: 'img_starry',
        },
      },
      {
        scene_id: 'sc_warm',
        name: 'Sunday Morning Calm',
        kind: 'scene',
        mappings: {
          entry_living_main: 'img_arch',
          entry_living_side: 'img_family',
          entry_kitchen: 'img_cafe',
        },
      },
    ];

    state.schedules = [
      { id: 'sched_1', time: '07:00', label: 'Daily Newspaper Widget', target: 'Kitchen Counter 10.3"', days: 'Mon–Fri', enabled: true, kind: 'widget' },
      { id: 'sched_2', time: '09:00', label: 'Edo Woodblock Triptych', target: 'Living Room Gallery (3 frames)', days: 'Every day', enabled: true, kind: 'scene' },
      { id: 'sched_3', time: '12:30', label: 'Family Agenda & Weather', target: 'Kitchen Counter 10.3"', days: 'Every day', enabled: true, kind: 'widget' },
      { id: 'sched_4', time: '18:30', label: 'Alps Panorama Wallpaper', target: 'Living Room Gallery (3 frames)', days: 'Weekends', enabled: false, kind: 'wallpaper' },
    ];
  }

  function imgThumb(imageId) {
    return ARTWORK_SVGS[imageId] || ARTWORK_SVGS.img_waves;
  }

  function getImage(imageId) {
    return state.images.find((i) => i.image_id === imageId) || state.images[0];
  }

  function getFrame(entryId) {
    return state.frames.find((f) => f.entryId === entryId) || state.frames[0];
  }

  function getActiveWall() {
    return state.walls.find((w) => w.wall_id === state.activeWallId) || state.walls[0];
  }

  function getWallFrames() {
    const wall = getActiveWall();
    return Object.keys(wall.placements)
      .map((id) => state.frames.find((f) => f.entryId === id))
      .filter(Boolean);
  }

  function getFilteredImages() {
    return state.images.filter((img) => {
      if (state.selectedAlbum && !img.albums.includes(state.selectedAlbum)) return false;
      if (state.libraryFilter === 'uploads') return !img.curated;
      if (state.libraryFilter === 'curated') return img.curated;
      return true;
    });
  }

  function setVariant(key, reason) {
    const next = normalizeVariant(key);
    state.variant = next;
    state.lastAction = reason || `Switched to Variant ${next}`;
    const u = new URL(window.location.href);
    u.searchParams.set('variant', next);
    u.searchParams.set('vp', state.viewport);
    window.history.replaceState({}, '', u.toString());
    render();
  }

  function cycleVariant(delta) {
    const idx = VARIANTS.findIndex((v) => v.key === state.variant);
    const nextIdx = (idx + delta + VARIANTS.length) % VARIANTS.length;
    setVariant(VARIANTS[nextIdx].key, `Cycled to Variant ${VARIANTS[nextIdx].key} (${VARIANTS[nextIdx].name})`);
  }

  // Action helpers that mutate in-memory state and trigger re-render + state log
  function sendImageToFrame(imageId, entryId, cropMeta) {
    const frame = getFrame(entryId);
    const img = getImage(imageId);
    if (!frame || !img) return;
    if (frame.online) {
      frame.currentImageId = imageId;
      frame.queuedImageId = null;
      frame.stagedImageId = null;
      state.lastAction = `Sent "${img.title}" live to ${frame.title}${cropMeta ? ` (crop zoom ${cropMeta.zoom}x)` : ''}`;
    } else {
      frame.queuedImageId = imageId;
      frame.stagedImageId = null;
      state.lastAction = `Queued "${img.title}" ON DECK for ${frame.title} (wakes in ${frame.wakeInMinutes}m)`;
    }
    state.cropSheet = null;
    render();
  }

  function stageSceneOnWall(sceneId) {
    const scene = state.scenes.find((s) => s.scene_id === sceneId);
    if (!scene) return;
    state.activeSceneId = sceneId;
    state.wallpaperSpanImageId = scene.wallpaperImageId || null;
    for (const [entryId, imgId] of Object.entries(scene.mappings)) {
      const f = getFrame(entryId);
      if (f) f.stagedImageId = imgId;
    }
    state.lastAction = `Staged ${scene.kind === 'wallpaper' ? 'Spanning Wallpaper' : 'Scene'} "${scene.name}" across ${Object.keys(scene.mappings).length} frames`;
    render();
  }

  function commitStagedWall() {
    let count = 0;
    for (const f of getWallFrames()) {
      if (f.stagedImageId) {
        if (f.online) {
          f.currentImageId = f.stagedImageId;
        } else {
          f.queuedImageId = f.stagedImageId;
        }
        f.stagedImageId = null;
        count++;
      }
    }
    state.activeSceneId = null;
    state.wallpaperSpanImageId = null;
    state.lastAction = `Applied staged wall artwork to ${count} frame(s) (Live / On Deck)`;
    render();
  }

  function clearStagedWall() {
    for (const f of state.frames) f.stagedImageId = null;
    state.activeSceneId = null;
    state.wallpaperSpanImageId = null;
    state.lastAction = 'Cleared staged wall preview';
    render();
  }

  function openCropSheet(imageId, targetFrameId, initialTab) {
    const f = getFrame(targetFrameId || state.selectedFrameIds[0] || state.frames[0].entryId);
    state.cropSheet = {
      imageId,
      targetFrameId: f.entryId,
      tab: initialTab || 'crop',
      zoom: 1.15,
      panX: 0,
      panY: 0,
      aspect: f.orientation || 'landscape',
    };
    const img = getImage(imageId);
    state.lastAction = `Opened Frame-Aware Crop & Inspector for "${img.title}" → ${f.title}`;
    render();
  }

  // -------------------------------------------------------------------------
  // Prototype Stylesheet (injected into prototype host)
  // -------------------------------------------------------------------------
  const PROTO_CSS = `
    :host, .proto-root {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #e2e8f0;
      box-sizing: border-box;
    }
    *, *::before, *::after { box-sizing: border-box; }
    .proto-outer {
      min-height: 100dvh;
      background: #090d16;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 0 0 112px 0;
    }
    .proto-outer.vp-mobile {
      padding-top: 16px;
      background: radial-gradient(circle at top, #172036 0%, #070a12 100%);
    }
    .proto-device-frame {
      width: 100%;
      max-width: 1240px;
      background: #0f172a;
      min-height: calc(100dvh - 112px);
      position: relative;
      container-type: inline-size;
      container-name: df-panel;
    }
    .proto-outer.vp-mobile .proto-device-frame {
      width: 393px;
      max-width: 100vw;
      min-height: 780px;
      max-height: 844px;
      border-radius: 38px;
      border: 8px solid #1e293b;
      box-shadow: 0 24px 70px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(255,255,255,0.08);
      overflow-x: hidden;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }

    /* Common pills, badges, buttons */
    .btn {
      border: 1px solid rgba(148, 163, 184, 0.25);
      background: #1e293b;
      color: #f8fafc;
      border-radius: 10px;
      padding: 8px 13px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      min-height: 40px;
      transition: all 0.15s ease;
    }
    .btn:hover { background: #334155; }
    .btn-primary {
      background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
      border-color: #60a5fa;
      color: #fff;
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
    }
    .btn-primary:hover { background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%); }
    .btn-amber {
      background: rgba(245, 158, 11, 0.16);
      border-color: rgba(245, 158, 11, 0.45);
      color: #fcd34d;
    }
    .btn-sm {
      padding: 5px 10px;
      font-size: 12px;
      min-height: 34px;
      border-radius: 8px;
    }
    .pill-row {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 4px;
      scrollbar-width: none;
    }
    .pill-row::-webkit-scrollbar { display: none; }
    .pill {
      flex: 0 0 auto;
      padding: 7px 13px;
      border-radius: 999px;
      font-size: 12.5px;
      font-weight: 600;
      background: #1e293b;
      color: #94a3b8;
      border: 1px solid rgba(148,163,184,0.18);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .pill.active {
      background: rgba(59, 130, 246, 0.2);
      color: #60a5fa;
      border-color: #3b82f6;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
    }
    .status-live { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .status-deck { background: rgba(245, 158, 11, 0.16); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }
    .status-staged { background: rgba(168, 85, 247, 0.18); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }

    /* Physical E-Ink Bezel Thumbnail */
    .bezel-wrap {
      background: #f8fafc;
      padding: 8px;
      border-radius: 8px;
      box-shadow: inset 0 0 0 2px #cbd5e1, 0 8px 20px rgba(0,0,0,0.45);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }
    .bezel-wrap img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
      border-radius: 3px;
    }

    /* Variant A: Consumer Mobile App Shell */
    .va-header {
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(15, 23, 42, 0.92);
      backdrop-filter: blur(12px);
      padding: 14px 16px 10px;
      border-bottom: 1px solid rgba(148,163,184,0.12);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .va-body {
      padding: 14px 16px 90px;
      flex: 1;
    }
    .va-mini-wall {
      background: linear-gradient(180deg, #162032 0%, #0f172a 100%);
      border: 1px solid rgba(148,163,184,0.18);
      border-radius: 16px;
      padding: 12px;
      margin-bottom: 14px;
    }
    .va-mini-canvas {
      position: relative;
      height: 148px;
      background: radial-gradient(rgba(148,163,184,0.15) 1px, transparent 1px);
      background-size: 14px 14px;
      border-radius: 10px;
      overflow: hidden;
      border: 1px dashed rgba(148,163,184,0.2);
    }
    .va-frame-card {
      background: #162032;
      border: 1px solid rgba(148,163,184,0.16);
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 12px;
      transition: border-color 0.15s;
    }
    .va-frame-card.selected {
      border-color: #3b82f6;
      box-shadow: 0 0 0 1px rgba(59,130,246,0.4);
    }
    .va-bottom-nav {
      position: sticky;
      bottom: 0;
      left: 0;
      right: 0;
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(12px);
      border-top: 1px solid rgba(148,163,184,0.15);
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      padding: 6px 8px 10px;
      z-index: 30;
    }
    .va-nav-item {
      background: none;
      border: none;
      color: #94a3b8;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 3px;
      font-size: 11px;
      font-weight: 600;
      padding: 6px 4px;
      border-radius: 10px;
      cursor: pointer;
    }
    .va-nav-item.active {
      color: #60a5fa;
      background: rgba(59,130,246,0.12);
    }

    /* Clean Photo Grid (Flow 3) */
    .photo-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(105px, 1fr));
      gap: 8px;
    }
    .photo-tile {
      position: relative;
      aspect-ratio: 1 / 1;
      border-radius: 12px;
      overflow: hidden;
      background: #1e293b;
      cursor: pointer;
      border: 2px solid transparent;
    }
    .photo-tile.checked {
      border-color: #3b82f6;
    }
    .photo-tile img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .photo-tile-check {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 26px;
      height: 26px;
      border-radius: 999px;
      background: rgba(15,23,42,0.75);
      border: 1.5px solid rgba(255,255,255,0.6);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
    }
    .photo-tile.checked .photo-tile-check {
      background: #3b82f6;
      border-color: #fff;
    }
    .photo-tile-caption {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      padding: 16px 6px 5px;
      background: linear-gradient(transparent, rgba(0,0,0,0.82));
      font-size: 10.5px;
      color: #f8fafc;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Variant B: Spatial Wall Workbench + Contextual Inspector Drawer */
    .vb-shell {
      display: flex;
      flex-direction: column;
      min-height: 760px;
      height: 100%;
    }
    @container df-panel (min-width: 760px) {
      .vb-main {
        display: grid;
        grid-template-columns: 1fr 380px;
        flex: 1;
      }
    }
    .vb-stage {
      background: radial-gradient(rgba(148,163,184,0.16) 1px, #0b1120 1px);
      background-size: 18px 18px;
      position: relative;
      min-height: 310px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      border-bottom: 1px solid rgba(148,163,184,0.16);
    }
    .vb-drawer {
      background: #131c2e;
      display: flex;
      flex-direction: column;
      flex: 1;
      border-left: 1px solid rgba(148,163,184,0.14);
    }

    /* Variant C: Channel Stream & Broadcast Timeline */
    .vc-shell {
      display: flex;
      flex-direction: column;
      padding-bottom: 32px;
    }
    .vc-timeline-track {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding: 6px 2px 10px;
    }
    .vc-slot {
      flex: 0 0 165px;
      background: #162032;
      border: 1px solid rgba(148,163,184,0.18);
      border-radius: 12px;
      padding: 10px;
      cursor: pointer;
    }
    .vc-slot.enabled {
      border-left: 4px solid #3b82f6;
    }

    /* Slide-Up Bottom Sheet Modal (Crop & Inspector / Frame Settings / Prompt) */
    .sheet-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 23, 0.76);
      backdrop-filter: blur(4px);
      z-index: 900;
      display: flex;
      align-items: flex-end;
      justify-content: center;
    }
    .sheet-card {
      width: 100%;
      max-width: 540px;
      max-height: 90dvh;
      background: #111827;
      border: 1px solid rgba(148,163,184,0.25);
      border-radius: 22px 22px 0 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 -16px 50px rgba(0,0,0,0.65);
    }
    .sheet-handle {
      width: 42px;
      height: 5px;
      background: rgba(148,163,184,0.35);
      border-radius: 999px;
      margin: 8px auto 4px;
    }

    /* Floating Prototype Switcher Bar */
    .proto-switcher-wrap {
      position: fixed;
      bottom: 12px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 9999;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      width: min(96vw, 760px);
      pointer-events: none;
    }
    .proto-state-pill {
      pointer-events: auto;
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid rgba(56, 189, 248, 0.4);
      color: #bae6fd;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 11.5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      max-width: 100%;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      box-shadow: 0 6px 20px rgba(0,0,0,0.5);
      cursor: pointer;
    }
    .proto-bar {
      pointer-events: auto;
      background: #020617;
      color: #f8fafc;
      border: 1.5px solid #f59e0b;
      border-radius: 999px;
      padding: 6px 10px;
      display: flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 12px 32px rgba(0,0,0,0.8);
      font-size: 12.5px;
      font-weight: 700;
    }
    .proto-bar button {
      background: #1e293b;
      color: #f8fafc;
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: 999px;
      padding: 5px 11px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    .proto-bar button:hover {
      background: #334155;
    }
    .proto-state-drawer {
      pointer-events: auto;
      width: 100%;
      max-height: 220px;
      overflow: auto;
      background: #020617;
      border: 1px solid #38bdf8;
      border-radius: 12px;
      padding: 10px 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
      color: #e2e8f0;
      box-shadow: 0 12px 32px rgba(0,0,0,0.85);
    }
  `;

  // -------------------------------------------------------------------------
  // Variant A: Mobile App Shell & Frame Deck
  // -------------------------------------------------------------------------
  function renderVariantA() {
    const wall = getActiveWall();
    const wallFrames = getWallFrames();
    const hasStaged = wallFrames.some((f) => f.stagedImageId);

    return `
      <!-- Top App Bar -->
      <div class="va-header">
        <div>
          <div style="font-size:10.5px;text-transform:uppercase;letter-spacing:0.08em;color:#60a5fa;font-weight:700;">Digital Frames · Variant A</div>
          <div style="font-size:17px;font-weight:800;color:#f8fafc;">
            ${state.aTab === 'walls' ? wall.name : state.aTab === 'library' ? 'Unified Library' : state.aTab === 'automations' ? 'Widgets & Schedules' : 'Discover Art & Packs'}
          </div>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-primary btn-sm" data-action="quick-send">＋ Quick Send</button>
        </div>
      </div>

      <div class="va-body">
        ${state.discoveredUnconfigured.length ? `
          <div style="background:rgba(59,130,246,0.14);border:1px solid rgba(59,130,246,0.4);border-radius:12px;padding:10px 12px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <div style="font-size:12px;">
              <strong style="color:#93c5fd;">📡 New frame on Wi-Fi:</strong> ${state.discoveredUnconfigured[0].title}
            </div>
            <button class="btn btn-primary btn-sm" data-action="adopt-discovered">Adopt</button>
          </div>
        ` : ''}

        ${state.aTab === 'walls' ? renderVariantAWalls(wall, wallFrames, hasStaged) : ''}
        ${state.aTab === 'library' ? renderSharedCleanLibrary() : ''}
        ${state.aTab === 'automations' ? renderVariantAAutomations() : ''}
        ${state.aTab === 'discover' ? renderVariantADiscover() : ''}
      </div>

      <!-- Sticky Staged Scene Bar -->
      ${hasStaged ? `
        <div style="position:sticky;bottom:64px;margin:0 12px 8px;background:#1e1b4b;border:1px solid #818cf8;border-radius:14px;padding:10px 14px;display:flex;align-items:center;justify-content:space-between;z-index:25;box-shadow:0 10px 25px rgba(0,0,0,0.6);">
          <div style="font-size:12.5px;font-weight:600;color:#e0e7ff;">
            🎨 Previewing staged art on ${wallFrames.filter((f) => f.stagedImageId).length} frames
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-sm" data-action="clear-staged">Cancel</button>
            <button class="btn btn-primary btn-sm" data-action="commit-staged">▶ Apply Wall Now</button>
          </div>
        </div>
      ` : ''}

      <!-- Bottom Navigation Bar -->
      <nav class="va-bottom-nav">
        <button class="va-nav-item ${state.aTab === 'walls' ? 'active' : ''}" data-action="a-tab" data-tab="walls">
          <span style="font-size:18px;">🖼️</span>
          <span>Walls & Frames</span>
        </button>
        <button class="va-nav-item ${state.aTab === 'library' ? 'active' : ''}" data-action="a-tab" data-tab="library">
          <span style="font-size:18px;">📚</span>
          <span>Library (${state.images.length})</span>
        </button>
        <button class="va-nav-item ${state.aTab === 'automations' ? 'active' : ''}" data-action="a-tab" data-tab="automations">
          <span style="font-size:18px;">⚡</span>
          <span>Automations</span>
        </button>
        <button class="va-nav-item ${state.aTab === 'discover' ? 'active' : ''}" data-action="a-tab" data-tab="discover">
          <span style="font-size:18px;">✨</span>
          <span>Discover</span>
        </button>
      </nav>
    `;
  }

  function renderVariantAWalls(wall, wallFrames, hasStaged) {
    return `
      <!-- Wall Switcher + New Wall (No window.prompt!) -->
      <div class="pill-row" style="margin-bottom:12px;">
        ${state.walls.map((w) => `
          <button class="pill ${w.wall_id === wall.wall_id ? 'active' : ''}" data-action="select-wall" data-wall="${w.wall_id}">
            🏠 ${w.name}
          </button>
        `).join('')}
        <button class="pill" data-action="new-wall-modal">＋ New Wall</button>
      </div>

      <!-- Mini Wall Map (Never traps touch scroll unless Layout Edit Mode is toggled!) -->
      <div class="va-mini-wall">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <span style="font-size:12px;font-weight:700;color:#94a3b8;">
            ${state.aWallLayoutEdit ? '📐 EDIT LAYOUT MODE (Tap frame to nudge)' : '🔒 WALL OVERVIEW (Tap frame to inspect)'}
          </span>
          <button class="btn btn-sm" data-action="toggle-a-layout">
            ${state.aWallLayoutEdit ? '✓ Done Layout' : '✎ Edit Layout'}
          </button>
        </div>
        <div class="va-mini-canvas">
          ${wallFrames.map((f) => {
            const p = wall.placements[f.entryId] || { x: 20, y: 20, w: 90, h: 70 };
            const activeImgId = f.stagedImageId || f.queuedImageId || f.currentImageId;
            const isSel = state.selectedFrameIds.includes(f.entryId);
            return `
              <div data-action="select-frame" data-entry="${f.entryId}"
                   style="position:absolute;left:${Math.round(p.x * 0.72)}px;top:${Math.round(p.y * 0.68)}px;width:${Math.round(p.w * 0.72)}px;height:${Math.round(p.h * 0.68)}px;background:#f8fafc;padding:3px;border-radius:5px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,0.5);border:2px solid ${isSel ? '#3b82f6' : '#cbd5e1'};">
                <img src="${imgThumb(activeImgId)}" style="width:100%;height:100%;object-fit:cover;border-radius:2px;" />
                <div style="position:absolute;bottom:2px;left:2px;right:2px;background:rgba(15,23,42,0.82);color:#fff;font-size:8.5px;padding:1px 3px;border-radius:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                  ${f.title}
                </div>
              </div>
            `;
          }).join('')}
        </div>
        ${state.aWallLayoutEdit ? `
          <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;">
            <button class="btn btn-sm" data-action="nudge-frame" data-dx="-16" data-dy="0">← Left</button>
            <button class="btn btn-sm" data-action="nudge-frame" data-dx="16" data-dy="0">→ Right</button>
            <button class="btn btn-sm" data-action="nudge-frame" data-dx="0" data-dy="-12">↑ Up</button>
            <button class="btn btn-sm" data-action="nudge-frame" data-dx="0" data-dy="12">↓ Down</button>
            <button class="btn btn-sm" data-action="auto-align-wall">✨ Auto-Align Row</button>
          </div>
        ` : ''}
      </div>

      <!-- Unified Scenes & Spanning Wallpapers Carousel -->
      <div style="margin-bottom:14px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
          <span style="font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;">Scenes & Spanning Wallpapers</span>
          <button class="btn btn-sm" data-action="save-scene-modal">💾 Save Current Wall</button>
        </div>
        <div class="pill-row">
          ${state.scenes.map((sc) => `
            <button class="pill ${state.activeSceneId === sc.scene_id ? 'active' : ''}" data-action="stage-scene" data-scene="${sc.scene_id}">
              ${sc.kind === 'wallpaper' ? '🖼 Span:' : '🎬 Scene:'} ${sc.name}
            </button>
          `).join('')}
        </div>
      </div>

      <!-- Frame Card Deck (Replaces hover-only quadrants with touch-first cards!) -->
      <div style="font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">
        Frames on this Wall (${wallFrames.length})
      </div>
      ${wallFrames.map((f) => {
        const currentImg = getImage(f.currentImageId);
        const queuedImg = f.queuedImageId ? getImage(f.queuedImageId) : null;
        const stagedImg = f.stagedImageId ? getImage(f.stagedImageId) : null;
        const displayImg = stagedImg || queuedImg || currentImg;
        const isSel = state.selectedFrameIds.includes(f.entryId);
        return `
          <div class="va-frame-card ${isSel ? 'selected' : ''}" data-action="select-frame" data-entry="${f.entryId}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:8px;">
              <div>
                <div style="font-size:15px;font-weight:700;color:#f8fafc;">${f.title}</div>
                <div style="font-size:11.5px;color:#94a3b8;margin-top:2px;">
                  ${f.width}×${f.height} (${f.orientation}) · ${f.battery !== null ? `🔋 ${f.battery}%` : '⚡ Mains'} · ${f.online ? '🟢 Awake on Wi-Fi' : `💤 Wakes in ${f.wakeInMinutes}m`}
                </div>
              </div>
              ${stagedImg
                ? `<span class="status-badge status-staged">🎨 Staged Draft</span>`
                : queuedImg
                  ? `<span class="status-badge status-deck">⏳ On Deck (${f.wakeInMinutes}m)</span>`
                  : `<span class="status-badge status-live">🟢 Showing Now</span>`}
            </div>

            <div style="display:flex;gap:12px;align-items:center;">
              <div class="bezel-wrap" style="width:${f.orientation === 'portrait' ? '74px' : '110px'};height:${f.orientation === 'portrait' ? '106px' : '82px'};flex:0 0 auto;">
                <img src="${imgThumb(displayImg.image_id)}" alt="${displayImg.title}" />
              </div>
              <div style="flex:1;min-width:0;">
                <div style="font-size:13.5px;font-weight:700;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                  ${displayImg.title}
                </div>
                ${queuedImg && !stagedImg ? `
                  <div style="font-size:11.5px;color:#fbbf24;margin-top:3px;">
                    Replacing "${currentImg.title}" on next wake
                  </div>
                ` : `
                  <div style="font-size:11.5px;color:#94a3b8;margin-top:3px;">
                    🗣 Voice: "${displayImg.voiceName}"
                  </div>
                `}
                <div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;">
                  <button class="btn btn-primary btn-sm" data-action="open-picker-for-frame" data-entry="${f.entryId}">🖼 Change Art</button>
                  <button class="btn btn-sm" data-action="open-crop-sheet" data-image="${displayImg.image_id}" data-entry="${f.entryId}">✂ Crop</button>
                  <button class="btn btn-sm" data-action="open-frame-config" data-entry="${f.entryId}">⚙ Settings</button>
                </div>
              </div>
            </div>
          </div>
        `;
      }).join('')}
    `;
  }

  function renderSharedCleanLibrary() {
    const photos = getFilteredImages();
    return `
      <!-- Filter Pills Consolidating My Gallery + Art Gallery -->
      <div class="pill-row" style="margin-bottom:10px;">
        <button class="pill ${state.libraryFilter === 'all' && !state.selectedAlbum ? 'active' : ''}" data-action="lib-filter" data-filter="all">All (${state.images.length})</button>
        <button class="pill ${state.libraryFilter === 'uploads' ? 'active' : ''}" data-action="lib-filter" data-filter="uploads">📱 My Uploads</button>
        <button class="pill ${state.libraryFilter === 'curated' ? 'active' : ''}" data-action="lib-filter" data-filter="curated">🏛 Curated Art</button>
        ${state.albums.map((a) => `
          <button class="pill ${state.selectedAlbum === a.name ? 'active' : ''}" data-action="lib-album" data-album="${a.name}">
            📁 ${a.name} (${a.count})
          </button>
        `).join('')}
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <span style="font-size:12px;color:#94a3b8;">Tap any photo to Crop & Send · Check corners for batch actions</span>
        <button class="btn btn-sm" data-action="simulate-upload">⬆ Upload Photo</button>
      </div>

      <!-- Clean 3-Column Grid (Zero per-card dropdowns or button stacks!) -->
      <div class="photo-grid">
        ${photos.map((img) => {
          const isChecked = state.batchSelectedPhotos.includes(img.image_id);
          return `
            <div class="photo-tile ${isChecked ? 'checked' : ''}" data-action="open-crop-sheet" data-image="${img.image_id}">
              <img src="${imgThumb(img.image_id)}" alt="${img.title}" />
              <div class="photo-tile-check" data-action="toggle-batch-photo" data-image="${img.image_id}">
                ${isChecked ? '✓' : ''}
              </div>
              <div class="photo-tile-caption">
                ${img.orientation === 'portrait' ? '▯' : '▭'} ${img.title}
              </div>
            </div>
          `;
        }).join('')}
      </div>

      <!-- Sticky Batch Action Bar when 1+ photos are selected -->
      ${state.batchSelectedPhotos.length > 0 ? `
        <div style="position:sticky;bottom:68px;margin-top:14px;background:#1e293b;border:1.5px solid #3b82f6;border-radius:14px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px;box-shadow:0 12px 28px rgba(0,0,0,0.65);">
          <span style="font-size:12.5px;font-weight:700;color:#93c5fd;">${state.batchSelectedPhotos.length} selected</span>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-primary btn-sm" data-action="batch-send-wall">▶ Distribute to Wall</button>
            <button class="btn btn-sm" data-action="batch-add-favorites">♥ Add to Favorites</button>
            <button class="btn btn-sm" data-action="batch-clear">Clear</button>
          </div>
        </div>
      ` : ''}
    `;
  }

  function renderVariantAAutomations() {
    return `
      <div class="pill-row" style="margin-bottom:14px;">
        <button class="pill ${state.aAutoSubTab === 'widgets' ? 'active' : ''}" data-action="auto-subtab" data-sub="widgets">🧩 Live Widgets & Messages</button>
        <button class="pill ${state.aAutoSubTab === 'schedules' ? 'active' : ''}" data-action="auto-subtab" data-sub="schedules">🗓 Schedule Timeline (${state.schedules.length})</button>
      </div>

      ${state.aAutoSubTab === 'widgets' ? renderSharedWidgetStudio() : renderSharedScheduleList()}
    `;
  }

  function renderSharedWidgetStudio() {
    const d = state.activeWidgetDraft;
    return `
      <!-- Sticky Live Frame Preview for Widgets -->
      <div style="background:#162032;border:1px solid rgba(148,163,184,0.2);border-radius:16px;padding:14px;margin-bottom:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:11.5px;font-weight:700;color:#60a5fa;text-transform:uppercase;">Live E-Ink Render Preview</span>
          <span style="font-size:11px;color:#94a3b8;">Target: ${getFrame(state.selectedFrameIds[0]).title}</span>
        </div>
        <div style="background:#f8fafc;color:#0f172a;border-radius:8px;padding:14px;font-family:Georgia,serif;border:4px solid #cbd5e1;">
          <div style="border-bottom:2px solid #0f172a;padding-bottom:4px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:baseline;">
            <strong style="font-size:17px;letter-spacing:0.03em;">${d.title}</strong>
            <span style="font-size:10px;font-family:system-ui;">OCT 27 · EDITION</span>
          </div>
          <div style="font-size:12.5px;line-height:1.45;">${d.headline}</div>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;">
          <button class="btn btn-primary" style="flex:1;" data-action="send-widget-now">▶ Send to Frame Now</button>
          <button class="btn" style="flex:1;" data-action="schedule-widget">🗓 Add to Schedule</button>
        </div>
      </div>

      <!-- Template Picker -->
      <div style="font-size:12px;font-weight:700;color:#94a3b8;margin-bottom:8px;text-transform:uppercase;">Choose Widget Generator</div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;">
        ${[
          { type: 'newspaper', icon: '📰', title: 'Daily Newspaper', headline: 'Sunny 72°F · 3 family calendar events · Trash day tomorrow' },
          { type: 'agenda', icon: '📅', title: 'Morning Agenda', headline: '09:00 Design Review · 12:30 Lunch · 17:00 Soccer Practice' },
          { type: 'message', icon: '💬', title: 'Styled Banner Message', headline: 'Welcome Home! Dinner is in the oven — Love, Mom' },
          { type: 'quote', icon: '✨', title: 'Quote / Word of the Day', headline: '“Simplicity is about subtracting the obvious and adding the meaningful.”' },
        ].map((tpl) => `
          <div data-action="pick-widget-tpl" data-type="${tpl.type}" data-title="${tpl.title}" data-headline="${tpl.headline}"
               style="background:${d.type === tpl.type ? 'rgba(59,130,246,0.18)' : '#162032'};border:1px solid ${d.type === tpl.type ? '#3b82f6' : 'rgba(148,163,184,0.16)'};border-radius:12px;padding:12px;cursor:pointer;">
            <div style="font-size:20px;margin-bottom:4px;">${tpl.icon}</div>
            <div style="font-size:13px;font-weight:700;color:#f8fafc;">${tpl.title}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderSharedScheduleList() {
    return `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <span style="font-size:12.5px;color:#94a3b8;">Replaces the hidden 38px bookshelf calendar with a direct timeline:</span>
        <button class="btn btn-primary btn-sm" data-action="add-schedule-slot">＋ New Schedule</button>
      </div>
      ${state.schedules.map((s) => `
        <div style="background:#162032;border:1px solid rgba(148,163,184,0.16);border-radius:14px;padding:12px 14px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;gap:10px;">
          <div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-size:16px;font-weight:800;color:#60a5fa;font-variant-numeric:tabular-nums;">${s.time}</span>
              <span style="font-size:14px;font-weight:700;color:#f8fafc;">${s.label}</span>
            </div>
            <div style="font-size:12px;color:#94a3b8;margin-top:3px;">
              🎯 ${s.target} · 🔁 ${s.days}
            </div>
          </div>
          <button class="btn btn-sm ${s.enabled ? 'btn-primary' : ''}" data-action="toggle-schedule" data-sched="${s.id}">
            ${s.enabled ? 'ON' : 'PAUSED'}
          </button>
        </div>
      `).join('')}
    `;
  }

  function renderVariantADiscover() {
    return `
      <div style="font-size:13px;color:#94a3b8;margin-bottom:12px;">
        One-tap curated expansion packs install straight into your unified Library & Scenes.
      </div>
      ${[
        { id: 'pack_edo', title: 'Hokusai & Hiroshige Woodblocks', count: '24 high-contrast E-Ink plates', badge: 'Installed', img: 'img_waves' },
        { id: 'pack_botanical', title: 'Kew Gardens Vintage Botanicals', count: '18 portrait & landscape studies', badge: 'Installed', img: 'img_botanical' },
        { id: 'pack_nasa', title: 'NASA Astronomy Picture of the Day', count: 'Live daily cosmic feed widget', badge: '1-Tap Install', img: 'img_starry' },
      ].map((p) => `
        <div style="background:#162032;border:1px solid rgba(148,163,184,0.18);border-radius:16px;padding:12px;margin-bottom:12px;display:flex;gap:12px;align-items:center;">
          <img src="${imgThumb(p.img)}" style="width:76px;height:76px;border-radius:10px;object-fit:cover;flex:0 0 auto;" />
          <div style="flex:1;">
            <div style="font-size:14.5px;font-weight:700;color:#f8fafc;">${p.title}</div>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">${p.count}</div>
            <button class="btn btn-sm ${p.badge === 'Installed' ? '' : 'btn-primary'}" style="margin-top:8px;" data-action="install-pack" data-pack="${p.title}">
              ${p.badge === 'Installed' ? '✓ Installed in Library' : '⬇ Install Pack'}
            </button>
          </div>
        </div>
      `).join('')}
    `;
  }

  // -------------------------------------------------------------------------
  // Variant B: Spatial Wall Stage + Contextual Inspector Drawer
  // -------------------------------------------------------------------------
  function renderVariantB() {
    const wall = getActiveWall();
    const wallFrames = getWallFrames();
    const activeFrame = getFrame(state.selectedFrameIds[0] || wallFrames[0]?.entryId);
    const hasStaged = wallFrames.some((f) => f.stagedImageId);

    return `
      <div class="vb-shell">
        <!-- Compact Single-Row Workbench Top Bar -->
        <div style="padding:10px 14px;background:#0f172a;border-bottom:1px solid rgba(148,163,184,0.15);display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:11px;font-weight:800;color:#a855f7;text-transform:uppercase;">Variant B · Workbench</span>
            <select data-action="select-wall-dropdown" style="background:#1e293b;color:#f8fafc;border:1px solid rgba(148,163,184,0.3);border-radius:8px;padding:6px 10px;font-size:13px;font-weight:700;">
              ${state.walls.map((w) => `<option value="${w.wall_id}" ${w.wall_id === wall.wall_id ? 'selected' : ''}>🏠 ${w.name}</option>`).join('')}
            </select>
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-sm ${state.bMode === 'content' ? 'btn-primary' : ''}" data-action="set-b-mode" data-mode="content">🔒 Content Mode</button>
            <button class="btn btn-sm ${state.bMode === 'layout' ? 'btn-amber' : ''}" data-action="set-b-mode" data-mode="layout">📐 Layout Mode</button>
          </div>
        </div>

        <div class="vb-main">
          <!-- Always-Visible Spatial Wall Stage (Full width — no 160px left palette!) -->
          <div class="vb-stage">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap;">
              <div class="pill-row">
                ${wallFrames.map((f) => {
                  const isSel = state.selectedFrameIds.includes(f.entryId);
                  return `
                    <button class="pill ${isSel ? 'active' : ''}" data-action="select-frame" data-entry="${f.entryId}">
                      ${f.orientation === 'portrait' ? '▯' : '▭'} ${f.title} ${f.queuedImageId ? '⏳' : '🟢'}
                    </button>
                  `;
                }).join('')}
              </div>
              ${hasStaged ? `
                <div style="display:flex;gap:6px;">
                  <button class="btn btn-sm" data-action="clear-staged">Reset</button>
                  <button class="btn btn-primary btn-sm" data-action="commit-staged">▶ Push Staged Wall</button>
                </div>
              ` : ''}
            </div>

            <!-- Interactive Spatial Wall Canvas -->
            <div style="position:relative;height:215px;margin:10px 0;border-radius:12px;background:rgba(15,23,42,0.55);border:1px solid rgba(148,163,184,0.16);overflow:hidden;">
              ${state.wallpaperSpanImageId ? `
                <img src="${imgThumb(state.wallpaperSpanImageId)}" style="position:absolute;inset:12px;width:calc(100% - 24px);height:calc(100% - 24px);object-fit:cover;opacity:0.28;filter:blur(1px);pointer-events:none;" />
              ` : ''}
              ${wallFrames.map((f) => {
                const p = wall.placements[f.entryId] || { x: 20, y: 20, w: 120, h: 90 };
                const activeImgId = f.stagedImageId || f.queuedImageId || f.currentImageId;
                const isSel = state.selectedFrameIds.includes(f.entryId);
                return `
                  <div data-action="select-frame" data-entry="${f.entryId}"
                       style="position:absolute;left:${Math.round(p.x * 0.82)}px;top:${Math.round(p.y * 0.9)}px;width:${Math.round(p.w * 0.85)}px;height:${Math.round(p.h * 0.85)}px;background:#f8fafc;padding:4px;border-radius:6px;cursor:pointer;transition:all 0.15s;box-shadow:0 10px 25px rgba(0,0,0,0.6);outline:${isSel ? '3px solid #3b82f6' : 'none'};">
                    <img src="${imgThumb(activeImgId)}" style="width:100%;height:100%;object-fit:cover;border-radius:2px;" />
                    <div style="position:absolute;top:-22px;left:0;background:${isSel ? '#2563eb' : 'rgba(15,23,42,0.85)'};color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;white-space:nowrap;">
                      ${f.title} ${f.queuedImageId ? '· ⏳' : ''}
                    </div>
                  </div>
                `;
              }).join('')}
            </div>

            <!-- Selected Frame Bar right under the Stage -->
            <div style="background:rgba(30,41,59,0.75);border-radius:10px;padding:8px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
              <div style="font-size:12.5px;">
                <strong>Inspecting:</strong> <span style="color:#60a5fa;font-weight:700;">${activeFrame.title}</span>
                <span style="color:#94a3b8;margin-left:6px;">(${activeFrame.width}×${activeFrame.height} · ${activeFrame.online ? '🟢 Online' : `💤 Wakes in ${activeFrame.wakeInMinutes}m`})</span>
              </div>
              ${state.bMode === 'layout' ? `
                <div style="display:flex;gap:4px;">
                  <button class="btn btn-sm" data-action="nudge-frame" data-dx="-14" data-dy="0">←</button>
                  <button class="btn btn-sm" data-action="nudge-frame" data-dx="14" data-dy="0">→</button>
                  <button class="btn btn-sm" data-action="nudge-frame" data-dx="0" data-dy="-10">↑</button>
                  <button class="btn btn-sm" data-action="nudge-frame" data-dx="0" data-dy="10">↓</button>
                  <button class="btn btn-sm" data-action="auto-align-wall">Align Row</button>
                </div>
              ` : `
                <button class="btn btn-primary btn-sm" data-action="open-crop-sheet" data-image="${activeFrame.stagedImageId || activeFrame.queuedImageId || activeFrame.currentImageId}" data-entry="${activeFrame.entryId}">
                  ✂ Fine-Tune Crop & Send
                </button>
              `}
            </div>
          </div>

          <!-- Contextual Bottom / Side Inspector Drawer (Never leaves the Wall!) -->
          <div class="vb-drawer">
            <div class="pill-row" style="padding:10px 14px;border-bottom:1px solid rgba(148,163,184,0.14);background:#0f172a;">
              <button class="pill ${state.bDrawerTab === 'library' ? 'active' : ''}" data-action="b-drawer-tab" data-tab="library">🖼 Assign Art</button>
              <button class="pill ${state.bDrawerTab === 'scenes' ? 'active' : ''}" data-action="b-drawer-tab" data-tab="scenes">🎬 Wall Scenes</button>
              <button class="pill ${state.bDrawerTab === 'widgets' ? 'active' : ''}" data-action="b-drawer-tab" data-tab="widgets">🧩 Widgets</button>
              <button class="pill ${state.bDrawerTab === 'schedule' ? 'active' : ''}" data-action="b-drawer-tab" data-tab="schedule">🗓 Schedules</button>
              <button class="pill ${state.bDrawerTab === 'config' ? 'active' : ''}" data-action="b-drawer-tab" data-tab="config">⚙ Device</button>
            </div>

            <div style="padding:14px;overflow-y:auto;flex:1;">
              ${state.bDrawerTab === 'library' ? `
                <div style="font-size:12px;color:#94a3b8;margin-bottom:10px;">
                  Tap any photo below to stage it directly onto <strong style="color:#f8fafc;">${activeFrame.title}</strong> on the Wall Stage above:
                </div>
                <div class="photo-grid">
                  ${state.images.map((img) => `
                    <div class="photo-tile" data-action="stage-photo-on-selected" data-image="${img.image_id}">
                      <img src="${imgThumb(img.image_id)}" alt="${img.title}" />
                      <div class="photo-tile-caption">${img.title}</div>
                    </div>
                  `).join('')}
                </div>
              ` : ''}

              ${state.bDrawerTab === 'scenes' ? `
                <div style="font-size:12px;color:#94a3b8;margin-bottom:10px;">
                  Stage a multi-frame scene or span a single panoramic photo across all frames on <strong>${wall.name}</strong>:
                </div>
                ${state.scenes.map((sc) => `
                  <div data-action="stage-scene" data-scene="${sc.scene_id}"
                       style="background:#1e293b;border:1px solid ${state.activeSceneId === sc.scene_id ? '#3b82f6' : 'rgba(148,163,184,0.2)'};border-radius:12px;padding:12px;margin-bottom:8px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;">
                    <div>
                      <div style="font-size:14px;font-weight:700;color:#f8fafc;">${sc.kind === 'wallpaper' ? '🖼 Panorama Span:' : '🎬 Scene:'} ${sc.name}</div>
                      <div style="font-size:11.5px;color:#94a3b8;margin-top:2px;">Covers ${Object.keys(sc.mappings).length} frames on this wall</div>
                    </div>
                    <span class="btn btn-sm">Stage →</span>
                  </div>
                `).join('')}
                <button class="btn btn-primary" style="width:100%;margin-top:6px;" data-action="save-scene-modal">💾 Save Current Wall as New Scene</button>
              ` : ''}

              ${state.bDrawerTab === 'widgets' ? renderSharedWidgetStudio() : ''}
              ${state.bDrawerTab === 'schedule' ? renderSharedScheduleList() : ''}
              ${state.bDrawerTab === 'config' ? renderInlineFrameConfig(activeFrame) : ''}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Variant C: Channel Stream & Broadcast Timeline (Playlist / Media Controller)
  // -------------------------------------------------------------------------
  function renderVariantC() {
    const channelFrame = state.cChannelId === 'all'
      ? state.frames[0]
      : getFrame(state.cChannelId);
    const currentImg = getImage(channelFrame.currentImageId);
    const queuedImg = channelFrame.queuedImageId ? getImage(channelFrame.queuedImageId) : null;

    return `
      <div class="vc-shell">
        <!-- Channel Strip Header -->
        <div style="padding:12px 16px;background:#0f172a;border-bottom:1px solid rgba(148,163,184,0.15);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <div>
              <span style="font-size:10.5px;font-weight:800;color:#34d399;text-transform:uppercase;letter-spacing:0.08em;">Variant C · Live Channel Stream</span>
              <div style="font-size:17px;font-weight:800;color:#f8fafc;">Now Playing & Broadcast Queue</div>
            </div>
            <button class="btn btn-primary btn-sm" data-action="quick-send">＋ Push Art</button>
          </div>
          <div class="pill-row">
            <button class="pill ${state.cChannelId === 'all' ? 'active' : ''}" data-action="c-channel" data-channel="all">📡 All Frames (${state.frames.length})</button>
            ${state.frames.map((f) => `
              <button class="pill ${state.cChannelId === f.entryId ? 'active' : ''}" data-action="c-channel" data-channel="${f.entryId}">
                ${f.online ? '🟢' : '💤'} ${f.title}
              </button>
            `).join('')}
          </div>
        </div>

        <div style="padding:14px 16px;">
          <!-- Lane 1: Now Playing + On-Deck Hero Stage -->
          <div style="background:linear-gradient(145deg, #162032 0%, #0f172a 100%);border:1px solid rgba(148,163,184,0.2);border-radius:18px;padding:16px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
              <div>
                <span class="status-badge status-live">🟢 LIVE ON E-INK</span>
                <span style="font-size:12px;color:#94a3b8;margin-left:6px;">${channelFrame.title} (${channelFrame.size})</span>
              </div>
              <button class="btn btn-sm" data-action="open-frame-config" data-entry="${channelFrame.entryId}">⚙ Frame Health</button>
            </div>

            <div style="display:grid;grid-template-columns:${queuedImg ? '1fr 1fr' : '1fr'};gap:12px;align-items:center;">
              <div style="text-align:center;">
                <div class="bezel-wrap" style="width:100%;max-width:210px;aspect-ratio:${channelFrame.orientation === 'portrait' ? '3/5' : '4/3'};">
                  <img src="${imgThumb(currentImg.image_id)}" alt="${currentImg.title}" />
                </div>
                <div style="font-size:13px;font-weight:700;margin-top:6px;">Now: ${currentImg.title}</div>
              </div>

              ${queuedImg ? `
                <div style="text-align:center;background:rgba(245,158,11,0.08);border:1px dashed rgba(245,158,11,0.45);border-radius:12px;padding:10px;">
                  <div class="status-badge status-deck" style="margin-bottom:6px;">⏳ ON DECK (${channelFrame.wakeInMinutes}m)</div>
                  <div class="bezel-wrap" style="width:100%;max-width:165px;aspect-ratio:${channelFrame.orientation === 'portrait' ? '3/5' : '4/3'};">
                    <img src="${imgThumb(queuedImg.image_id)}" alt="${queuedImg.title}" />
                  </div>
                  <div style="font-size:12.5px;font-weight:700;color:#fcd34d;margin-top:6px;">Next: ${queuedImg.title}</div>
                </div>
              ` : ''}
            </div>

            <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;">
              <button class="btn btn-primary" style="flex:1;" data-action="open-crop-sheet" data-image="${(queuedImg || currentImg).image_id}" data-entry="${channelFrame.entryId}">
                ✂ Adjust Crop / Send New
              </button>
              <button class="btn" data-action="voice-simulate">🗣 Test Voice ("Show Red Fuji")</button>
            </div>
          </div>

          <!-- Lane 2: 24-Hour Broadcast Ribbon Timeline -->
          <div style="margin-bottom:18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
              <span style="font-size:12px;font-weight:800;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;">🗓 24-Hour Broadcast Timeline</span>
              <button class="btn btn-sm" data-action="add-schedule-slot">＋ Add Time Slot</button>
            </div>
            <div class="vc-timeline-track">
              ${state.schedules.map((s) => `
                <div class="vc-slot ${s.enabled ? 'enabled' : ''}" data-action="toggle-schedule" data-sched="${s.id}">
                  <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-size:15px;font-weight:800;color:#60a5fa;">${s.time}</span>
                    <span style="font-size:10px;padding:2px 6px;border-radius:99px;background:${s.enabled ? 'rgba(16,185,129,0.2)' : 'rgba(148,163,184,0.15)'};color:${s.enabled ? '#34d399' : '#94a3b8'};">${s.enabled ? 'ACTIVE' : 'OFF'}</span>
                  </div>
                  <div style="font-size:12.5px;font-weight:700;color:#f8fafc;margin-top:6px;">${s.label}</div>
                  <div style="font-size:11px;color:#94a3b8;margin-top:3px;">${s.target}</div>
                </div>
              `).join('')}
            </div>
          </div>

          <!-- Lane 3: Horizontal Content Swimlanes (Scenes, Library, Widgets) -->
          <div style="margin-bottom:16px;">
            <div style="font-size:12px;font-weight:800;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">
              🎬 One-Tap Wall Scenes & Spanning Panoramas
            </div>
            <div class="pill-row">
              ${state.scenes.map((sc) => `
                <button class="pill" data-action="stage-and-commit-scene" data-scene="${sc.scene_id}">
                  ${sc.kind === 'wallpaper' ? '🖼' : '🎬'} ${sc.name} · Play Now ▶
                </button>
              `).join('')}
            </div>
          </div>

          <div style="margin-bottom:16px;">
            <div style="font-size:12px;font-weight:800;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">
              📚 Library Stream (Tap to Crop & Queue on ${channelFrame.title})
            </div>
            <div class="photo-grid">
              ${state.images.map((img) => `
                <div class="photo-tile" data-action="open-crop-sheet" data-image="${img.image_id}" data-entry="${channelFrame.entryId}">
                  <img src="${imgThumb(img.image_id)}" alt="${img.title}" />
                  <div class="photo-tile-caption">${img.title}</div>
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Shared Modals & Bottom Sheets (Fixing the 8-Button Crop Stack & window.prompt)
  // -------------------------------------------------------------------------
  function renderCropAndInspectorSheet() {
    if (!state.cropSheet) return '';
    const cs = state.cropSheet;
    const img = getImage(cs.imageId);
    const targetFrame = getFrame(cs.targetFrameId);

    return `
      <div class="sheet-backdrop" data-action="close-modals-backdrop">
        <div class="sheet-card">
          <div class="sheet-handle"></div>
          <!-- Compact Header (Replaces 8-button vertical stack!) -->
          <div style="padding:8px 16px 12px;border-bottom:1px solid rgba(148,163,184,0.16);display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <button class="btn btn-sm" data-action="close-crop-sheet">✕ Close</button>
            <div style="text-align:center;min-width:0;">
              <div style="font-size:14px;font-weight:800;color:#f8fafc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${img.title}</div>
              <div style="font-size:11px;color:#60a5fa;">Target: ${targetFrame.title} (${targetFrame.width}×${targetFrame.height})</div>
            </div>
            <button class="btn btn-primary btn-sm" data-action="confirm-crop-send">
              ${targetFrame.online ? '▶ Send Now' : '⏳ Queue On Deck'}
            </button>
          </div>

          <!-- In-Modal Target Frame Switcher Pill Bar -->
          <div class="pill-row" style="padding:10px 16px;background:#0b1120;border-bottom:1px solid rgba(148,163,184,0.12);">
            ${state.frames.map((f) => `
              <button class="pill ${f.entryId === cs.targetFrameId ? 'active' : ''}" data-action="crop-switch-frame" data-entry="${f.entryId}">
                ${f.orientation === 'portrait' ? '▯' : '▭'} ${f.title}
              </button>
            `).join('')}
          </div>

          <!-- Center Stage (Generous height, 44x44px touch targets) -->
          <div style="padding:16px;overflow-y:auto;flex:1;">
            ${cs.tab === 'crop' ? `
              <div style="display:flex;flex-direction:column;align-items:center;">
                <div style="font-size:11.5px;color:#94a3b8;margin-bottom:8px;">
                  Pinch/Zoom or use 44×44px corner handles · Frame Bezel Aspect: <strong>${cs.aspect.toUpperCase()}</strong>
                </div>
                <div class="bezel-wrap" style="width:${cs.aspect === 'portrait' ? '185px' : '275px'};height:${cs.aspect === 'portrait' ? '260px' : '195px'};overflow:hidden;">
                  <img src="${imgThumb(img.image_id)}" style="transform:scale(${cs.zoom}) translate(${cs.panX}px, ${cs.panY}px);transition:transform 0.12s;" />
                  <!-- 44x44px Touch Corner Targets -->
                  <div style="position:absolute;top:4px;left:4px;width:44px;height:44px;border-top:4px solid #3b82f6;border-left:4px solid #3b82f6;border-radius:4px;pointer-events:none;"></div>
                  <div style="position:absolute;top:4px;right:4px;width:44px;height:44px;border-top:4px solid #3b82f6;border-right:4px solid #3b82f6;border-radius:4px;pointer-events:none;"></div>
                  <div style="position:absolute;bottom:4px;left:4px;width:44px;height:44px;border-bottom:4px solid #3b82f6;border-left:4px solid #3b82f6;border-radius:4px;pointer-events:none;"></div>
                  <div style="position:absolute;bottom:4px;right:4px;width:44px;height:44px;border-bottom:4px solid #3b82f6;border-right:4px solid #3b82f6;border-radius:4px;pointer-events:none;"></div>
                </div>

                <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;justify-content:center;">
                  <button class="btn btn-sm" data-action="crop-zoom" data-delta="-0.15">🔍 − Zoom Out</button>
                  <button class="btn btn-sm" data-action="crop-zoom" data-delta="0.15">🔍 ＋ Zoom In (${cs.zoom.toFixed(2)}×)</button>
                  <button class="btn btn-sm" data-action="crop-toggle-aspect">🔄 Flip Landscape/Portrait</button>
                </div>
              </div>
            ` : ''}

            ${cs.tab === 'voice' ? `
              <div style="display:flex;flex-direction:column;gap:12px;">
                <label style="font-size:12.5px;color:#cbd5e1;">
                  🗣 <strong>Voice Assistant Name</strong> (Say <em>"Hey Google/Assist, show ${img.voiceName}"</em>)
                  <input type="text" id="crop-voice-input" value="${img.voiceName}"
                         style="width:100%;margin-top:6px;padding:10px;border-radius:10px;background:#1e293b;border:1px solid rgba(148,163,184,0.3);color:#fff;font-size:14px;" />
                </label>
                <label style="font-size:12.5px;color:#cbd5e1;">
                  🏷 <strong>Search Tags</strong> (comma-separated)
                  <input type="text" id="crop-tags-input" value="${img.tags.join(', ')}"
                         style="width:100%;margin-top:6px;padding:10px;border-radius:10px;background:#1e293b;border:1px solid rgba(148,163,184,0.3);color:#fff;font-size:14px;" />
                </label>
                <button class="btn btn-primary" data-action="save-photo-metadata">💾 Save Voice Name & Tags</button>
              </div>
            ` : ''}

            ${cs.tab === 'albums' ? `
              <div style="font-size:12.5px;color:#94a3b8;margin-bottom:10px;">Tap an album chip to toggle membership for <strong>${img.title}</strong>:</div>
              <div style="display:flex;flex-wrap:wrap;gap:8px;">
                ${state.albums.map((a) => {
                  const inAlbum = img.albums.includes(a.name);
                  return `
                    <button class="pill ${inAlbum ? 'active' : ''}" data-action="toggle-photo-album" data-album="${a.name}">
                      ${inAlbum ? '✓' : '＋'} 📁 ${a.name}
                    </button>
                  `;
                }).join('')}
              </div>
            ` : ''}
          </div>

          <!-- Compact 3-Segment Bottom Bar (Replaces 8 full-width buttons!) -->
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:10px 16px 16px;background:#0b1120;border-top:1px solid rgba(148,163,184,0.15);">
            <button class="btn btn-sm ${cs.tab === 'crop' ? 'btn-primary' : ''}" data-action="crop-tab" data-tab="crop">✂ Crop & Frame</button>
            <button class="btn btn-sm ${cs.tab === 'voice' ? 'btn-primary' : ''}" data-action="crop-tab" data-tab="voice">🗣 Voice & Tags</button>
            <button class="btn btn-sm ${cs.tab === 'albums' ? 'btn-primary' : ''}" data-action="crop-tab" data-tab="albums">📁 Albums (${img.albums.length})</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderInlineFrameConfig(frame) {
    return `
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div style="background:#1e293b;border-radius:12px;padding:12px;">
          <div style="font-size:13.5px;font-weight:700;color:#f8fafc;">${frame.title}</div>
          <div style="font-size:12px;color:#94a3b8;margin-top:2px;">
            Host: ${frame.host} · Driver: ${frame.driver.toUpperCase()} · ${frame.battery !== null ? `Battery: ${frame.battery}%` : 'AC Powered'}
          </div>
        </div>

        <div>
          <div style="font-size:12px;font-weight:700;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;">Orientation Lock (KPF 4b)</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;">
            ${[
              { mode: 'auto', label: '🔄 Auto (G-Sensor)' },
              { mode: 'landscape', label: '▭ Landscape' },
              { mode: 'portrait', label: '▯ Portrait' },
            ].map((o) => `
              <button class="btn btn-sm ${frame.orientationMode === o.mode ? 'btn-primary' : ''}"
                      data-action="set-frame-orientation" data-entry="${frame.entryId}" data-orient="${o.mode}">
                ${o.label}
              </button>
            `).join('')}
          </div>
        </div>

        <div>
          <div style="font-size:12px;font-weight:700;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;">Deep Sleep Wake Interval</div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;">
            ${[15, 30, 60, 360].map((mins) => `
              <button class="btn btn-sm ${frame.sleepMinutes === mins ? 'btn-primary' : ''}"
                      data-action="set-frame-sleep" data-entry="${frame.entryId}" data-mins="${mins}">
                ${mins < 60 ? `${mins}m` : `${mins / 60}h`}
              </button>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  }

  function renderFrameConfigSheet() {
    if (!state.frameConfigSheet) return '';
    const frame = getFrame(state.frameConfigSheet);
    return `
      <div class="sheet-backdrop" data-action="close-modals-backdrop">
        <div class="sheet-card">
          <div class="sheet-handle"></div>
          <div style="padding:10px 16px 12px;border-bottom:1px solid rgba(148,163,184,0.16);display:flex;justify-content:space-between;align-items:center;">
            <strong style="font-size:15px;">⚙ Device Settings · ${frame.title}</strong>
            <button class="btn btn-sm" data-action="close-frame-config">Done</button>
          </div>
          <div style="padding:16px;overflow-y:auto;">
            ${renderInlineFrameConfig(frame)}
          </div>
        </div>
      </div>
    `;
  }

  function renderPromptModal() {
    if (!state.promptModal) return '';
    return `
      <div class="sheet-backdrop" data-action="close-modals-backdrop">
        <div class="sheet-card" style="max-width:420px;border-radius:20px;margin:auto;">
          <div style="padding:16px;">
            <div style="font-size:15px;font-weight:800;color:#f8fafc;margin-bottom:6px;">${state.promptModal.title}</div>
            <div style="font-size:12px;color:#94a3b8;margin-bottom:10px;">${state.promptModal.label} (Replaces browser window.prompt!)</div>
            <input type="text" id="proto-prompt-input" value="${state.promptModal.value}"
                   style="width:100%;padding:10px 12px;border-radius:10px;background:#1e293b;border:1px solid #3b82f6;color:#fff;font-size:14px;margin-bottom:12px;" />
            <div style="display:flex;justify-content:flex-end;gap:8px;">
              <button class="btn btn-sm" data-action="close-prompt">Cancel</button>
              <button class="btn btn-primary btn-sm" data-action="confirm-prompt">Save</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Floating Prototype Switcher & Live State Inspector (Required by UI.md)
  // -------------------------------------------------------------------------
  function renderPrototypeSwitcher() {
    const current = VARIANTS.find((v) => v.key === state.variant) || VARIANTS[0];
    const snapshot = {
      variant: `${current.key} (${current.name})`,
      viewport: state.viewport,
      lastAction: state.lastAction,
      activeWall: state.activeWallId,
      selectedFrames: state.selectedFrameIds,
      framesStatus: state.frames.map((f) => ({
        title: f.title,
        showing: f.currentImageId,
        onDeck: f.queuedImageId,
        staged: f.stagedImageId,
        orientationMode: f.orientationMode,
      })),
      batchSelectedPhotos: state.batchSelectedPhotos,
      activeSchedules: state.schedules.filter((s) => s.enabled).map((s) => `${s.time} ${s.label}`),
    };

    return `
      <div class="proto-switcher-wrap">
        ${state.stateInspectorOpen ? `
          <pre class="proto-state-drawer">${ JSON.stringify(snapshot, null, 2) }</pre>
        ` : ''}
        <div class="proto-state-pill" data-action="toggle-state-inspector" title="Click to expand full live state JSON">
          ⚡ <strong>State:</strong> ${state.lastAction} <span style="opacity:0.75;">(${state.stateInspectorOpen ? '▼ Hide JSON' : '▲ Inspect State'})</span>
        </div>
        <div class="proto-bar">
          <button data-action="prev-variant" title="Previous Variant (←)">←</button>
          <span style="padding:0 6px;color:#fcd34d;">
            ${current.key} (${current.name})
          </span>
          <button data-action="next-variant" title="Next Variant (→)">→</button>
          <span style="opacity:0.35;">|</span>
          <button data-action="toggle-viewport" title="Switch between 390px Phone Bezel and Full-Width Desktop">
            ${state.viewport === 'mobile' ? '📱 Mobile 390px' : '🖥 Desktop Full'}
          </button>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Mount & Event Delegation
  // -------------------------------------------------------------------------
  let protoContainer = null;

  function render() {
    if (!protoContainer) return;
    const currentVariant = VARIANTS.find((v) => v.key === state.variant) || VARIANTS[0];
    protoContainer.innerHTML = `
      <style>${PROTO_CSS}</style>
      <div class="proto-outer ${state.viewport === 'mobile' ? 'vp-mobile' : 'vp-desktop'}">
        <div class="proto-device-frame">
          ${currentVariant.fn()}
          ${renderCropAndInspectorSheet()}
          ${renderFrameConfigSheet()}
          ${renderPromptModal()}
        </div>
      </div>
      ${renderPrototypeSwitcher()}
    `;
  }

  function handleAction(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;

    if (action === 'prev-variant') { e.stopPropagation(); cycleVariant(-1); return; }
    if (action === 'next-variant') { e.stopPropagation(); cycleVariant(1); return; }
    if (action === 'toggle-viewport') {
      e.stopPropagation();
      state.viewport = state.viewport === 'mobile' ? 'desktop' : 'mobile';
      state.lastAction = `Switched viewport preview to ${state.viewport.toUpperCase()}`;
      const u = new URL(window.location.href);
      u.searchParams.set('vp', state.viewport);
      window.history.replaceState({}, '', u.toString());
      render();
      return;
    }
    if (action === 'toggle-state-inspector') {
      state.stateInspectorOpen = !state.stateInspectorOpen;
      render();
      return;
    }

    // Variant A navigation
    if (action === 'a-tab') {
      state.aTab = btn.dataset.tab;
      state.lastAction = `Navigated to Variant A tab: ${state.aTab}`;
      render();
      return;
    }
    if (action === 'auto-subtab') {
      state.aAutoSubTab = btn.dataset.sub;
      state.lastAction = `Switched Automations view to ${state.aAutoSubTab}`;
      render();
      return;
    }
    if (action === 'toggle-a-layout') {
      state.aWallLayoutEdit = !state.aWallLayoutEdit;
      state.lastAction = state.aWallLayoutEdit ? 'Unlocked Wall Layout Edit Mode' : 'Locked Wall Layout (Content Mode)';
      render();
      return;
    }

    // Variant B navigation
    if (action === 'set-b-mode') {
      state.bMode = btn.dataset.mode;
      state.lastAction = `Switched Variant B Workbench to ${state.bMode.toUpperCase()} mode`;
      render();
      return;
    }
    if (action === 'b-drawer-tab') {
      state.bDrawerTab = btn.dataset.tab;
      state.lastAction = `Switched Contextual Inspector Drawer to ${state.bDrawerTab}`;
      render();
      return;
    }
    if (action === 'stage-photo-on-selected') {
      const f = getFrame(state.selectedFrameIds[0]);
      const img = getImage(btn.dataset.image);
      f.stagedImageId = img.image_id;
      state.lastAction = `Staged "${img.title}" onto ${f.title} on Wall Stage`;
      render();
      return;
    }

    // Variant C navigation
    if (action === 'c-channel') {
      state.cChannelId = btn.dataset.channel;
      if (state.cChannelId !== 'all') state.selectedFrameIds = [state.cChannelId];
      state.lastAction = `Tuned Channel Stream to ${state.cChannelId === 'all' ? 'All Frames' : getFrame(state.cChannelId).title}`;
      render();
      return;
    }
    if (action === 'stage-and-commit-scene') {
      stageSceneOnWall(btn.dataset.scene);
      commitStagedWall();
      return;
    }
    if (action === 'voice-simulate') {
      const target = state.cChannelId === 'all' ? state.frames[0] : getFrame(state.cChannelId);
      sendImageToFrame('img_fuji', target.entryId);
      state.lastAction = `Voice command "Show Red Fuji" matched img_fuji → pushed to ${target.title}`;
      render();
      return;
    }

    // Shared Wall & Frame actions
    if (action === 'select-wall') {
      state.activeWallId = btn.dataset.wall;
      state.lastAction = `Selected wall "${getActiveWall().name}"`;
      render();
      return;
    }
    if (action === 'select-wall-dropdown') {
      return; // handled by change listener
    }
    if (action === 'select-frame') {
      const entryId = btn.dataset.entry;
      state.selectedFrameIds = [entryId];
      state.lastAction = `Selected frame "${getFrame(entryId).title}"`;
      render();
      return;
    }
    if (action === 'nudge-frame') {
      const wall = getActiveWall();
      const entryId = state.selectedFrameIds[0];
      const p = wall.placements[entryId];
      if (p) {
        p.x = Math.max(4, p.x + parseInt(btn.dataset.dx, 10));
        p.y = Math.max(4, p.y + parseInt(btn.dataset.dy, 10));
        state.lastAction = `Nudged ${getFrame(entryId).title} to (${p.x}, ${p.y})`;
        render();
      }
      return;
    }
    if (action === 'auto-align-wall') {
      const wall = getActiveWall();
      let x = 18;
      for (const id of Object.keys(wall.placements)) {
        wall.placements[id].x = x;
        wall.placements[id].y = 28;
        x += wall.placements[id].w + 16;
      }
      state.lastAction = `Auto-aligned all frames horizontally on "${wall.name}"`;
      render();
      return;
    }
    if (action === 'stage-scene') {
      stageSceneOnWall(btn.dataset.scene);
      return;
    }
    if (action === 'commit-staged') {
      commitStagedWall();
      return;
    }
    if (action === 'clear-staged') {
      clearStagedWall();
      return;
    }

    // Crop & Quick-Send Sheet actions (Flow 1)
    if (action === 'quick-send' || action === 'open-picker-for-frame') {
      const entryId = btn.dataset.entry || state.selectedFrameIds[0] || state.frames[0].entryId;
      const f = getFrame(entryId);
      openCropSheet(f.stagedImageId || f.queuedImageId || f.currentImageId, entryId, 'crop');
      return;
    }
    if (action === 'open-crop-sheet') {
      e.stopPropagation();
      openCropSheet(btn.dataset.image, btn.dataset.entry || state.selectedFrameIds[0], 'crop');
      return;
    }
    if (action === 'close-crop-sheet') {
      state.cropSheet = null;
      state.lastAction = 'Closed Crop & Inspector sheet';
      render();
      return;
    }
    if (action === 'crop-switch-frame') {
      if (state.cropSheet) {
        const f = getFrame(btn.dataset.entry);
        state.cropSheet.targetFrameId = f.entryId;
        state.cropSheet.aspect = f.orientation;
        state.lastAction = `Switched Crop target frame to ${f.title} (${f.orientation})`;
        render();
      }
      return;
    }
    if (action === 'crop-zoom') {
      if (state.cropSheet) {
        const next = Math.min(2.2, Math.max(0.85, state.cropSheet.zoom + parseFloat(btn.dataset.delta)));
        state.cropSheet.zoom = next;
        state.lastAction = `Adjusted bezel crop zoom to ${next.toFixed(2)}x`;
        render();
      }
      return;
    }
    if (action === 'crop-toggle-aspect') {
      if (state.cropSheet) {
        state.cropSheet.aspect = state.cropSheet.aspect === 'portrait' ? 'landscape' : 'portrait';
        state.lastAction = `Previewing ${state.cropSheet.aspect} aspect mask`;
        render();
      }
      return;
    }
    if (action === 'crop-tab') {
      if (state.cropSheet) {
        state.cropSheet.tab = btn.dataset.tab;
        render();
      }
      return;
    }
    if (action === 'confirm-crop-send') {
      if (state.cropSheet) {
        sendImageToFrame(state.cropSheet.imageId, state.cropSheet.targetFrameId, { zoom: state.cropSheet.zoom.toFixed(2) });
      }
      return;
    }
    if (action === 'save-photo-metadata') {
      if (state.cropSheet) {
        const img = getImage(state.cropSheet.imageId);
        const vInput = protoContainer.querySelector('#crop-voice-input');
        const tInput = protoContainer.querySelector('#crop-tags-input');
        if (vInput) img.voiceName = vInput.value.trim();
        if (tInput) img.tags = tInput.value.split(',').map((s) => s.trim()).filter(Boolean);
        state.lastAction = `Saved voice name "${img.voiceName}" & tags for "${img.title}"`;
        render();
      }
      return;
    }
    if (action === 'toggle-photo-album') {
      if (state.cropSheet) {
        const img = getImage(state.cropSheet.imageId);
        const album = btn.dataset.album;
        if (img.albums.includes(album)) {
          img.albums = img.albums.filter((a) => a !== album);
          state.lastAction = `Removed "${img.title}" from album "${album}"`;
        } else {
          img.albums.push(album);
          state.lastAction = `Added "${img.title}" to album "${album}"`;
        }
        render();
      }
      return;
    }

    // Library & Batch Multi-Select actions (Flow 3)
    if (action === 'lib-filter') {
      state.libraryFilter = btn.dataset.filter;
      state.selectedAlbum = null;
      state.lastAction = `Filtered library by "${state.libraryFilter}"`;
      render();
      return;
    }
    if (action === 'lib-album') {
      state.selectedAlbum = state.selectedAlbum === btn.dataset.album ? null : btn.dataset.album;
      state.lastAction = state.selectedAlbum ? `Opened album "${state.selectedAlbum}"` : 'Cleared album filter';
      render();
      return;
    }
    if (action === 'toggle-batch-photo') {
      e.stopPropagation();
      const id = btn.dataset.image;
      if (state.batchSelectedPhotos.includes(id)) {
        state.batchSelectedPhotos = state.batchSelectedPhotos.filter((x) => x !== id);
      } else {
        state.batchSelectedPhotos.push(id);
      }
      state.lastAction = `Batch selection: ${state.batchSelectedPhotos.length} photo(s) selected`;
      render();
      return;
    }
    if (action === 'batch-send-wall') {
      const wf = getWallFrames();
      state.batchSelectedPhotos.forEach((imgId, i) => {
        const target = wf[i % wf.length];
        if (target) target.stagedImageId = imgId;
      });
      state.batchSelectedPhotos = [];
      state.aTab = 'walls';
      state.lastAction = 'Distributed selected photos across wall frames';
      render();
      return;
    }
    if (action === 'batch-add-favorites') {
      state.batchSelectedPhotos.forEach((imgId) => {
        const img = getImage(imgId);
        if (img && !img.albums.includes('Favorites')) img.albums.push('Favorites');
      });
      state.lastAction = `Added ${state.batchSelectedPhotos.length} photo(s) to Favorites`;
      state.batchSelectedPhotos = [];
      render();
      return;
    }
    if (action === 'batch-clear') {
      state.batchSelectedPhotos = [];
      state.lastAction = 'Cleared batch photo selection';
      render();
      return;
    }
    if (action === 'simulate-upload') {
      const newId = `img_upload_${state.images.length + 1}`;
      ARTWORK_SVGS[newId] = svgDataUri('#1e3a8a', '#0ea5e9', '#fde047', `Camera Roll Photo #${state.images.length + 1}`, 'portrait', '📸');
      state.images.unshift({
        image_id: newId,
        title: `Camera Roll Photo #${state.images.length + 1}`,
        voiceName: `camera photo ${state.images.length + 1}`,
        tags: ['upload', 'phone'],
        albums: ['Favorites'],
        orientation: 'portrait',
        curated: false,
      });
      openCropSheet(newId, state.selectedFrameIds[0], 'crop');
      return;
    }

    // Widgets & Schedules (Flow 4)
    if (action === 'pick-widget-tpl') {
      state.activeWidgetDraft = {
        type: btn.dataset.type,
        title: btn.dataset.title,
        headline: btn.dataset.headline,
      };
      state.lastAction = `Selected widget template "${btn.dataset.title}"`;
      render();
      return;
    }
    if (action === 'send-widget-now') {
      const f = getFrame(state.selectedFrameIds[0]);
      const widId = `img_wid_${Date.now()}`;
      ARTWORK_SVGS[widId] = svgDataUri('#1e293b', '#334155', '#38bdf8', state.activeWidgetDraft.title, f.orientation, '📰');
      state.images.unshift({
        image_id: widId,
        title: state.activeWidgetDraft.title,
        voiceName: state.activeWidgetDraft.title.toLowerCase(),
        tags: ['widget'],
        albums: [],
        orientation: f.orientation,
        curated: false,
      });
      sendImageToFrame(widId, f.entryId);
      return;
    }
    if (action === 'schedule-widget' || action === 'add-schedule-slot') {
      state.schedules.push({
        id: `sched_${state.schedules.length + 1}`,
        time: '20:00',
        label: state.activeWidgetDraft.title,
        target: getFrame(state.selectedFrameIds[0]).title,
        days: 'Every day',
        enabled: true,
        kind: 'widget',
      });
      state.aAutoSubTab = 'schedules';
      state.lastAction = `Added "${state.activeWidgetDraft.title}" at 20:00 to Schedule Timeline`;
      render();
      return;
    }
    if (action === 'toggle-schedule') {
      const s = state.schedules.find((x) => x.id === btn.dataset.sched);
      if (s) {
        s.enabled = !s.enabled;
        state.lastAction = `${s.enabled ? 'Enabled' : 'Paused'} schedule "${s.time} ${s.label}"`;
        render();
      }
      return;
    }

    // Onboarding & Frame Settings (Flow 5)
    if (action === 'adopt-discovered') {
      const d = state.discoveredUnconfigured.shift();
      if (d) {
        const newEntryId = 'entry_bedroom_east';
        state.frames.push({
          entryId: newEntryId,
          title: d.title,
          size: d.size,
          width: 800,
          height: 480,
          orientation: 'landscape',
          orientationMode: 'auto',
          battery: 96,
          online: true,
          wakeInMinutes: 0,
          sleepMinutes: 60,
          host: d.host,
          driver: 'fraimic',
          currentImageId: 'img_fuji',
          queuedImageId: null,
          stagedImageId: null,
        });
        getActiveWall().placements[newEntryId] = { x: 180, y: 80, w: 96, h: 68 };
        state.lastAction = `Adopted discovered frame "${d.title}" onto ${getActiveWall().name}`;
        render();
      }
      return;
    }
    if (action === 'open-frame-config') {
      e.stopPropagation();
      state.frameConfigSheet = btn.dataset.entry;
      state.lastAction = `Opened device settings for ${getFrame(btn.dataset.entry).title}`;
      render();
      return;
    }
    if (action === 'close-frame-config') {
      state.frameConfigSheet = null;
      render();
      return;
    }
    if (action === 'set-frame-orientation') {
      const f = getFrame(btn.dataset.entry);
      f.orientationMode = btn.dataset.orient;
      if (btn.dataset.orient !== 'auto') f.orientation = btn.dataset.orient;
      state.lastAction = `Set ${f.title} orientation lock to ${f.orientationMode.toUpperCase()}`;
      render();
      return;
    }
    if (action === 'set-frame-sleep') {
      const f = getFrame(btn.dataset.entry);
      f.sleepMinutes = parseInt(btn.dataset.mins, 10);
      state.lastAction = `Updated ${f.title} sleep interval to ${f.sleepMinutes} minutes`;
      render();
      return;
    }

    // Inline Shadow DOM Prompt Modal (Replaces window.prompt!)
    if (action === 'new-wall-modal') {
      state.promptModal = {
        title: 'Create New Wall',
        label: 'Wall Name',
        value: 'Upstairs Hallway',
        kind: 'new-wall',
      };
      render();
      return;
    }
    if (action === 'save-scene-modal') {
      state.promptModal = {
        title: 'Save Current Wall as Scene',
        label: 'Scene Name',
        value: 'Evening Gallery Mix',
        kind: 'save-scene',
      };
      render();
      return;
    }
    if (action === 'close-prompt') {
      state.promptModal = null;
      render();
      return;
    }
    if (action === 'confirm-prompt') {
      const input = protoContainer.querySelector('#proto-prompt-input');
      const val = (input ? input.value : state.promptModal.value).trim();
      if (val && state.promptModal.kind === 'new-wall') {
        const id = `wall_${Date.now()}`;
        state.walls.push({
          wall_id: id,
          name: val,
          placements: {
            entry_living_main: { x: 24, y: 28, w: 140, h: 105 },
            entry_living_side: { x: 185, y: 22, w: 76, h: 120 },
          },
        });
        state.activeWallId = id;
        state.lastAction = `Created new wall "${val}" (via inline modal, no window.prompt!)`;
      } else if (val && state.promptModal.kind === 'save-scene') {
        const mappings = {};
        for (const f of getWallFrames()) {
          mappings[f.entryId] = f.stagedImageId || f.queuedImageId || f.currentImageId;
        }
        const id = `sc_${Date.now()}`;
        state.scenes.unshift({ scene_id: id, name: val, kind: 'scene', mappings });
        state.activeSceneId = id;
        state.lastAction = `Saved scene "${val}" for ${Object.keys(mappings).length} frames`;
      }
      state.promptModal = null;
      render();
      return;
    }
    if (action === 'install-pack') {
      state.lastAction = `Installed expansion pack "${btn.dataset.pack}" into Library`;
      render();
      return;
    }
    if (action === 'close-modals-backdrop') {
      if (e.target === btn) {
        state.cropSheet = null;
        state.frameConfigSheet = null;
        state.promptModal = null;
        render();
      }
    }
  }

  function mountPrototype() {
    const panel = document.getElementById('panel');
    if (!panel || !panel.shadowRoot) {
      setTimeout(mountPrototype, 40);
      return;
    }
    seedRichDefaults(panel);

    // Hide the legacy root inside the shadow DOM while keeping the panel element alive
    Array.from(panel.shadowRoot.children).forEach((ch) => {
      if (ch.id !== 'df-prototype-root') ch.style.display = 'none';
    });

    protoContainer = panel.shadowRoot.getElementById('df-prototype-root');
    if (!protoContainer) {
      protoContainer = document.createElement('div');
      protoContainer.id = 'df-prototype-root';
      protoContainer.className = 'proto-root';
      panel.shadowRoot.appendChild(protoContainer);
    }

    protoContainer.addEventListener('click', handleAction);
    protoContainer.addEventListener('change', (e) => {
      const sel = e.target.closest('[data-action="select-wall-dropdown"]');
      if (sel) {
        state.activeWallId = sel.value;
        state.lastAction = `Selected wall "${getActiveWall().name}"`;
        render();
      }
    });

    // Keyboard ← and → variant switching (Required by UI.md)
    window.addEventListener('keydown', (e) => {
      const path = e.composedPath ? e.composedPath() : [e.target];
      const inInput = path.some((el) => el && el.tagName && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
      if (inInput) return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        cycleVariant(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        cycleVariant(1);
      }
    });

    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountPrototype);
  } else {
    mountPrototype();
  }
})();
