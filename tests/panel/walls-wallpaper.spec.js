// Wallpaper mode (KPF 19/36): one shared background image placed on the
// wall's canvas at its own independent position/scale, with frames acting
// as transparent windows over it. Lives natively in the Walls tab -- no
// separate tab, no separate wall picker. A "wallpaper" is not a separate
// entity: saving one just creates/updates an ordinary Scene whose mappings
// are image_crop entries sharing one image_id, plus a `wallpaper` field
// recording the image's rect so the editor can restore it later.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openDashboard, dragTileBy, getWallTiles, selectWallScene } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame 1', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Living Room Frame 2', width: 1600, height: 1200, orientation: 'auto' },
];

const IMAGES = [
  { image_id: 'img_bg_1', filename: 'sunset.png', albums: ['Images'] },
  { image_id: 'img_bg_2', filename: 'forest.png', albums: ['Nature'] },
];

const ALBUMS = [
  { name: 'Nature', count: 1, cover_image_id: 'img_bg_2' },
];

const SCENES = [
  {
    scene_id: 'scene_wallpaper_1',
    name: 'Existing Wallpaper',
    mappings: {
      entry_1: { type: 'image_crop', image_id: 'img_bg_1', crop_box: [0, 0, 0.5, 1] },
      entry_2: { type: 'image_crop', image_id: 'img_bg_1', crop_box: [0.5, 0, 1, 1] },
    },
    wallpaper: { image_id: 'img_bg_1', x: 10, y: 20, width: 500, height: 400 },
  },
];

async function openWallpaperMode(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-btn').click();
  });
}

async function chooseWallpaperImage(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-choose-btn').click();
  });
  await page.waitForFunction(() => {
    const grid = document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-picker-grid');
    return grid && grid.children.length > 0;
  });
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-picker-grid').firstElementChild.click();
  });
  await page.waitForFunction(() => document.getElementById('panel')._wallWallpaperEdit !== null);
}

test.describe('Wallpaper mode (Walls tab)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, albums: ALBUMS, scenes: SCENES });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('lives on the Walls tab -- no separate tab or wall picker', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });

    const hasArtFactoryTab = await page.evaluate(
      () => !!document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="art_factory"]')
    );
    expect(hasArtFactoryTab).toBe(false);

    const wallpaperBtn = await page.evaluate(
      () => !!document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-btn')
    );
    expect(wallpaperBtn).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('toggling wallpaper mode shows frame thumbnails until an image is chosen', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);

    await openWallpaperMode(page);

    // The frame's own thumbnail loads via an authenticated fetch -> blob
    // URL (_loadFrameThumbnail), not a synchronous <img src="...">, so
    // wait for it rather than reading the DOM immediately.
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tiles = [...root.querySelectorAll('.wall-tile')];
      return tiles.length > 0 && tiles.every((t) => t.querySelector('.wall-frame-thumb img'));
    });

    const beforeImage = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return [...root.querySelectorAll('.wall-tile')].map((t) => ({
        transparent: t.classList.contains('wall-wallpaper-tile'),
        hasThumbnail: !!t.querySelector('.wall-frame-thumb img'),
      }));
    });
    expect(beforeImage).toHaveLength(FRAMES.length);
    for (const tile of beforeImage) {
      expect(tile.transparent).toBe(false);
      expect(tile.hasThumbnail).toBe(true);
    }

    await chooseWallpaperImage(page);

    const afterImage = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return [...root.querySelectorAll('.wall-tile')].map((t) => t.classList.contains('wall-wallpaper-tile'));
    });
    expect(afterImage.every(Boolean)).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('dragging a frame never changes the background image rect', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);
    await chooseWallpaperImage(page);

    const before = await page.evaluate(() => ({ ...document.getElementById('panel')._wallWallpaperEdit }));

    await dragTileBy(page, 'entry_1', 0, 220);
    await page.waitForTimeout(100);

    const after = await page.evaluate(() => ({ ...document.getElementById('panel')._wallWallpaperEdit }));
    expect(after.x).toBe(before.x);
    expect(after.y).toBe(before.y);
    expect(after.width).toBe(before.width);
    expect(after.height).toBe(before.height);

    // The frame itself did move.
    const tiles = await getWallTiles(page);
    const tile1 = tiles.find((t) => t.entryId === 'entry_1');
    expect(parseFloat(tile1.top)).toBeGreaterThan(0);

    expect(pageErrors).toHaveLength(0);
  });

  test('panning the image updates its rect without moving any frame', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);
    await chooseWallpaperImage(page);

    const framesBefore = await getWallTiles(page);

    const bgBox = await page.evaluate(() => {
      const r = document.getElementById('panel').shadowRoot.querySelector('.wall-wallpaper-bg').getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await page.mouse.move(bgBox.x, bgBox.y);
    await page.mouse.down();
    await page.mouse.move(bgBox.x + 40, bgBox.y + 15, { steps: 5 });
    await page.mouse.up();

    const edit = await page.evaluate(() => document.getElementById('panel')._wallWallpaperEdit);
    expect(edit.x).toBeGreaterThan(0);

    const framesAfter = await getWallTiles(page);
    expect(framesAfter).toEqual(framesBefore);

    expect(pageErrors).toHaveLength(0);
  });

  test('resizing via the corner handle zooms uniformly, preserving aspect ratio', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);
    await chooseWallpaperImage(page);

    const before = await page.evaluate(() => ({ ...document.getElementById('panel')._wallWallpaperEdit }));
    const aspectBefore = before.width / before.height;

    const handleBox = await page.evaluate(() => {
      const r = document.getElementById('panel').shadowRoot.querySelector('.wall-wallpaper-resize-handle').getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    await page.mouse.move(handleBox.x, handleBox.y);
    await page.mouse.down();
    await page.mouse.move(handleBox.x + 60, handleBox.y + 60, { steps: 5 });
    await page.mouse.up();

    const after = await page.evaluate(() => document.getElementById('panel')._wallWallpaperEdit);
    expect(after.width).toBeGreaterThan(before.width);
    // Anchored at top-left -- position never changes from a resize.
    expect(after.x).toBe(before.x);
    expect(after.y).toBe(before.y);
    expect(after.width / after.height).toBeCloseTo(aspectBefore, 5);

    expect(pageErrors).toHaveLength(0);
  });

  test('Save as Scene posts push_now:false with the image rect, and Send to Frames Now posts push_now:true', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);
    await chooseWallpaperImage(page);

    page.once('dialog', (dialog) => dialog.accept('My New Wallpaper'));
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-save-scene-btn').click();
    });
    await page.waitForTimeout(300);

    expect(mockServer.wallpaperCalls.length).toBe(1);
    const firstCall = mockServer.wallpaperCalls[0].body;
    expect(firstCall.push_now).toBe(false);
    expect(firstCall.save_scene).toBe(true);
    expect(firstCall.image_id).toBe('img_bg_1');
    expect(firstCall.image_rect).toBeTruthy();
    expect(typeof firstCall.image_rect.x).toBe('number');

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-send-btn').click();
    });
    await page.waitForTimeout(300);

    expect(mockServer.wallpaperCalls.length).toBe(2);
    expect(mockServer.wallpaperCalls[1].body.push_now).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('re-saving threads scene_id back so it updates in place, not a duplicate', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);
    await chooseWallpaperImage(page);

    page.once('dialog', (dialog) => dialog.accept('Reusable Wallpaper'));
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-save-scene-btn').click();
    });
    await page.waitForTimeout(300);
    const firstSceneId = mockServer.wallpaperCalls[0].body.scene_id;
    expect(firstSceneId).toBeUndefined(); // no scene_id on the very first save

    // Re-save (no prompt this time -- sceneId/sceneName now carried in edit state).
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-save-scene-btn').click();
    });
    await page.waitForTimeout(300);

    expect(mockServer.wallpaperCalls.length).toBe(2);
    expect(mockServer.wallpaperCalls[1].body.scene_id).toBeTruthy();
    expect(mockServer.scenes.filter((s) => s.name === 'Reusable Wallpaper')).toHaveLength(1);

    expect(pageErrors).toHaveLength(0);
  });

  test('selecting an existing wallpaper scene restores its stored image rect', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);

    await selectWallScene(page, 'scene_wallpaper_1');
    await page.waitForFunction(() => {
      const edit = document.getElementById('panel')._wallWallpaperEdit;
      return edit && edit.imageId === 'img_bg_1';
    });

    const edit = await page.evaluate(() => document.getElementById('panel')._wallWallpaperEdit);
    expect(edit.x).toBe(10);
    expect(edit.y).toBe(20);
    expect(edit.width).toBe(500);
    expect(edit.height).toBe(400);
    expect(edit.sceneId).toBe('scene_wallpaper_1');

    const tilesAreTransparent = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return [...root.querySelectorAll('.wall-tile')].every((t) => t.classList.contains('wall-wallpaper-tile'));
    });
    expect(tilesAreTransparent).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('the wallpaper image picker has an album filter and renders thumbnails with the same crop-safe markup as the per-frame picker', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await openWallpaperMode(page);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-choose-btn').click();
    });
    await page.waitForFunction(() => {
      const grid = document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-picker-grid');
      return grid && grid.children.length > 0;
    });

    const initial = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const albumSelect = root.getElementById('wall-wallpaper-picker-album');
      const grid = root.getElementById('wall-wallpaper-picker-grid');
      return {
        albumOptions: [...albumSelect.options].map((o) => o.value),
        cellCount: grid.children.length,
        // Reuses the per-frame picker's own cell/thumb classes -- an
        // earlier version used a plain unstyled div, which left the
        // fetched <img> at its natural size with nothing constraining it,
        // so the cell's overflow:hidden clipped an arbitrary corner
        // instead of showing a clean, centered crop.
        firstCellIsImagePickerCell: grid.firstElementChild.classList.contains('image-picker-cell'),
        firstCellHasThumbDiv: !!grid.firstElementChild.querySelector('.image-picker-thumb'),
      };
    });

    expect(initial.albumOptions).toEqual(['', 'Nature']);
    expect(initial.cellCount).toBe(2); // both images, unfiltered ("All Photos")
    expect(initial.firstCellIsImagePickerCell).toBe(true);
    expect(initial.firstCellHasThumbDiv).toBe(true);

    // Filter to the "Nature" album -- only img_bg_2 should remain.
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const albumSelect = root.getElementById('wall-wallpaper-picker-album');
      albumSelect.value = 'Nature';
      albumSelect.dispatchEvent(new Event('change'));
    });
    await page.waitForFunction(() => {
      const grid = document.getElementById('panel').shadowRoot.getElementById('wall-wallpaper-picker-grid');
      return grid && grid.children.length === 1;
    });

    expect(pageErrors).toHaveLength(0);
  });

  test('previewing a wallpaper scene on the normal Walls tab (not editing mode) shows one shared background behind transparent frame windows, not a full image per tile', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    // Deliberately NOT entering wallpaper-editing mode -- this is the
    // ordinary Walls tab scene-preview path (KPF 19), which previously
    // showed every frame's tile as the same full, uncropped background
    // image (there was "no crop-rendering endpoint") instead of each
    // frame's own slice.
    await selectWallScene(page, 'scene_wallpaper_1');
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.querySelector('.wall-wallpaper-bg') !== null;
    });

    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const bg = root.querySelector('.wall-wallpaper-bg');
      const tiles = [...root.querySelectorAll('.wall-tile')];
      return {
        wallpaperModeActive: document.getElementById('panel')._wallWallpaperMode,
        bgLeft: bg ? bg.style.left : null,
        bgTop: bg ? bg.style.top : null,
        tilesAreWindows: tiles.every((t) => t.classList.contains('wall-wallpaper-tile')),
        tilesHaveFooters: tiles.every((t) => !!t.querySelector('.wall-tile-footer')),
      };
    });

    expect(state.wallpaperModeActive).toBe(false); // still the ordinary Walls tab, not the editor
    expect(state.bgLeft).toBe('10px');
    expect(state.bgTop).toBe('20px');
    expect(state.tilesAreWindows).toBe(true);
    // Unlike the editing-mode tiles, normal-mode tiles keep their footer
    // (name/status) and hover quadrants -- this is a read-only preview
    // skin layered onto the ordinary tile, not a different tile type.
    expect(state.tilesHaveFooters).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('clicking Send to Frames on the ordinary Walls tab (a wallpaper scene loaded, not editing mode) actually sends the wallpaper-mapped frames', async ({ page }) => {
    // The bug this guards against: a wallpaper's image_crop mapping is an
    // object, not a plain image_id string, so it never matched the
    // client's old string-only per-frame send loop -- "Send to Frames"
    // reported success while silently never touching that frame, and its
    // thumbnail never updated. This is the ordinary Walls tab "Send to
    // Frames" button, deliberately NOT wallpaper-editing mode (that path,
    // covered above, always worked -- this one didn't).
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openDashboard(page);
    await selectWallScene(page, 'scene_wallpaper_1');
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.querySelector('.wall-wallpaper-bg') !== null;
    });

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-send-btn').click();
    });
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-scene-fb').style.display === 'block'
    );

    expect(mockServer.wallSendCalls.length).toBe(1);
    const sentMappings = mockServer.wallSendCalls[0].body.mappings;
    expect(Object.keys(sentMappings).sort()).toEqual(['entry_1', 'entry_2']);
    expect(sentMappings.entry_1).toEqual({ type: 'image_crop', image_id: 'img_bg_1', crop_box: [0, 0, 0.5, 1] });
    expect(sentMappings.entry_2).toEqual({ type: 'image_crop', image_id: 'img_bg_1', crop_box: [0.5, 0, 1, 1] });

    const fbText = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-scene-fb').textContent
    );
    expect(fbText).toContain('Sent to 2 frame');

    expect(pageErrors).toHaveLength(0);
  });

  test('a frame\'s "on frame" thumbnail (no scene mapping, no library image_id) loads with an auth header, not a bare <img src>', async ({ page }) => {
    // Real bug: coordinator.last_thumbnail (a crop/upload/skill-render send
    // with no library image_id behind it) rendered via a plain
    // `<img src="/api/digital_frames/frame/{id}/thumbnail">`. HA requires
    // the Bearer auth header for every /api/ route; an <img> tag has no way
    // to attach one, so this always 401'd in real Home Assistant even
    // though this permissive mock would happily serve it either way --
    // this is exactly why the bug slipped past every earlier test here.
    // Rendering it via _loadFrameThumbnail (authenticated fetch -> blob
    // URL, like every other thumbnail in the panel) is what this asserts.
    await mockServer.stop();
    const framesWithThumbnail = [
      { ...FRAMES[0], last_image_id: null, has_thumbnail: true },
      FRAMES[1],
    ];
    mockServer = createMockServer({ frames: framesWithThumbnail, images: IMAGES, albums: ALBUMS, scenes: SCENES });
    baseUrl = await mockServer.start();

    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: framesWithThumbnail });
    await openDashboard(page);

    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = root.querySelector('.wall-tile[data-entry-id="entry_1"]');
      return tile && tile.querySelector('.wall-tile-media img');
    });

    const requests = mockServer.frameThumbnailRequests.filter((r) => r.url.includes('entry_1'));
    expect(requests.length).toBeGreaterThan(0);
    expect(requests.every((r) => r.hasAuthHeader)).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });
});
