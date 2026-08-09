// End-to-end Playwright test for Art Factory AI image generation (KPF 38).

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];

test.describe('Art Factory AI Generation Flow (KPF 38)', () => {
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

  test('fills prompt, selects style, clicks Generate Image, and verifies preview', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    // Switch to Art Factory tab
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="art_factory"]').click();
    });

    // Fill prompt and select style
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-prompt').value = 'Cyberpunk city under starry night sky';
      root.getElementById('art-factory-style').value = 'neon_noir';
      root.getElementById('art-factory-generate-btn').click();
    });

    // Wait for generation response & preview to appear
    await page.waitForFunction(() => {
      const root = document.getElementById('panel').shadowRoot;
      const wrapper = root.getElementById('art-factory-preview-wrapper');
      return wrapper && wrapper.style.display !== 'none';
    }, { timeout: 5000 });

    // Verify mock server received call
    expect(mockServer.artFactoryCalls.length).toBeGreaterThan(0);
    const lastCall = mockServer.artFactoryCalls[mockServer.artFactoryCalls.length - 1];
    expect(lastCall.prompt).toBe('Cyberpunk city under starry night sky');
    expect(lastCall.style).toBe('neon_noir');

    // Click Send to Frame button
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('art-factory-send-btn').click();
    });

    await page.waitForTimeout(1000);

    // Verify send request made
    expect(mockServer.requestLog.some(r => typeof r === 'string' && r.includes('/api/digital_frames/library/send'))).toBe(true);
  });
});
