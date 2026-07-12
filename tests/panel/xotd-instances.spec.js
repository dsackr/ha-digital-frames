const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// xOTD ("Daily Content"): installed like any other Add-on (a plain
// Install/Remove switch, XotdManager.async_set_enabled -- see
// _buildXotdPackCard in fraimic-panel.js), which reveals the "Daily
// Content" tab. That tab shows one tile per content type (Joke/Quote/
// Scripture/Word/Image); clicking a tile opens the New Instance modal
// pre-selected to that type. Each instance pairs one content_mode with
// one frame and its own schedule.
//
// This mirrors the real scene_packs/index.json "xotd" catalog entry
// closely enough (content_mode + joke/quote/scripture + theme/drop_cap
// fields) to exercise the generic config_schema engine the same way
// agenda-calendar-source.spec.js does for daily_agenda.
const XOTD_PACK = {
  id: 'xotd',
  name: 'xOTD (Day-of-the-Day)',
  description: 'Joke, quote, scripture, or word of the day.',
  category: 'productivity',
  categories: ['productivity'],
  type: 'widget',
  cover: 'addons/xotd/preview_cover.jpg',
  config_schema: [
    {
      name: 'content_mode', type: 'select', label: 'Content Type', default: 'quote',
      options: [
        { value: 'joke', label: 'Joke of the Day' },
        { value: 'quote', label: 'Quote of the Day' },
        { value: 'scripture', label: 'Scripture of the Day' },
        { value: 'word', label: 'Word of the Day' },
      ],
    },
    {
      name: 'joke_feed', type: 'select', label: 'Joke Feed', default: 'icanhazdadjoke',
      options: [{ value: 'icanhazdadjoke', label: 'icanhazdadjoke.com' }, { value: 'custom', label: 'Custom API URL...' }],
      show_if: { field: 'content_mode', equals: 'joke' },
    },
    {
      name: 'quote_feed', type: 'select', label: 'Quote Feed', default: 'zenquotes',
      options: [{ value: 'zenquotes', label: 'ZenQuotes' }, { value: 'custom', label: 'Custom API URL...' }],
      show_if: { field: 'content_mode', equals: 'quote' },
    },
    {
      name: 'scripture_source', type: 'select', label: 'Scripture Source', default: 'daily_api',
      options: [{ value: 'daily_api', label: 'Daily Verse of the Day' }, { value: 'custom_list', label: 'Custom list' }],
      show_if: { field: 'content_mode', equals: 'scripture' },
    },
    // Deliberately no show_if -- these apply "to all 4 text modes", the
    // exact case that once leaked into Image mode's fields too.
    {
      name: 'theme', type: 'select', label: 'Visual Theme', default: 'classic',
      options: [{ value: 'classic', label: 'Classic' }, { value: 'retro_atomic', label: 'Retro Atomic Age' }],
    },
    {
      name: 'drop_cap', type: 'boolean', label: 'Drop Cap', default: false,
    },
  ],
};

function frames() {
  return [
    { entry_id: 'entry_1', title: 'Living Room Frame' },
    { entry_id: 'entry_2', title: 'Office Frame' },
  ];
}

async function openAddonsTab(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
  await page.waitForFunction(() => {
    const root = document.getElementById('panel').shadowRoot;
    return root.getElementById('pack-grid').children.length > 0;
  });
}

function xotdTabButtonDisplay(page) {
  return page.evaluate(() => {
    const btn = document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="xotd"]');
    return btn ? btn.style.display : null;
  });
}

async function openXotdTab(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="xotd"]').click();
  });
  await page.waitForFunction(() => {
    const grid = document.getElementById('panel').shadowRoot.getElementById('xotd-grid');
    return grid && grid.children.length > 0;
  });
}

async function clickModeTile(page, mode) {
  await page.evaluate((m) => {
    const root = document.getElementById('panel').shadowRoot;
    const tiles = [...root.querySelectorAll('.xotd-mode-tile')];
    const tile = tiles.find((t) => t.querySelector('.xotd-mode-tile-title').textContent.toLowerCase().includes(m));
    tile.click();
  }, mode);
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

// Find the xotd instance card whose title contains `titleSubstring`, then
// click a button inside it matching `buttonText`.
async function clickCardButton(page, titleSubstring, buttonText) {
  await page.evaluate(({ titleSubstring, buttonText }) => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.getElementById('xotd-grid').querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.includes(titleSubstring));
    const btn = [...card.querySelectorAll('button')].find((b) => b.textContent.includes(buttonText));
    btn.click();
  }, { titleSubstring, buttonText });
}

function fieldValue(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).value, id);
}

// Effective visibility, not just the row's own inline style: fields with
// no show_if of their own (theme/drop_cap) are hidden by their ancestor
// wrapper (#xotd-text-fields-wrap / #xotd-image-fields-wrap) toggling,
// never by their own row's style.display -- offsetParent is null whenever
// the element or any ancestor has display:none, regardless of which one.
function fieldDisplay(page, id) {
  return page.evaluate((elId) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    if (!el) return null;
    return el.offsetParent !== null ? 'visible' : 'none';
  }, id);
}

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

test.describe('xOTD install gate (Add-ons tab)', () => {
  test('the Daily Content tab is hidden until xOTD is installed', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      expect(await xotdTabButtonDisplay(page)).toBe('none');
    } finally {
      await mock.stop();
    }
  });

  test('xotd appears as a plain Install/Remove card, never the config modal', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK] });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openAddonsTab(page);

      const card = await page.evaluate(() => {
        const root = document.getElementById('panel').shadowRoot;
        const el = [...root.querySelectorAll('.pack-card')]
          .find((c) => c.querySelector('.scene-card-title').textContent.includes('xOTD'));
        return {
          found: !!el,
          hasInstallButton: !!el.querySelector('#xotd-pack-install'),
          buttonLabel: el.querySelector('#xotd-pack-install').textContent.trim(),
        };
      });
      expect(card.found).toBe(true);
      expect(card.hasInstallButton).toBe(true);
      expect(card.buttonLabel).toContain('Install');

      // Clicking Install must never open the generic per-frame config modal.
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-pack-install').click();
      });
      await expect.poll(() => mock.xotdEnabled).toBe(true);
      const widgetModalDisplay = await page.evaluate(() => {
        const overlay = document.getElementById('panel').shadowRoot.getElementById('widget-config-overlay');
        return overlay.style.display;
      });
      expect(widgetModalDisplay).not.toBe('flex');

      // Installing reveals the tab and switches to it.
      expect(await xotdTabButtonDisplay(page)).toBe('');
      const activeTab = await page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('tab-xotd').classList.contains('active'));
      expect(activeTab).toBe(true);
    } finally {
      await mock.stop();
    }
  });

  test('removing xotd deletes every instance and hides the tab again', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdInstances: [{ instance_id: 'xotd_1', content_mode: 'joke', frame_id: 'entry_1', schedule: { type: 'hourly' } }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      expect(await xotdTabButtonDisplay(page)).toBe('');

      await openAddonsTab(page);
      page.once('dialog', (dialog) => dialog.accept());
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-pack-remove').click();
      });

      await expect.poll(() => mock.xotdEnabled).toBe(false);
      expect(mock.xotdInstances.length).toBe(0);
      expect(await xotdTabButtonDisplay(page)).toBe('none');
    } finally {
      await mock.stop();
    }
  });
});

test.describe('xOTD "Daily Content" tab', () => {
  test('creating two instances via mode tiles keeps them independent', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK], xotdEnabled: true });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      // First instance: Joke -> Frame A, hourly.
      await clickModeTile(page, 'joke');
      expect(await fieldValue(page, 'xotd-field-content_mode')).toBe('joke');
      await setFieldValue(page, 'xotd-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });
      await expect.poll(() => mock.xotdInstances.length).toBe(1);

      // Second instance: Scripture -> Frame B, daily at 08:00:00.
      await clickModeTile(page, 'scripture');
      expect(await fieldValue(page, 'xotd-field-content_mode')).toBe('scripture');
      await setFieldValue(page, 'xotd-frame', 'entry_2');
      await setFieldValue(page, 'xotd-schedule-type', 'daily');
      await setFieldValue(page, 'xotd-schedule-time', '08:00:00');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });
      await expect.poll(() => mock.xotdInstances.length).toBe(2);

      const [first, second] = mock.xotdInstances;
      expect(first.content_mode).toBe('joke');
      expect(first.frame_id).toBe('entry_1');
      expect(first.schedule.type).toBe('hourly');
      expect(second.content_mode).toBe('scripture');
      expect(second.frame_id).toBe('entry_2');
      expect(second.schedule).toEqual({ type: 'daily', time: '08:00:00' });

      const titles = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent));
      expect(titles.some((t) => t.includes('Joke') && t.includes('Living Room Frame'))).toBe(true);
      expect(titles.some((t) => t.includes('Scripture') && t.includes('Office Frame'))).toBe(true);
    } finally {
      await mock.stop();
    }
  });

  test('editing one instance\'s schedule does not affect the other', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdEnabled: true,
      xotdInstances: [
        { instance_id: 'xotd_1', content_mode: 'joke', frame_id: 'entry_1', schedule: { type: 'hourly' } },
        { instance_id: 'xotd_2', content_mode: 'scripture', frame_id: 'entry_2', schedule: { type: 'hourly' } },
      ],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      await clickCardButton(page, 'Joke', 'Edit');
      await page.waitForFunction(() => {
        const overlay = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-overlay');
        return overlay && overlay.style.display === 'flex';
      });
      expect(await fieldValue(page, 'xotd-schedule-type')).toBe('hourly');

      await setFieldValue(page, 'xotd-schedule-type', 'daily');
      await setFieldValue(page, 'xotd-schedule-time', '09:30:00');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });

      await expect.poll(() => mock.xotdInstances.find((i) => i.instance_id === 'xotd_1').schedule.type).toBe('daily');
      const edited = mock.xotdInstances.find((i) => i.instance_id === 'xotd_1');
      const untouched = mock.xotdInstances.find((i) => i.instance_id === 'xotd_2');
      expect(edited.schedule).toEqual({ type: 'daily', time: '09:30:00' });
      expect(untouched.schedule).toEqual({ type: 'hourly' });
      expect(untouched.frame_id).toBe('entry_2');
    } finally {
      await mock.stop();
    }
  });

  test('deleting one instance leaves the other running', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdEnabled: true,
      xotdInstances: [
        { instance_id: 'xotd_1', content_mode: 'joke', frame_id: 'entry_1', schedule: { type: 'hourly' } },
        { instance_id: 'xotd_2', content_mode: 'scripture', frame_id: 'entry_2', schedule: { type: 'hourly' } },
      ],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      page.once('dialog', (dialog) => dialog.accept());
      await clickCardButton(page, 'Joke', 'Delete');

      await expect.poll(() => mock.xotdInstances.length).toBe(1);
      expect(mock.xotdInstances[0].instance_id).toBe('xotd_2');

      // The card removal is async (delete -> reload -> re-render), so poll
      // the DOM rather than reading it the instant the server confirms.
      await expect.poll(() => page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent))).toEqual(expect.arrayContaining([expect.stringContaining('Scripture')]));
      const titles = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.querySelectorAll('#xotd-grid .scene-card-title'),
      ].map((el) => el.textContent));
      expect(titles.some((t) => t.includes('Joke'))).toBe(false);
    } finally {
      await mock.stop();
    }
  });

  test('"Send Now" fires the instance immediately', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdEnabled: true,
      xotdInstances: [{ instance_id: 'xotd_1', content_mode: 'joke', frame_id: 'entry_1', schedule: { type: 'hourly' } }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);

      await clickCardButton(page, 'Joke', 'Send Now');

      await expect.poll(() => mock.xotdRunCalls).toEqual(['xotd_1']);
    } finally {
      await mock.stop();
    }
  });

  test('image_album mode\'s album dropdown populates from the library', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(),
      scenePacks: [XOTD_PACK],
      xotdEnabled: true,
      albums: [{ name: 'Vacation', count: 3, cover_image_id: null }, { name: 'Family', count: 5, cover_image_id: null }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await clickModeTile(page, 'image');

      await setFieldValue(page, 'xotd-field-sub_mode', 'image_album');

      const albumOptions = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.getElementById('xotd-field-album').querySelectorAll('option'),
      ].map((o) => o.value));
      expect(albumOptions).toContain('Vacation');
      expect(albumOptions).toContain('Family');
    } finally {
      await mock.stop();
    }
  });

  test('content_mode switching shows/hides the right field groups', async ({ page }) => {
    const mock = createMockServer({
      frames: frames(), scenePacks: [XOTD_PACK], xotdEnabled: true, albums: [{ name: 'Vacation', count: 1 }],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await clickModeTile(page, 'quote'); // any tile opens the same modal

      await setFieldValue(page, 'xotd-field-content_mode', 'joke');
      expect(await fieldDisplay(page, 'xotd-row-joke_feed')).toBe('visible');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-sub_mode')).toBe('none');
      // theme/drop_cap have no show_if of their own -- they must still show
      // for every text mode via the wrapping container.
      expect(await fieldDisplay(page, 'xotd-row-theme')).toBe('visible');
      expect(await fieldDisplay(page, 'xotd-row-drop_cap')).toBe('visible');

      await setFieldValue(page, 'xotd-field-content_mode', 'quote');
      expect(await fieldDisplay(page, 'xotd-row-joke_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('visible');

      await setFieldValue(page, 'xotd-field-content_mode', 'image');
      expect(await fieldDisplay(page, 'xotd-row-quote_feed')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-sub_mode')).toBe('visible');
      // The bug this test pins: Visual Theme / Drop Cap must NOT show for
      // Image mode -- they're text-mode-only fields with no show_if of
      // their own, so without the wrapping container they'd leak through.
      expect(await fieldDisplay(page, 'xotd-row-theme')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-drop_cap')).toBe('none');
      // sub_mode defaults to image_feed -- feed_provider shows, album doesn't.
      expect(await fieldDisplay(page, 'xotd-row-feed_provider')).toBe('visible');
      expect(await fieldDisplay(page, 'xotd-row-album')).toBe('none');

      await setFieldValue(page, 'xotd-field-sub_mode', 'image_album');
      expect(await fieldDisplay(page, 'xotd-row-feed_provider')).toBe('none');
      expect(await fieldDisplay(page, 'xotd-row-album')).toBe('visible');

      await setFieldValue(page, 'xotd-field-sub_mode', 'image_feed');
      await setFieldValue(page, 'xotd-field-feed_provider', 'nasa_apod');
      expect(await fieldDisplay(page, 'xotd-row-nasa_api_key')).toBe('visible');
      await setFieldValue(page, 'xotd-field-feed_provider', 'wikimedia_potd');
      expect(await fieldDisplay(page, 'xotd-row-nasa_api_key')).toBe('none');
    } finally {
      await mock.stop();
    }
  });

  test('submit is rejected with no target frame selected', async ({ page }) => {
    const mock = createMockServer({ frames: frames(), scenePacks: [XOTD_PACK], xotdEnabled: true });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: frames() });
      await openXotdTab(page);
      await clickModeTile(page, 'joke');

      await setFieldValue(page, 'xotd-frame', '');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('xotd-modal-submit').click();
      });

      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('xotd-modal-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('select a target frame');
      expect(mock.xotdInstances.length).toBe(0);
    } finally {
      await mock.stop();
    }
  });
});
