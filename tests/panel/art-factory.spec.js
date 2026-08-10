// End-to-end Playwright tests for Art Factory (KPF 36, 37, 38 & the wallpaper
// mode that reuses the Walls tab's real canvas/drag machinery under a
// transparent-window skin -- see _activateArtFactoryWallpaperCanvas in
// digital-frames-panel.js).

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openDashboard, dragTileBy, getWallTiles } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame 1', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Living Room Frame 2', width: 1600, height: 1200, orientation: 'auto' },
];

const IMAGES = [
  { image_id: 'img_bg_1', filename: 'sunset.png', albums: ['Images'] },
];

async function openArtFactoryTab(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="art_factory"]').click();
  });
  await page.waitForFunction(() => {
    const tab = document.getElementById('panel').shadowRoot.getElementById('tab-art_factory');
    return tab && tab.classList.contains('active');
  });
}

test.describe('Art Factory AI Generation & Wallpaper Studio (KPF 36, 37, 38)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('switches to Art Factory tab and loads engine status', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    await page.waitForFunction(() => {
      const badge = document.getElementById('panel').shadowRoot.getElementById('art-factory-engine-badge');
      return badge && badge.textContent.includes('Home Assistant AI');
    }, { timeout: 5000 });

    expect(pageErrors).toHaveLength(0);
  });

  test('wall select populates and the canvas shows one transparent window per placed frame', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    // Regression coverage for the bug where #art-factory-wall-select stayed
    // empty because it was only ever populated once, at tab-init time, with
    // no re-population once wall data actually landed.
    const wallOptionCount = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('art-factory-wall-select').options.length
    );
    expect(wallOptionCount).toBeGreaterThan(0);

    // #wall-canvas itself was relocated in here -- same element the Walls
    // tab drags against, not a separate implementation.
    const relocated = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const host = root.getElementById('art-factory-canvas-host');
      const canvas = root.getElementById('wall-canvas');
      return !!(host && canvas && host.contains(canvas) && canvas.classList.contains('wallpaper-mode'));
    });
    expect(relocated).toBe(true);

    const tiles = await getWallTiles(page);
    expect(tiles).toHaveLength(FRAMES.length);

    const allTransparentSkin = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return [...root.querySelectorAll('.wall-tile')].every((t) => t.classList.contains('af-wallpaper-tile'));
    });
    expect(allTransparentSkin).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('dragging a frame in the wallpaper editor updates the same wall the Walls tab shows', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    const before = (await getWallTiles(page)).find((t) => t.entryId === 'entry_1');
    // Straight down, away from entry_2's row -- a sideways move of this
    // magnitude would collide with entry_2's tile and get rejected (snapped
    // back to start), which isn't what this test is checking.
    await dragTileBy(page, 'entry_1', 0, 220);
    // Let the debounced layout save (800ms) land before switching tabs --
    // switching back to the Walls tab re-selects the active wall, which
    // (like the Walls tab's own wall-switcher) re-reads placements from
    // the cached wall list, not from any not-yet-saved in-memory edit.
    await page.waitForTimeout(900);

    const afterInArtFactory = (await getWallTiles(page)).find((t) => t.entryId === 'entry_1');
    expect(afterInArtFactory.top).not.toBe(before.top);

    // Switch to the Walls tab -- #wall-canvas moves back and re-renders
    // with the normal thumbnail skin, but it's the exact same
    // this._wallPlacements the drag above just wrote to.
    await openDashboard(page);
    const inWallsTab = (await getWallTiles(page)).find((t) => t.entryId === 'entry_1');
    expect(inWallsTab.left).toBe(afterInArtFactory.left);
    expect(inWallsTab.top).toBe(afterInArtFactory.top);

    const noLongerWallpaperSkin = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === 'entry_1');
      return tile && !tile.classList.contains('af-wallpaper-tile');
    });
    expect(noLongerWallpaperSkin).toBe(true);

    expect(pageErrors).toHaveLength(0);
  });

  test('choosing a background image from the library updates the label and canvas', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-choose-bg-btn').click();
    });
    await page.waitForFunction(() => {
      const grid = document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-picker-grid');
      return grid && grid.children.length > 0;
    });

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-picker-grid').firstElementChild.click();
    });

    const bgName = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-name').textContent
    );
    expect(bgName).toBe('sunset.png');

    const overlayHidden = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-picker-overlay').style.display
    );
    expect(overlayHidden).toBe('none');

    expect(pageErrors).toHaveLength(0);
  });

  test('generates artwork and can use the result as the wallpaper background', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-prompt').value = 'Cyberpunk city under starry night sky';
      root.getElementById('art-factory-style').value = 'neon_noir';
      root.getElementById('art-factory-generate-btn').click();
    });

    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const lastResult = root.getElementById('art-factory-last-result');
      return lastResult && lastResult.style.display !== 'none';
    }, { timeout: 5000 });

    // Generation never locks the image to any wall -- nothing about the
    // wallpaper canvas/background changes just from generating.
    const bgNameBeforeUse = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-name').textContent
    );
    expect(bgNameBeforeUse).toBe('None selected');

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-use-as-bg-btn').click();
    });

    const bgNameAfterUse = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-name').textContent
    );
    expect(bgNameAfterUse).not.toBe('None selected');

    expect(pageErrors).toHaveLength(0);
  });

  test('Save as Scene never pushes to hardware; Send to Frames Now does', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    // Pick a background straight from the library -- no generation needed.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-choose-bg-btn').click();
    });
    await page.waitForFunction(() => {
      const grid = document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-picker-grid');
      return grid && grid.children.length > 0;
    });
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-bg-picker-grid').firstElementChild.click();
    });

    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-scene-name').value = 'My Wallpaper Scene';
      root.getElementById('art-factory-save-scene-btn').click();
    });
    await page.waitForTimeout(300);

    expect(mockServer.wallSpanCalls.length).toBe(1);
    expect(mockServer.wallSpanCalls[0].body.push_now).toBe(false);
    expect(mockServer.wallSpanCalls[0].body.save_scene).toBe(true);
    expect(mockServer.wallSpanCalls[0].body.source_type).toBe('library');
    expect(mockServer.wallSpanCalls[0].body.image_id).toBe('img_bg_1');

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-send-span-btn').click();
    });
    await page.waitForTimeout(300);

    expect(mockServer.wallSpanCalls.length).toBe(2);
    expect(mockServer.wallSpanCalls[1].body.push_now).toBe(true);
    expect(mockServer.wallSpanCalls[1].body.save_scene).toBe(false);

    expect(pageErrors).toHaveLength(0);
  });

  test('wall size hint reflects the wall aggregate geometry, not one frame', async ({ page }) => {
    const { pageErrors } = await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openArtFactoryTab(page);

    await page.waitForFunction(() => {
      const hint = document.getElementById('panel').shadowRoot.getElementById('art-factory-wall-size-hint');
      return hint && hint.textContent.includes('×');
    }, { timeout: 5000 });

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('art-factory-use-wall-size-btn').click();
    });

    await page.waitForFunction(() => {
      const sizeEl = document.getElementById('panel').shadowRoot.getElementById('art-factory-size');
      return [...sizeEl.options].some((o) => o.dataset.wallSize === 'true');
    }, { timeout: 5000 });

    const sizeValue = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('art-factory-size').value
    );
    // Mock server's geometry stand-in: 1200 * frame count wide, 1600 tall --
    // wider than any single frame's own resolution, proving this is the
    // wall's aggregate size, not one frame's.
    expect(sizeValue).toBe(`${1200 * FRAMES.length}x1600`);

    expect(pageErrors).toHaveLength(0);
  });
});
