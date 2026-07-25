// Coverage for embedded frame management (the per-card gear menu) and the
// discovered-frames banner: rename via config_entries/update, remove via
// the config entry DELETE endpoint, banner rendering from flow-subscribe
// events, resuming a discovered flow without deleting it on cancel, and
// admin gating of all of the above.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'portrait', host: '192.168.1.10' },
  { entry_id: 'entry_2', title: 'Office Frame', width: 800, height: 480, orientation: 'landscape', host: '192.168.1.20' },
];

const DISCOVERED_FLOW = {
  flow_id: 'flow_disc1',
  handler: 'digital_frames',
  context: { source: 'integration_discovery', title_placeholders: { name: '192.168.1.31' } },
  step_id: 'name_device',
};

async function openInfoFor(page, entryId) {
  await page.waitForFunction((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    return tile && tile.querySelector('.wall-tile-quadrant[data-action="info"]');
  }, entryId, { timeout: 5000 });
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    tile.querySelector('.wall-tile-quadrant[data-action="info"]').click();
  }, entryId);
}

async function openConfigureFor(page, entryId) {
  await page.waitForFunction((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    return tile && tile.querySelector('.wall-tile-quadrant[data-action="configure"]');
  }, entryId, { timeout: 5000 });
  await page.evaluate((id) => {
    const root = document.getElementById('panel').shadowRoot;
    const tile = [...root.querySelectorAll('.wall-tile')].find((t) => t.dataset.entryId === id);
    tile.querySelector('.wall-tile-quadrant[data-action="configure"]').click();
  }, entryId);
}

test.describe('Frame management and discovery banner', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async () => {
    mockServer = createMockServer({
      frames: FRAMES,
      discoveredFlows: [{ flow_id: 'flow_disc1', host: '192.168.1.31' }],
    });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('info overlay → rename issues config_entries/update with the new title', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openInfoFor(page, 'entry_1');

    // Assert details are displayed correctly
    const details = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        ip: root.getElementById('frame-info-ip').textContent,
        orientation: root.getElementById('frame-info-orientation').textContent,
        battery: root.getElementById('frame-info-battery').textContent,
      };
    });
    expect(details.ip).toBe('192.168.1.10');
    expect(details.orientation).toBe('Portrait');
    expect(details.battery).toBe('90%');

    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-settings-name').value = 'Kitchen Frame';
    });
    await clickPanelButton(page, 'frame-settings-rename');

    // Both registries must be updated: entry title alone leaves the device
    // page showing the creation-time name.
    await expect.poll(() => page.evaluate(
      () => window.__wsCalls.filter((c) => c.type === 'config_entries/update' || c.type === 'config/device_registry/update')
    )).toEqual([
      { type: 'config_entries/update', entry_id: 'entry_1', title: 'Kitchen Frame' },
      { type: 'config/device_registry/update', device_id: 'entry_1', name_by_user: 'Kitchen Frame' },
    ]);
  });

  test('configure options flow modal → advanced settings collapsible toggle works', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openConfigureFor(page, 'entry_1');

    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'init';
    }, { timeout: 5000 });

    // Assert resolution / Frame Type is standard (not hidden)
    const isResolutionVisible = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const el = root.getElementById('flow-field-resolution');
      return el && el.offsetParent !== null;
    });
    expect(isResolutionVisible).toBe(true);

    // Assert scan_interval and rotation_edge are hidden initially
    const isScanIntervalVisibleBefore = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const el = root.getElementById('flow-field-scan_interval');
      return el && el.offsetParent !== null;
    });
    expect(isScanIntervalVisibleBefore).toBe(false);

    // Click the Advanced Settings link to expand it
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const toggle = root.querySelector('.options-advanced-toggle');
      toggle.click();
    });

    // Assert scan_interval and rotation_edge are visible after clicking toggle
    const isScanIntervalVisibleAfter = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const el = root.getElementById('flow-field-scan_interval');
      return el && el.offsetParent !== null;
    });
    expect(isScanIntervalVisibleAfter).toBe(true);
  });

  test('configure options flow modal → reconnect and remove actions inside advanced options work', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    // 1. Reconnect action
    await openConfigureFor(page, 'entry_1');
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'init';
    }, { timeout: 5000 });

    // Click advanced toggle to make reconnect button clickable
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.querySelector('.options-advanced-toggle').click();
    });

    // Click reconnect
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const btns = [...root.querySelectorAll('.options-advanced-actions button')];
      const reconnectBtn = btns.find(b => b.textContent === 'Reconnect Frame');
      reconnectBtn.click();
    });

    // Expect the mock reload endpoint to have been called
    await expect.poll(() => mockServer.reloadCalls).toEqual([{ entry_id: 'entry_1' }]);

    // 2. Remove action
    await openConfigureFor(page, 'entry_2');
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'init';
    }, { timeout: 5000 });

    // Click advanced toggle
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.querySelector('.options-advanced-toggle').click();
    });

    // Accept confirmation and click remove
    page.once('dialog', (dialog) => dialog.accept());
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const btns = [...root.querySelectorAll('.options-advanced-actions button')];
      const removeBtn = btns.find(b => b.textContent === 'Remove from HA');
      removeBtn.click();
    });

    // Expect the mock entry delete endpoint to have been called
    await expect.poll(() => mockServer.entryDeletes).toEqual(['entry_2']);
  });

  test('the banner renders discovered flows and its Add resumes that flow_id', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.waitForFunction(() => {
      const banner = document.getElementById('panel').shadowRoot.getElementById('discovery-banner');
      return banner.style.display === 'flex';
    }, { timeout: 5000 });

    const bannerText = await page.evaluate(
      () => document.getElementById('panel').shadowRoot.getElementById('discovery-banner').textContent
    );
    expect(bannerText).toContain('1 frame found');
    expect(bannerText).toContain('192.168.1.31');

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.banner-add-btn').click();
    });
    // Resuming = GET on the pending flow, landing straight on name_device.
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'name_device';
    }, { timeout: 5000 });
    expect(mockServer.requestLog).toContain('GET /api/config/config_entries/flow/flow_disc1');

    // Cancelling a discovered flow must NOT delete it server-side -- it has
    // to stay pending for HA's own Discovered card.
    await clickPanelButton(page, 'flow-modal-cancel');
    await page.waitForTimeout(200);
    expect(mockServer.flowDeletes).toEqual([]);
  });

  test('a flow-subscribe removal event clears the banner', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.waitForFunction(() => {
      const banner = document.getElementById('panel').shadowRoot.getElementById('discovery-banner');
      return banner.style.display === 'flex';
    }, { timeout: 5000 });

    await page.evaluate(() => {
      window.__flowSubCallback([{ type: 'removed', flow_id: 'flow_disc1' }]);
    });

    await page.waitForFunction(() => {
      const banner = document.getElementById('panel').shadowRoot.getElementById('discovery-banner');
      return banner.style.display === 'none';
    }, { timeout: 5000 });
  });

  test('non-admins see no Add button, gear buttons, or banner', async ({ page }) => {
    await page.addInitScript((flow) => { window.__mockFlowProgress = [flow]; }, DISCOVERED_FLOW);
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(err));

    await page.goto(`${baseUrl}/harness.html`);
    await page.evaluate((frameList) => {
      const hass = window.__buildMockHass(frameList);
      hass.user = { is_admin: false };
      document.getElementById('panel').hass = hass;
    }, FRAMES);
    await page.waitForFunction(
      (n) => {
        const panel = document.getElementById('panel');
        return panel && panel._frames && panel._frames.length === n && panel._loaded;
      },
      FRAMES.length,
      { timeout: 10000 }
    );

    const visibility = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        addBtn: root.getElementById('frame-add-btn').style.display,
        // Non-admin tiles are rendered without a hover overlay.
        overlayCount: root.querySelectorAll('.wall-tile-hover-overlay').length,
        tileCount: root.querySelectorAll('.wall-tile').length,
        banner: root.getElementById('discovery-banner').style.display,
      };
    });
    expect(visibility.addBtn).toBe('none');
    expect(visibility.tileCount).toBe(2);
    expect(visibility.overlayCount).toBe(0);
    expect(visibility.banner).toBe('none');
    expect(pageErrors).toEqual([]);
  });
});
