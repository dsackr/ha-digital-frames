// KPF 41: Resend to frame from the Frame Information modal.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton } = require('./fixtures/panel-page');

const FRAME = {
  entry_id: 'entry_1',
  title: 'Living Room Frame',
  width: 1200,
  height: 1600,
  orientation: 'portrait',
  host: '192.168.1.10',
  driver: 'fraimic',
  origin: 'official',
};

async function openInfo(page) {
  await page.waitForFunction(() => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = root.querySelector('.wall-tile');
    return tile && tile.querySelector('.wall-tile-quadrant[data-action="info"]');
  });
  await page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    root.querySelector('.wall-tile-quadrant[data-action="info"]').click();
  });
}

test.describe('Resend to frame', () => {
  let mockServer;
  let baseUrl;

  test.afterEach(async () => {
    if (mockServer) await mockServer.stop();
    mockServer = null;
  });

  test('button is disabled when the frame has no previous image', async ({ page }) => {
    mockServer = createMockServer({ frames: [FRAME] });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: [FRAME] });
    await openInfo(page);

    const state = await page.evaluate(() => {
      const btn = document.getElementById('panel').shadowRoot.getElementById('frame-settings-resend');
      return { disabled: btn.disabled, text: btn.textContent };
    });
    expect(state.disabled).toBe(true);
    expect(state.text).toContain('Resend to frame');
  });

  test('resend posts the frame entry id and shows success', async ({ page }) => {
    const frames = [{ ...FRAME, last_image_id: 'image_beach', can_resend: true }];
    mockServer = createMockServer({ frames });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames });
    await openInfo(page);

    const enabled = await page.evaluate(() => {
      const btn = document.getElementById('panel').shadowRoot.getElementById('frame-settings-resend');
      return !btn.disabled;
    });
    expect(enabled).toBe(true);

    await clickPanelButton(page, 'frame-settings-resend');
    await expect.poll(() => page.evaluate(() => {
      const fb = document.getElementById('panel').shadowRoot.getElementById('frame-settings-fb');
      return { text: fb.textContent, className: fb.className, display: fb.style.display };
    })).toEqual({
      text: 'Resent to the frame.',
      className: 'feedback ok',
      display: 'block',
    });
    expect(mockServer.resendCalls).toEqual([{ entry_id: 'entry_1' }]);
  });

  test('button shows a loading label while the resend is in flight', async ({ page }) => {
    const frames = [{ ...FRAME, last_image_id: 'image_beach', can_resend: true }];
    mockServer = createMockServer({ frames });
    baseUrl = await mockServer.start();
    mockServer.setResend({ delayMs: 600 });
    await gotoPanel(page, baseUrl, { frames });
    await openInfo(page);
    await clickPanelButton(page, 'frame-settings-resend');

    await expect.poll(() => page.evaluate(() => {
      const btn = document.getElementById('panel').shadowRoot.getElementById('frame-settings-resend');
      return btn.textContent;
    })).toBe('Resending…');

    await expect.poll(() => page.evaluate(() => {
      const fb = document.getElementById('panel').shadowRoot.getElementById('frame-settings-fb');
      return fb.textContent;
    })).toBe('Resent to the frame.');
  });

  test('a queued resend shows the asleep message', async ({ page }) => {
    const frames = [{ ...FRAME, has_thumbnail: true, can_resend: true }];
    mockServer = createMockServer({ frames });
    baseUrl = await mockServer.start();
    mockServer.setResend({
      body: {
        success: false,
        queued: true,
        message: 'Frame is asleep — the image is queued and will be sent when it wakes up.',
      },
    });
    await gotoPanel(page, baseUrl, { frames });
    await openInfo(page);
    await clickPanelButton(page, 'frame-settings-resend');

    await expect.poll(() => page.evaluate(() => {
      const fb = document.getElementById('panel').shadowRoot.getElementById('frame-settings-fb');
      return fb.textContent;
    })).toContain('asleep');
  });

  test('no previous image from the API is shown as an error', async ({ page }) => {
    const frames = [{ ...FRAME, last_image_id: 'image_beach', can_resend: true }];
    mockServer = createMockServer({ frames });
    baseUrl = await mockServer.start();
    mockServer.setResend({
      status: 409,
      body: { message: 'No image has been sent to this frame yet' },
    });
    await gotoPanel(page, baseUrl, { frames });
    await openInfo(page);
    await clickPanelButton(page, 'frame-settings-resend');

    await expect.poll(() => page.evaluate(() => {
      const fb = document.getElementById('panel').shadowRoot.getElementById('frame-settings-fb');
      return { text: fb.textContent, className: fb.className };
    })).toEqual({
      text: 'No image has been sent to this frame yet',
      className: 'feedback err',
    });
  });
});
