// The wall picker's "✂ Adjust Crop" button: hands the staged (or on-frame)
// library image to the Library crop editor, pre-targeted at the picker's
// frame -- so crop adjustment is reachable right where the user is already
// managing the frame, not only from the Library shelf.

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
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];
const IMAGES = [
  { image_id: 'image_vacation', filename: 'beach.png', albums: ['Vacation'] },
];

async function openPickerOnFirstTile(page) {
  await openScenesTab(page);
  await createWall(page, 'Living Room');
  const canvasBox = await page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y };
  });
  await dragFirstPaletteItemTo(page, canvasBox.x + 100, canvasBox.y + 80);
  await page.waitForTimeout(100);
  await clickTile(page, 'entry_1');
  await page.waitForFunction(
    () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
  );
}

function cropBtnDisabled(page) {
  return page.evaluate(
    () => document.getElementById('panel').shadowRoot.getElementById('wall-picker-crop-btn').disabled
  );
}

test.describe('Wall picker: Adjust Crop', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('disabled when the frame has no library image staged or on it', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);
    expect(await cropBtnDisabled(page)).toBe(true);
  });

  test('staging a library pick enables it, and clicking opens the crop editor targeted at this frame', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);

    // Stage a library image (this closes the picker), then reopen.
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('#wall-image-picker-grid .image-picker-cell').click();
    });
    await clickTile(page, 'entry_1');
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block'
    );

    expect(await cropBtnDisabled(page)).toBe(false);
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-picker-crop-btn').click();
    });

    // The picker closes and the Library crop editor opens, pre-targeted at
    // this frame's battery entity (the editor's frame key).
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('editor-overlay').style.display === 'flex'
    );
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        pickerDisplay: root.getElementById('wall-image-picker-overlay').style.display,
        target: root.getElementById('editor-frame-select').value,
        title: root.getElementById('editor-title').textContent,
      };
    });
    expect(state.pickerDisplay).toBe('none');
    expect(state.target).toBe('sensor.entry_1_battery');
    expect(state.title).toBe('beach.png');
  });

  test('a frame with a library image already on it can adjust its crop without re-picking', async ({ page }) => {
    await mockServer.stop();
    mockServer = createMockServer({
      frames: [{ ...FRAMES[0], last_image_id: 'image_vacation' }],
      images: IMAGES,
    });
    baseUrl = await mockServer.start();

    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openPickerOnFirstTile(page);
    expect(await cropBtnDisabled(page)).toBe(false);
  });
});
