// KPF 37: Mobile-first responsive shell, touch Frame Card Deck, locked/unlocked
// wall layout toggle, bottom-sheet image picker, compact crop actions, and
// de-cluttered mobile library grid.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const FRAMES = [
  {
    entry_id: 'entry_living',
    title: 'Living Room 13.3"',
    width: 1600,
    height: 1200,
    size: '13.3"',
    orientation: 'landscape',
    last_image_id: 'img_wave',
    has_thumbnail: true,
  },
  {
    entry_id: 'entry_nook',
    title: 'Reading Nook 7.3"',
    width: 480,
    height: 800,
    size: '7.3"',
    orientation: 'portrait',
    queued: true,
    queued_image_id: 'img_fuji',
    has_thumbnail: true,
  },
];

const IMAGES = [
  { image_id: 'img_wave', filename: 'great-wave.png', albums: ['Favorites'] },
  { image_id: 'img_fuji', filename: 'red-fuji.png', albums: ['Favorites'] },
];

const ALBUMS = [
  { name: 'Favorites', count: 2, cover_image_id: 'img_wave' },
];

test.describe('Mobile UX (Variant A: Mobile App Shell & Frame Deck)', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockServer = createMockServer({ frames: FRAMES, images: IMAGES, albums: ALBUMS });
    baseUrl = await mockServer.start();
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('docks the tab bar to the bottom of the mobile viewport and defaults the wall to locked Content Mode', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    const mobileShell = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      const root = panel.shadowRoot;
      let menuToggled = false;
      panel.addEventListener('hass-toggle-menu', () => { menuToggled = true; }, { once: true });
      root.getElementById('ha-menu-btn').click();

      const tabBar = root.getElementById('tab-bar');
      const tabStyle = getComputedStyle(tabBar);
      const palette = root.getElementById('wall-palette');
      const canvas = root.getElementById('wall-canvas');
      const deck = root.getElementById('wall-frame-deck');
      const wallStrip = root.getElementById('wall-strip');
      const firstCard = deck.querySelector('.wall-deck-card');
      return {
        menuToggled,
        tabPosition: tabStyle.position,
        tabBottom: tabStyle.bottom,
        wallStripWidth: Math.round(wallStrip.getBoundingClientRect().width),
        paletteDisplay: getComputedStyle(palette).display,
        canvasDisplay: getComputedStyle(canvas).display,
        canvasTouchAction: getComputedStyle(canvas).touchAction,
        deckDisplay: getComputedStyle(deck).display,
        deckCardCount: deck.querySelectorAll('.wall-deck-card').length,
        firstCardTop: Math.round(firstCard.getBoundingClientRect().top),
      };
    });

    expect(mobileShell.menuToggled).toBe(true);
    expect(mobileShell.tabPosition).toBe('fixed');
    expect(mobileShell.tabBottom).toBe('0px');
    expect(mobileShell.wallStripWidth).toBeGreaterThan(250);
    // Default Content Mode hides the desktop canvas/palette clutter so the
    // Frame Card Deck sits immediately above the fold.
    expect(mobileShell.paletteDisplay).toBe('none');
    expect(mobileShell.canvasDisplay).toBe('none');
    expect(mobileShell.canvasTouchAction).toBe('pan-y');
    expect(mobileShell.deckDisplay).toBe('flex');
    expect(mobileShell.deckCardCount).toBe(2);
    expect(mobileShell.firstCardTop).toBeLessThan(350);

    // Toggling "✎ Edit Layout" reveals the palette and full-width canvas with touch-action: none.
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-mobile-layout-btn').click();
    });

    const editMode = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const canvas = root.getElementById('wall-canvas');
      return {
        btnText: root.getElementById('wall-mobile-layout-btn').textContent,
        paletteDisplay: getComputedStyle(root.getElementById('wall-palette')).display,
        canvasDisplay: getComputedStyle(canvas).display,
        canvasWidth: Math.round(canvas.getBoundingClientRect().width),
        canvasTouchAction: getComputedStyle(canvas).touchAction,
      };
    });
    expect(editMode.btnText).toContain('Done Layout');
    expect(editMode.paletteDisplay).toBe('flex');
    expect(editMode.canvasDisplay).toBe('block');
    expect(editMode.canvasWidth).toBeGreaterThan(300);
    expect(editMode.canvasTouchAction).toBe('none');
  });

  test('renders 3-state status badges on Frame Deck cards and stages/crops art via touch actions without hover', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    const initialBadges = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const cards = [...root.querySelectorAll('#wall-frame-deck .wall-deck-card')];
      return cards.map((c) => ({
        entryId: c.dataset.entryId,
        badgeKind: c.querySelector('.wall-deck-badge')?.dataset.kind || null,
        statusHtml: c.querySelector('.wall-deck-status')?.innerHTML || '',
      }));
    });

    expect(initialBadges).toEqual([
      expect.objectContaining({ entryId: 'entry_living', badgeKind: 'onframe' }),
      expect.objectContaining({ entryId: 'entry_nook', badgeKind: 'ondeck' }),
    ]);
    expect(initialBadges[0].statusHtml).toContain('90%');

    // Tap "🖼 Change Art" on the first Frame Deck card -> opens the bottom-sheet picker
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.querySelector('.wall-deck-card[data-entry-id="entry_living"] [data-deck-action="select-image"]').click();
    });

    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#wall-image-picker-grid .image-picker-cell').length > 0
    );

    const pickerSheet = await page.evaluate(() => {
      const box = document.getElementById('panel').shadowRoot.getElementById('wall-image-picker-box');
      const rect = box.getBoundingClientRect();
      return {
        bottom: Math.round(rect.bottom),
        width: Math.round(rect.width),
      };
    });
    expect(pickerSheet.bottom).toBe(844);
    expect(pickerSheet.width).toBe(390);

    // Pick 'img_fuji' -> stages onto entry_living and updates the deck card badge to 'staged'
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.querySelector('#wall-image-picker-grid .image-picker-cell[data-image-id="img_fuji"]').click();
    });

    const stagedBadge = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      return root.querySelector('.wall-deck-card[data-entry-id="entry_living"] .wall-deck-badge')?.dataset.kind;
    });
    expect(stagedBadge).toBe('staged');

    // Tap "✂ Crop" directly on the Frame Deck card -> opens #editor-overlay pre-targeted at Living Room 13.3"
    await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      root.querySelector('.wall-deck-card[data-entry-id="entry_living"] [data-deck-action="crop"]').click();
    });

    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.getElementById('editor-overlay').style.display === 'flex'
    );

    const editorLayout = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const actions = root.querySelector('.editor-actions');
      return {
        target: root.getElementById('editor-frame-select').value,
        title: root.getElementById('editor-title').textContent,
        actionsDisplay: getComputedStyle(actions).display,
      };
    });
    expect(editorLayout.target).toBe('sensor.entry_living_battery');
    expect(editorLayout.title).toBe('red-fuji.png');
    expect(editorLayout.actionsDisplay).toBe('grid');
  });

  test('renders a clean 2-column photo grid in My Gallery on mobile with per-card button stacks hidden', async ({ page }) => {
    await gotoPanel(page, baseUrl, { frames: FRAMES });

    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('.tab-btn[data-tab="my_gallery"]').click();
    });
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#lib-grid .album-tile').length > 0
    );
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.querySelector('#lib-grid .album-tile .album-name').click();
    });
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('#lib-grid .lib-card').length > 0
    );

    const galleryState = await page.evaluate(() => {
      const root = document.getElementById('panel').shadowRoot;
      const card = root.querySelector('#lib-grid .lib-card');
      const btns = card.querySelector('.btns');
      return {
        btnsDisplay: getComputedStyle(btns).display,
      };
    });
    expect(galleryState.btnsDisplay).toBe('none');
  });
});
