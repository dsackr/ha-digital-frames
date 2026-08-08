// End-to-end Playwright test for Spanned Wall Image across 2D physical frame layouts (KPF 36).

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openScenesTab } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame 1', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Living Room Frame 2', width: 1200, height: 1600, orientation: 'auto' },
];

const IMAGES = [
  { image_id: 'img_1', filename: 'landscape.jpg', albums: ['Nature'] },
];

test.describe('Spanned Wall Image Flow (KPF 36)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      images: IMAGES,
      walls: [
        {
          wall_id: 'wall_1',
          name: 'Living Room Wall',
          kind: 'custom',
          placements: {
            entry_1: { x: 40, y: 40 },
            entry_2: { x: 220, y: 40 },
          },
        },
      ],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('opens Spanned Wall Image modal and renders live preview overlays', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    // Click "🖼 Span Image Across Wall"
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-span-image-btn').click();
    });

    // Verify modal overlay is displayed
    const isVisible = await page.evaluate(() => {
      const overlay = document.getElementById('panel').shadowRoot.getElementById('wall-span-modal-overlay');
      return overlay && overlay.style.display !== 'none';
    });
    expect(isVisible).toBe(true);

    // Verify title text
    const titleText = await page.evaluate(() => {
      return document.getElementById('panel').shadowRoot.getElementById('wall-span-title').textContent;
    });
    expect(titleText).toContain('Span Image Across Wall');
  });

  test('submits AI Prompt spanned wall image to backend', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    // Open Modal
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-span-image-btn').click();
    });

    // Fill AI Prompt, check Save Scene, set Scene Name, and submit
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('wall-span-ai-prompt').value = 'Dramatic sunset over snowy mountain peaks';
      const saveSceneCb = root.getElementById('wall-span-save-scene-cb');
      saveSceneCb.checked = true;
      saveSceneCb.dispatchEvent(new Event('change'));
      root.getElementById('wall-span-scene-name-input').value = 'Sunset Wall Scene';
      root.getElementById('wall-span-submit-btn').click();
    });

    await page.waitForTimeout(1500);

    // Verify mock server received the wall span request
    expect(mockServer.wallSpanCalls.length).toBeGreaterThan(0);
    const lastCall = mockServer.wallSpanCalls[mockServer.wallSpanCalls.length - 1];
    expect(lastCall.body.source_type).toBe('ai');
    expect(lastCall.body.prompt).toBe('Dramatic sunset over snowy mountain peaks');
    expect(lastCall.body.save_scene).toBe(true);
    expect(lastCall.body.scene_name).toBe('Sunset Wall Scene');
  });

  test('selects library photo and spans across wall', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-span-image-btn').click();
    });

    // Switch to Library tab
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('wall-span-tab-btn-lib').click();
    });

    // Wait for item div in library grid
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const grid = root.getElementById('wall-span-lib-grid');
      return grid && grid.querySelector('div') !== null;
    }, { timeout: 10000 });

    // Pick first library image and submit
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const firstItem = root.querySelector('#wall-span-lib-grid > div');
      if (firstItem) firstItem.click();
      root.getElementById('wall-span-submit-btn').click();
    });

    await page.waitForTimeout(1500);

    expect(mockServer.wallSpanCalls.length).toBeGreaterThan(0);
    const lastCall = mockServer.wallSpanCalls[mockServer.wallSpanCalls.length - 1];
    expect(lastCall.body.source_type).toBe('lib');
    expect(lastCall.body.image_id).toBe('img_1');
  });
});
