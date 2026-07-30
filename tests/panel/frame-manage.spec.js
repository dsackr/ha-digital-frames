// Coverage for embedded frame management (the per-card gear menu) and the
// discovered-frames banner: rename via config_entries/update, remove via
// the config entry DELETE endpoint, banner rendering from flow-subscribe
// events, resuming a discovered flow without deleting it on cancel, and
// admin gating of all of the above.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, clickPanelButton, clickWallTileQuadrant } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'portrait', host: '192.168.1.10', orientation_entity_id: 'select.entry_1_orientation', orientation_locked: false, device_orientation: 'portrait', driver: 'fraimic', origin: 'official', keep_awake_actual: true, sleep_minutes_actual: 25 },
  { entry_id: 'entry_2', title: 'Office Frame', width: 800, height: 480, orientation: 'landscape', host: '192.168.1.20', driver: 'meural', origin: 'meural' },
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

// Save Changes closes the modal and re-discovers after a fixed delay
// (_refreshAfterEntryChange's setTimeout) rather than on a signal this test
// can await -- poll-reopen instead of a single fixed sleep so the assertion
// isn't a race against wall-clock time on a loaded CI/worker machine. Also
// wait for the Save Changes button to re-enable: it's disabled for the
// whole span of the click handler, which doesn't resolve (and re-enable it)
// until _refreshAfterEntryChange finishes -- the same async chain that
// updates the text this helper is polling for, so a fast reopen can catch
// the right text with the button still mid-save-handler and disabled.
async function reopenUntilOrientationText(page, entryId, expectedText) {
  await expect.poll(async () => {
    await openInfoFor(page, entryId);
    return page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        saveEnabled: !root.getElementById('frame-settings-save').disabled,
      };
    });
  }, { timeout: 10000 }).toEqual({ text: expectedText, saveEnabled: true });
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
    await clickPanelButton(page, 'frame-settings-save');

    // Both registries must be updated: entry title alone leaves the device
    // page showing the creation-time name.
    await expect.poll(() => page.evaluate(
      () => window.__wsCalls.filter((c) => c.type === 'config_entries/update' || c.type === 'config/device_registry/update')
    )).toEqual([
      { type: 'config_entries/update', entry_id: 'entry_1', title: 'Kitchen Frame' },
      { type: 'config/device_registry/update', device_id: 'entry_1', name_by_user: 'Kitchen Frame' },
    ]);
  });

  test('info overlay → orientation lock is staged locally and only applied on Save Changes', async ({ page }) => {
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

    // 2. Click Landscape to stage a lock -- no service call should fire yet,
    // it's a local preview only (matches the Name field, which has never
    // auto-saved either).
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-info-landscape').click();
    });

    state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        portraitActive: root.getElementById('frame-info-portrait').classList.contains('active'),
        landscapeActive: root.getElementById('frame-info-landscape').classList.contains('active'),
        serviceCalls: window.__serviceCalls,
      };
    });
    expect(state.text).toBe('Landscape (Locked)');
    expect(state.landscapeActive).toBe(true);
    expect(state.serviceCalls).toEqual([]);

    // Prepare mock frames data mutation in Node.js BEFORE Save Changes
    // triggers a post-save re-discovery.
    FRAMES[0].orientation_locked = true;
    FRAMES[0].orientation = 'landscape';

    // 3. Click Save Changes -- now the service call fires.
    await clickPanelButton(page, 'frame-settings-save');

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

    // Save Changes closes the modal; reopen (polling past the
    // _refreshAfterEntryChange delay) to continue the unlock flow.
    await page.evaluate(() => { window.__serviceCalls = []; });
    await reopenUntilOrientationText(page, 'entry_1', 'Landscape (Locked)');

    state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        landscapeActive: root.getElementById('frame-info-landscape').classList.contains('active'),
      };
    });
    expect(state.text).toBe('Landscape (Locked)');
    expect(state.landscapeActive).toBe(true);

    // Mutate mock frames data to simulate backend unlock before Save Changes.
    FRAMES[0].orientation_locked = false;
    FRAMES[0].orientation = 'portrait'; // defaults back to discovered portrait

    // 4. Click the already-active Landscape button to stage an unlock.
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-info-landscape').click();
    });
    expect(await page.evaluate(() => window.__serviceCalls)).toEqual([]);

    await clickPanelButton(page, 'frame-settings-save');

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

    // Reopen and check that the UI correctly re-rendered to Portrait (Discovered)
    await reopenUntilOrientationText(page, 'entry_1', 'Portrait (Discovered)');
    state = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        portraitActive: root.getElementById('frame-info-portrait').classList.contains('active'),
        landscapeActive: root.getElementById('frame-info-landscape').classList.contains('active'),
      };
    });
    expect(state).toEqual({
      text: 'Portrait (Discovered)',
      portraitActive: false,
      landscapeActive: false,
    });
  });

  test('info overlay → orientation icons stay in a fixed position regardless of label length', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openInfoFor(page, 'entry_1');

    // entry_1 starts unlocked with "Portrait (Discovered)" -- a long label.
    const initial = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        x: root.getElementById('frame-info-portrait').getBoundingClientRect().left,
      };
    });
    expect(initial.text).toBe('Portrait (Discovered)');

    // Staging a landscape lock swaps in a differently-sized label
    // ("Landscape (Locked)") without any network round-trip.
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-info-landscape').click();
    });
    const staged = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return {
        text: root.getElementById('frame-info-orientation').textContent,
        x: root.getElementById('frame-info-portrait').getBoundingClientRect().left,
      };
    });
    expect(staged.text).toBe('Landscape (Locked)');

    // The icon row anchors to the right edge of the modal (justify-content:
    // space-between) instead of trailing the variable-width label text, so
    // the icons must not shift position as the label changes length.
    expect(staged.x).toBe(initial.x);
  });

  test('info overlay → Rediscover polls the frame immediately without staging/saving', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openInfoFor(page, 'entry_1');

    expect(await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.getElementById('frame-info-orientation').textContent;
    })).toBe('Portrait (Discovered)');

    // Simulate the frame having been physically rotated since the last poll.
    FRAMES[0].device_orientation = 'landscape';

    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-info-poll').click();
    });

    await expect.poll(() => mockServer.pollOrientationCalls).toEqual([{ entry_id: 'entry_1' }]);

    // No select.select_option call -- rediscovering is not a lock edit.
    expect(await page.evaluate(() => window.__serviceCalls)).toEqual([]);

    await expect.poll(() => page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.getElementById('frame-info-orientation').textContent;
    })).toBe('Landscape (Discovered)');
  });

  test('configure options flow modal → advanced settings collapsible toggle works', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await openConfigureFor(page, 'entry_1');

    await page.waitForFunction(() => {
      const panel = document.getElementById('panel');
      return panel._flowModal && panel._flowModal.step && panel._flowModal.step.step_id === 'init';
    }, { timeout: 5000 });

    // Frame Type is fixed at add time — not re-offered when size is set.
    const hasResolutionField = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return !!root.getElementById('flow-field-resolution');
    });
    expect(hasResolutionField).toBe(false);

    // Always-on shows a friendly label (not raw frame_always_on).
    const alwaysOnLabel = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const input = root.getElementById('flow-field-frame_always_on');
      const row = input && input.closest('.modal-row');
      const label = row && row.querySelector('label');
      return label ? label.textContent : null;
    });
    expect(alwaysOnLabel).toMatch(/Always on/i);

    // Assert advanced fields (scan_interval, fast_poll_when_queued) hidden initially
    const advancedHiddenBefore = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const scan = root.getElementById('flow-field-scan_interval');
      const fast = root.getElementById('flow-field-fast_poll_when_queued');
      return {
        scan: !!(scan && scan.offsetParent !== null),
        fast: !!(fast && fast.offsetParent !== null),
        fastExists: !!fast,
      };
    });
    expect(advancedHiddenBefore.scan).toBe(false);
    expect(advancedHiddenBefore.fast).toBe(false);
    expect(advancedHiddenBefore.fastExists).toBe(true);

    // Click the Advanced Settings link to expand it
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const toggle = root.querySelector('.options-advanced-toggle');
      toggle.click();
    });

    // Assert advanced wake-hunt + poll fields are visible after clicking toggle
    const advancedVisibleAfter = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const scan = root.getElementById('flow-field-scan_interval');
      const fast = root.getElementById('flow-field-fast_poll_when_queued');
      return {
        scan: !!(scan && scan.offsetParent !== null),
        fast: !!(fast && fast.offsetParent !== null),
      };
    });
    expect(advancedVisibleAfter.scan).toBe(true);
    expect(advancedVisibleAfter.fast).toBe(true);
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

  test('info overlay → shows UI link icon next to IP Address and Keep Awake status', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openInfoFor(page, 'entry_1');

    const infoState = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const uiLink = root.getElementById('frame-ui-link');
      const keepAwakeRow = root.getElementById('frame-info-keep-awake-row');
      const keepAwakeVal = root.getElementById('frame-info-keep-awake');
      return {
        uiLinkVisible: uiLink.style.display !== 'none',
        uiLinkHref: uiLink.href,
        keepAwakeVisible: keepAwakeRow.style.display === 'flex',
        keepAwakeText: keepAwakeVal.textContent,
      };
    });

    expect(infoState.uiLinkVisible).toBe(true);
    expect(infoState.uiLinkHref).toBe('http://192.168.1.10/portal');
    expect(infoState.keepAwakeVisible).toBe(true);
    expect(infoState.keepAwakeText).toBe('Yes (Sleep: 25m)');
  });

  test('info overlay → shows Meural UI link correctly', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openInfoFor(page, 'entry_2');

    const infoState = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const uiLink = root.getElementById('frame-ui-link');
      return {
        uiLinkVisible: uiLink.style.display !== 'none',
        uiLinkHref: uiLink.href,
      };
    });

    expect(infoState.uiLinkVisible).toBe(true);
    expect(infoState.uiLinkHref).toBe('http://192.168.1.20/remote');
  });

  test('configure options flow modal → greys out always_on and sleep_minutes for official Fraimic', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    
    // Open info settings first so _frameSettingsTarget is populated
    await openInfoFor(page, 'entry_1');
    
    // Now trigger configure flow from panel
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.getElementById('frame-settings-close').click();
    });
    
    await openConfigureFor(page, 'entry_1');

    // Disabled + greyed, but values reflect *detected* keep_awake / sleep
    // (entry_1 has keep_awake_actual: true, sleep_minutes_actual: 25).
    const fieldsState = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const alwaysOn = root.getElementById('flow-field-frame_always_on');
      const sleepMin = root.getElementById('flow-field-frame_sleep_minutes');
      const alwaysRow = alwaysOn.closest('.modal-row');
      return {
        alwaysOnDisabled: alwaysOn.disabled,
        alwaysOnChecked: alwaysOn.checked,
        alwaysOnOpacity: alwaysRow.style.opacity,
        alwaysOnHint: (alwaysRow.querySelector('.modal-file-summary') || {}).textContent || '',
        sleepMinDisabled: sleepMin.disabled,
        sleepMinValue: sleepMin.value,
        sleepMinOpacity: sleepMin.closest('.modal-row').style.opacity,
      };
    });

    expect(fieldsState.alwaysOnDisabled).toBe(true);
    expect(fieldsState.alwaysOnChecked).toBe(true);
    expect(fieldsState.alwaysOnOpacity).toBe('0.5');
    expect(fieldsState.alwaysOnHint).toMatch(/detected|read-only/i);
    expect(fieldsState.alwaysOnHint).toMatch(/always on/i);
    expect(fieldsState.sleepMinDisabled).toBe(true);
    expect(fieldsState.sleepMinValue).toBe('25');
    expect(fieldsState.sleepMinOpacity).toBe('0.5');
  });
});
