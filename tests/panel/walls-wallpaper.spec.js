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
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, scenes: SCENES });
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

    const beforeImage = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return [...root.querySelectorAll('.wall-tile')].map((t) => ({
        transparent: t.classList.contains('wall-wallpaper-tile'),
        hasThumbnail: !!t.querySelector('img[src*="/frame/"]'),
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
});
