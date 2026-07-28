// Coverage for embedded frame management (the per-card gear menu) and the
// discovered-frames banner: rename via config_entries/update, remove via
// the config entry DELETE endpoint, banner rendering from flow-subscribe
// events, resuming a discovered flow without deleting it on cancel, and
// admin gating of all of the above.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton, clickWallTileQuadrant } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'portrait', host: '192.168.1.10', orientation_entity_id: 'select.entry_1_orientation', orientation_locked: false, device_orientation: 'portrait' },
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
    expect(details.orientation).toBe('Portrait (Discovered)');
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

  test('info overlay → lock/unlock/discover orientation controls', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openInfoFor(page, 'entry_1');

    // 1. Initial State: Unlocked, device orientation portrait discovered
    let state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        portraitActive: root.getElementById('frame-info-portrait').classList.contains('active'),
        landscapeActive: root.getElementById('frame-info-landscape').classList.contains('active'),
      };
    });
    expect(state.text).toBe('Portrait (Discovered)');
    expect(state.portraitActive).toBe(false);
    expect(state.landscapeActive).toBe(false);

    // Prepare mock frames data mutation in Node.js BEFORE the click triggers discovery
    FRAMES[0].orientation_locked = true;
    FRAMES[0].orientation = 'landscape';

    // 2. Click Landscape to lock it
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-info-landscape').click();
    });

    // Expect callService was triggered to lock to Landscape
    await expect.poll(() => page.evaluate(() => window.__serviceCalls)).toEqual([
      {
        domain: 'select',
        service: 'select_option',
        data: {
          entity_id: 'select.entry_1_orientation',
          option: 'Landscape',
        },
      },
    ]);

    // Check that the UI correctly re-rendered to Landscape (Locked)
    await expect.poll(() => page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        portraitActive: root.getElementById('frame-info-portrait').classList.contains('active'),
        landscapeActive: root.getElementById('frame-info-landscape').classList.contains('active'),
      };
    })).toEqual({
      text: 'Landscape (Locked)',
      portraitActive: false,
      landscapeActive: true,
    });

    // Reset service calls
    await page.evaluate(() => { window.__serviceCalls = []; });

    // Mutate mock frames data to simulate backend unlock before we click to unlock
    FRAMES[0].orientation_locked = false;
    FRAMES[0].orientation = 'portrait'; // defaults back to discovered portrait

    // Click Landscape button to deselect/unlock
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-info-landscape').click();
    });

    // Expect callService was triggered to unlock
    await expect.poll(() => page.evaluate(() => window.__serviceCalls)).toEqual([
      {
        domain: 'select',
        service: 'select_option',
        data: {
          entity_id: 'select.entry_1_orientation',
          option: 'Auto (any picture, Fraimic default)',
        },
      },
    ]);

    // Check that the UI correctly re-rendered to Portrait (Discovered)
    await expect.poll(() => page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        portraitActive: root.getElementById('frame-info-portrait').classList.contains('active'),
        landscapeActive: root.getElementById('frame-info-landscape').classList.contains('active'),
      };
    })).toEqual({
      text: 'Portrait (Discovered)',
      portraitActive: false,
      landscapeActive: false,
    });
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

// Regression coverage for the hover-overlay quadrants routing to the wrong
// action: `openInfoFor`/`openConfigureFor` above (and the tests that use
// them) drive the overlay via element.click(), which synthesizes a bare
// 'click' event directly on the quadrant div. That never exercises the
// tile's real pointerdown -> _wallBeginDrag -> pointerup path, so it can't
// catch a bug that only manifests there -- specifically, `_wallBeginDrag`
// adds the `dragging` class to the tile as soon as the mouse goes down
// (before it's known whether this will turn into an actual drag), and
// `.wall-tile.dragging .wall-tile-hover-overlay` sets `pointer-events:
// none !important`. That flips the instant the button is pressed, so by
// pointerup the overlay is no longer hit-testable and
// `e.composedPath()[0]` resolves to whatever is under it
// (`.wall-tile-media`) instead of the quadrant -- `_onWallPointerUp` then
// always falls through to its "default fallback" (open the image picker),
// regardless of which quadrant was actually clicked. These tests click
// each quadrant with real mouse move/down/up, the only way to observe that.
test.describe('Frame management: hover overlay quadrants (real mouse input)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES });
    baseUrl = await mockServer.start();
    page.on('console', msg => console.log('BROWSER_LOG:', msg.text()));
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('select-image quadrant opens the image picker', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await clickWallTileQuadrant(page, 'entry_1', 'select-image');
    await expect(page.locator('#panel')).toBeVisible();
    const open = await page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block');
    expect(open).toBe(true);
  });

  test('info quadrant opens the Frame Info popup, not the image picker', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await clickWallTileQuadrant(page, 'entry_1', 'info');
    const state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        infoOpen: root.getElementById('frame-settings-overlay').style.display === 'flex',
        pickerOpen: root.getElementById('wall-image-picker-overlay').style.display === 'block',
      };
    });
    expect(state.infoOpen).toBe(true);
    expect(state.pickerOpen).toBe(false);
  });

  test('configure quadrant opens the options flow modal, not the image picker', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await clickWallTileQuadrant(page, 'entry_1', 'configure');
    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step;
    }, { timeout: 5000 });
    const pickerOpen = await page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-overlay').style.display === 'block');
    expect(pickerOpen).toBe(false);
  });

  test('remove-tile quadrant removes the frame from the wall, not the image picker', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await clickWallTileQuadrant(page, 'entry_1', 'remove-tile');
    const state = await page.evaluate((id) => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        stillPlaced: !!root.querySelector(`.wall-tile[data-entry-id="${id}"]`),
        pickerOpen: root.getElementById('wall-image-picker-overlay').style.display === 'block',
      };
    }, 'entry_1');
    expect(state.stillPlaced).toBe(false);
    expect(state.pickerOpen).toBe(false);
  });
});
