const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const {
  gotoPanel,
  openScenesTab,
  createWall,
  dragFirstPaletteItemTo,
  clickTile,
} = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'landscape_frame', title: 'Landscape Frame', width: 1600, height: 1200, orientation: 'landscape' },
  { entry_id: 'portrait_frame', title: 'Portrait Frame', width: 1200, height: 1600, orientation: 'portrait' },
];

const IMAGES = [
  { image_id: 'img_unlocked', filename: 'unlocked.png', orientation_lock: 'unlocked', albums: ['Images'] },
  { image_id: 'img_portrait', filename: 'portrait.png', orientation_lock: 'portrait', albums: ['Images'] },
  { image_id: 'img_landscape', filename: 'landscape.png', orientation_lock: 'landscape', albums: ['Images'] },
];

const ALBUMS = [
  { name: 'Images', count: 3, cover_image_id: 'img_unlocked' },
];

test.describe('Crop Aspect Ratio and Orientation Lock UI', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
    page.on('console', msg => console.log('BROWSER_LOG:', msg.text()));
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('Screen Compatibility dropdown updates orientation lock and disables incompatible frames', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    // Open Library modal
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('library-open-btn').click();
    });

    // Wait for albums to render
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.album-tile').length > 0
    );

    // Open "Images" album
    await page.evaluate(() => {
      const tile = [...document.getElementById('panel').shadowRoot.querySelectorAll('.album-tile')]
        .find(t => t.querySelector('.album-name').textContent === 'Images');
      tile.querySelector('.album-name').click();
    });

    // Open editor for the first image
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.lib-thumb').length > 0
    );
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.lib-thumb').click();
    });

    // Check editor overlay opens
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('editor-overlay').style.display === 'flex'
    );

    // Verify compat select exists and is set to unlocked
    const compatSelectVal = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('editor-compat-select').value
    );
    expect(compatSelectVal).toBe('unlocked');

    // Select Portrait Only
    await page.evaluate(() => {
      const select = document.getElementById('panel').shadowRoot.getElementById('editor-compat-select');
      select.value = 'portrait';
      select.dispatchEvent(new Event('change'));
    });

    // Verify that the frame select dropdown options have been updated and landscape targets are disabled
    await page.waitForTimeout(200);
    const disabledOptions = await page.evaluate(() => {
      const select = document.getElementById('panel').shadowRoot.getElementById('editor-frame-select');
      return [...select.querySelectorAll('option')].map(opt => ({
        value: opt.value,
        text: opt.textContent,
        disabled: opt.disabled,
      }));
    });

    const genericLandscapeOpt = disabledOptions.find(o => o.value === 'generic_landscape');
    expect(genericLandscapeOpt.disabled).toBe(true);
    expect(genericLandscapeOpt.text).toContain('(Incompatible)');

    const landscapeFrameOpt = disabledOptions.find(o => o.value === 'sensor.landscape_frame_battery');
    expect(landscapeFrameOpt.disabled).toBe(true);
    expect(landscapeFrameOpt.text).toContain('(Incompatible)');

    const portraitFrameOpt = disabledOptions.find(o => o.value === 'sensor.portrait_frame_battery');
    expect(portraitFrameOpt.disabled).toBe(false);
  });

  test('Wall Image Picker dims and blocks orientation-locked images', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    // Go to Wall manager
    await openScenesTab(page);
    await createWall(page, 'Living Room');
    const canvasBox = await page.evaluate(() => {
      const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
      return { x: r.x, y: r.y };
    });

    // Drag the standard landscape frame (which is now first) onto the canvas
    await dragFirstPaletteItemTo(page, canvasBox.x + 100, canvasBox.y + 80);

    await page.waitForTimeout(100);

    // Click the landscape frame tile to open the image picker
    await clickTile(page, 'landscape_frame');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );

    // Wait for photos grid to load
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );

    // Get cells state (opacity and classes)
    const cellsState = await page.evaluate(() => {
      const cells = [...document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell')];
      return cells.map(c => ({
        id: c.dataset.imageId,
        opacity: getComputedStyle(c).opacity,
        incompatible: c.classList.contains('incompatible'),
      }));
    });

    const portImgCell = cellsState.find(c => c.id === 'img_portrait');
    expect(portImgCell.incompatible).toBe(true);
    expect(parseFloat(portImgCell.opacity)).toBeCloseTo(0.3, 1);

    const landImgCell = cellsState.find(c => c.id === 'img_landscape');
    expect(landImgCell.incompatible).toBe(false);
    expect(parseFloat(landImgCell.opacity)).toBeCloseTo(1.0, 1);

    // Clicking the incompatible cell should show an alert and NOT close the picker
    page.on('dialog', async dialog => {
      expect(dialog.message()).toContain('This image is locked to portrait screens');
      await dialog.dismiss();
    });

    await page.evaluate(() => {
      const cells = [...document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell')];
      const portCell = cells.find(c => c.dataset.imageId === 'img_portrait');
      portCell.click();
    });

    await page.waitForTimeout(100);
    const display = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display
    );
    expect(display).toBe('block'); // still open!
  });
});
