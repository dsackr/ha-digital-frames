const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

// The Daily Agenda add-on's install form used to force a Google/iCal URL as
// a required field, with no way to pick one of the calendars Home Assistant
// already knows about. Regression coverage for the fix: the calendar_url
// field is now optional, and defaults to a "Home Assistant Calendar" picker
// backed by hass.states, with the iCal URL as an alternate mode.
const DAILY_AGENDA_PACK = {
  id: 'daily_agenda',
  name: 'Daily Agenda',
  description: 'Calendar and weather widget.',
  category: 'productivity',
  categories: ['productivity'],
  type: 'widget',
  cover: 'addons/daily_agenda/preview_cover.jpg',
  config_schema: [
    {
      name: 'calendar_source', type: 'select', label: 'Calendar Source', default: 'ha',
      options: [
        { value: 'ha', label: 'Home Assistant Calendar' },
        { value: 'ical', label: 'Google Calendar / iCal URL' },
      ],
    },
    {
      name: 'ha_calendar_entity', type: 'entity', domain: 'calendar', label: 'Home Assistant Calendar',
      required: false, show_if: { field: 'calendar_source', equals: 'ha' },
    },
    {
      name: 'calendar_url', type: 'string', label: 'Calendar iCal URL', required: true,
      placeholder: 'https://calendar.google.com/...', show_if: { field: 'calendar_source', equals: 'ical' },
    },
    { name: 'zip_code', type: 'string', label: 'ZIP Code or City Name', required: false, placeholder: 'e.g. 90210 or London', group: 'weather' },
  ],
};

async function openAddons(page) {
  await page.evaluate(() => {
    document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="addons"]').click();
  });
}

async function openDailyAgendaModal(page) {
  await page.evaluate(() => {
    const root = document.getElementById('panel').shadowRoot;
    const card = [...root.querySelectorAll('.pack-card')]
      .find((c) => c.querySelector('.scene-card-title').textContent.trim() === 'Daily Agenda');
    card.querySelector('.pack-cover').click();
  });
  await page.waitForFunction(() => {
    const overlay = document.getElementById('panel').shadowRoot.getElementById('widget-config-overlay');
    return overlay && overlay.style.display === 'flex';
  });
}

function fieldValue(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).value, id);
}

function fieldDisplay(page, id) {
  return page.evaluate((elId) => document.getElementById('panel').shadowRoot.getElementById(elId).style.display, id);
}

async function setFieldValue(page, id, value) {
  await page.evaluate(({ elId, val }) => {
    const el = document.getElementById('panel').shadowRoot.getElementById(elId);
    el.value = val;
    el.dispatchEvent(new Event('change'));
  }, { elId: id, val: value });
}

test.describe('Daily Agenda add-on: calendar source picker', () => {
  test('defaults to the Home Assistant calendar picker and installs without an iCal URL', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [DAILY_AGENDA_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });

      // Seed a couple of HA calendar entities, same as a real hass object
      // would already have populated before the panel ever opens.
      await page.evaluate(() => {
        const states = document.getElementById('panel')._hass.states;
        states['calendar.home'] = { state: 'off', attributes: { friendly_name: 'Home' } };
        states['calendar.work'] = { state: 'off', attributes: { friendly_name: 'Work Calendar' } };
      });

      await openAddons(page);
      await openDailyAgendaModal(page);

      expect(await fieldValue(page, 'widget-field-calendar_source')).toBe('ha');
      expect(await fieldDisplay(page, 'widget-row-ha_calendar_entity')).toBe('block');
      expect(await fieldDisplay(page, 'widget-row-calendar_url')).toBe('none');

      const entityOptions = await page.evaluate(() => [
        ...document.getElementById('panel').shadowRoot.getElementById('widget-field-ha_calendar_entity').options,
      ].map((o) => o.value));
      expect(entityOptions).toEqual(['calendar.home', 'calendar.work']);

      await setFieldValue(page, 'widget-config-frame', 'entry_1');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });

      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.calendar_source).toBe('ha');
      expect(mock.installCalls[0].config.ha_calendar_entity).toBe('calendar.home');
      expect(mock.installCalls[0].config.calendar_url).toBe('');
    } finally {
      await mock.stop();
    }
  });

  test('switching to iCal mode requires a URL and is saved/restored correctly', async ({ page }) => {
    const mock = createMockServer({
      frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }],
      scenePacks: [DAILY_AGENDA_PACK],
    });
    const baseUrl = await mock.start();
    try {
      await gotoPanel(page, baseUrl, { frames: [{ entry_id: 'entry_1', title: 'Living Room Frame' }] });
      await page.evaluate(() => {
        document.getElementById('panel')._hass.states['calendar.home'] = { state: 'off', attributes: { friendly_name: 'Home' } };
      });

      await openAddons(page);
      await openDailyAgendaModal(page);

      await setFieldValue(page, 'widget-field-calendar_source', 'ical');
      expect(await fieldDisplay(page, 'widget-row-ha_calendar_entity')).toBe('none');
      expect(await fieldDisplay(page, 'widget-row-calendar_url')).toBe('block');

      await setFieldValue(page, 'widget-config-frame', 'entry_1');

      // Blank URL in iCal mode must be rejected client-side (no install call).
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      const fb = await page.evaluate(() => {
        const el = document.getElementById('panel').shadowRoot.getElementById('widget-config-fb');
        return { text: el.textContent, display: el.style.display };
      });
      expect(fb.display).toBe('block');
      expect(fb.text).toContain('Calendar iCal URL is required');
      expect(mock.installCalls.length).toBe(0);

      await setFieldValue(page, 'widget-field-calendar_url', 'https://calendar.google.com/private-abc/basic.ics');
      await page.evaluate(() => {
        document.getElementById('panel').shadowRoot.getElementById('widget-config-submit').click();
      });
      await expect.poll(() => mock.installCalls.length).toBe(1);
      expect(mock.installCalls[0].config.calendar_source).toBe('ical');
      expect(mock.installCalls[0].config.calendar_url).toBe('https://calendar.google.com/private-abc/basic.ics');
      // The (hidden) entity picker still rides along in the payload -- the
      // backend only reads it when calendar_source is 'ha', so its presence
      // here is harmless, not a bug.
    } finally {
      await mock.stop();
    }
  });
});
