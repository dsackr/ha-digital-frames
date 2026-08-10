// End-to-end Playwright test for Art Factory AI image & wall spanning studio (KPF 36 & 38).

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame 1', width: 1200, height: 1600, orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Living Room Frame 2', width: 1600, height: 1200, orientation: 'auto' },
];

test.describe('Art Factory AI Generation & Wall Spanning Studio (KPF 36 & 38)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('switches to Art Factory tab and loads engine status', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    // Switch to Art Factory tab
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="art_factory"]').click();
    });

    // Verify tab content is active
    const isActive = await page.evaluate(() => {
      const tab = document.getElementById('panel').shadowRoot.getElementById('tab-art_factory');
      return tab && tab.classList.contains('active');
    });
    expect(isActive).toBe(true);

    // Verify engine badge text loads
    await page.waitForFunction(() => {
      const badge = document.getElementById('panel').shadowRoot.getElementById('art-factory-engine-badge');
      return badge && badge.textContent.includes('Home Assistant AI');
    }, { timeout: 5000 });
  });

  test('generates artwork, renders frame overlays, drags frame, sends to frames, and saves as scene', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    // Switch to Art Factory tab
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="art_factory"]').click();
    });

    // Fill prompt and generate
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-prompt').value = 'Cyberpunk city under starry night sky';
      root.getElementById('art-factory-style').value = 'neon_noir';
      root.getElementById('art-factory-generate-btn').click();
    });

    // Wait for generation response & preview wrapper to appear
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const wrapper = root.getElementById('art-factory-preview-wrapper');
      return wrapper && wrapper.style.display !== 'none';
    }, { timeout: 5000 });

    // Verify frame overlays rendered on wall canvas
    const overlayCount = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const overlays = root.querySelectorAll('.art-factory-frame-tile');
      return overlays.length;
    });
    expect(overlayCount).toBeGreaterThan(0);

    // Drag a frame overlay tile across artwork canvas
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const tile = root.querySelector('.art-factory-frame-tile');
      if (tile) {
        tile.dispatchEvent(new PointerEvent('pointerdown', { clientX: 100, clientY: 100, bubbles: true }));
        tile.dispatchEvent(new PointerEvent('pointermove', { clientX: 150, clientY: 150, bubbles: true }));
        tile.dispatchEvent(new PointerEvent('pointerup', { clientX: 150, clientY: 150, bubbles: true }));
      }
    });

    // Click Send to Frames button
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-send-span-btn').click();
    });

    await page.waitForTimeout(1000);

    // Verify spanned wall send request received by mock server
    expect(mockServer.wallSpanCalls.length).toBeGreaterThan(0);

    // Click Save as Scene button
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-scene-name').value = 'My Spanned Cyberpunk Scene';
      root.getElementById('art-factory-save-scene-btn').click();
    });

    await page.waitForTimeout(1000);

    // Verify save scene call
    const lastSpanCall = mockServer.wallSpanCalls[mockServer.wallSpanCalls.length - 1];
    expect(lastSpanCall.body.save_scene).toBe(true);
  });
});
