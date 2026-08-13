// Wall canvas zoom (buttons, Ctrl/Cmd+wheel) and pan (spacebar+drag,
// middle-click drag, two-finger touch drag) -- a view-only convenience,
// never persisted with the layout. See KEY_PRODUCT_FLOWS.md KPF 19.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openScenesTab } = require('./fixtures/panel-page');

// Six frames spread far apart so total content size vastly exceeds any
// reasonable test viewport -- scrollLeft/scrollTop must have real overflow
// to move through, or setting/observing them is a no-op regardless of any
// pan gesture (the browser clamps scrollLeft to 0 with nothing to scroll).
const FRAMES = Array.from({ length: 6 }, (_, i) => ({
  entry_id: `entry_${i}`, title: `Frame ${i}`, width: 1200, height: 1600, orientation: 'auto',
}));
const DEFAULT_WALL = {
  wall_id: 'default', name: 'All Frames', kind: 'default',
  placements: Object.fromEntries(FRAMES.map((f, i) => [
    f.entry_id, { x: (i % 3) * 3000, y: Math.floor(i / 3) * 3000 },
  ])),
};

function zoomOf(page) {
  return page.evaluate(() => document.getElementById('panel')._wallZoom);
}
function zoomLabel(page) {
  return page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-zoom-label').textContent);
}
function scrollPos(page) {
  return page.evaluate(() => {
    const c = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
    return { left: c.scrollLeft, top: c.scrollTop };
  });
}
function canvasRect(page) {
  return page.evaluate(() => {
    const r = document.getElementById('panel').shadowRoot.getElementById('wall-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
}

test.describe('Wall canvas zoom and pan', () => {
  let mockServer;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, walls: [DEFAULT_WALL] });
    const baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-tile').length === 6
    );
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('starts at 100% and the zoom-in/out/reset buttons step and clamp', async ({ page }) => {
    expect(await zoomOf(page)).toBe(1);
    expect(await zoomLabel(page)).toBe('100%');

    const zoomIn = () => page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-zoom-in-btn').click());
    const zoomOut = () => page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-zoom-out-btn').click());
    const zoomReset = () => page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-zoom-reset-btn').click());

    await zoomIn();
    expect(await zoomOf(page)).toBeCloseTo(1.1, 5);
    expect(await zoomLabel(page)).toBe('110%');

    await zoomReset();
    expect(await zoomOf(page)).toBe(1);

    // Clamp at the floor.
    for (let i = 0; i < 20; i++) await zoomOut();
    expect(await zoomOf(page)).toBeCloseTo(0.25, 5);

    await zoomReset();
    // Clamp at the ceiling.
    for (let i = 0; i < 30; i++) await zoomIn();
    expect(await zoomOf(page)).toBeCloseTo(2.5, 5);
  });

  test('the zoom-layer transform reflects the current zoom', async ({ page }) => {
    await page.evaluate(() => document.getElementById('panel').shadowRoot.getElementById('wall-zoom-in-btn').click());
    const transform = await page.evaluate(() => {
      const canvas = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
      return canvas.querySelector('.wall-zoom-layer').style.transform;
    });
    expect(transform).toBe('scale(1.1)');
  });

  test('Ctrl+wheel zooms; plain wheel does not', async ({ page }) => {
    const rect = await canvasRect(page);
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;

    await page.mouse.move(cx, cy);
    await page.mouse.wheel(0, -100); // plain scroll -- must not zoom
    expect(await zoomOf(page)).toBe(1);

    await page.keyboard.down('Control');
    await page.mouse.wheel(0, -100); // scroll "up" -- zoom in
    await page.keyboard.up('Control');
    const zoomed = await zoomOf(page);
    expect(zoomed).toBeGreaterThan(1);

    await page.keyboard.down('Control');
    await page.mouse.wheel(0, 100); // scroll "down" -- zoom back out
    await page.keyboard.up('Control');
    expect(await zoomOf(page)).toBeLessThan(zoomed);
  });

  test('space+left-drag pans the canvas without moving a tile or starting a marquee', async ({ page }) => {
    // Seed a real scroll position so panning in either direction is observable
    // (a fresh, unscrolled canvas can't scroll further negative/up-left).
    await page.evaluate(() => {
      const c = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
      c.scrollLeft = 100;
      c.scrollTop = 100;
    });
    const before = await scrollPos(page);
    const posBefore = await page.evaluate(() => document.getElementById('panel')._wallPlacements.entry_0);

    const rect = await canvasRect(page);
    const startX = rect.x + rect.width / 2;
    const startY = rect.y + rect.height / 2;

    await page.keyboard.down('Space');
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX - 40, startY - 30, { steps: 5 });
    await page.mouse.up();
    await page.keyboard.up('Space');

    const after = await scrollPos(page);
    // Dragging left/up pans the view right/down -- scroll increases.
    expect(after.left).toBeGreaterThan(before.left);
    expect(after.top).toBeGreaterThan(before.top);

    // Nothing was selected, no tile moved, no marquee left behind.
    const state = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      return {
        selection: [...panel._wallSelection],
        marquee: panel.shadowRoot.querySelector('.wall-marquee'),
        pos: panel._wallPlacements.entry_0,
      };
    });
    expect(state.selection).toEqual([]);
    expect(state.marquee).toBeNull();
    expect(state.pos).toEqual(posBefore);
  });

  test('middle-click drag pans the canvas', async ({ page }) => {
    await page.evaluate(() => {
      const c = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
      c.scrollLeft = 100;
      c.scrollTop = 100;
    });
    const before = await scrollPos(page);
    const rect = await canvasRect(page);
    const startX = rect.x + rect.width / 2;
    const startY = rect.y + rect.height / 2;

    await page.mouse.move(startX, startY);
    await page.mouse.down({ button: 'middle' });
    await page.mouse.move(startX - 40, startY - 30, { steps: 5 });
    await page.mouse.up({ button: 'middle' });

    const after = await scrollPos(page);
    expect(after.left).toBeGreaterThan(before.left);
    expect(after.top).toBeGreaterThan(before.top);
  });

  test('a two-finger touch drag pans and cancels an in-progress single-finger drag', async ({ page }) => {
    await page.evaluate(() => {
      const c = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
      c.scrollLeft = 100;
      c.scrollTop = 100;
    });
    const before = await scrollPos(page);
    const posBefore = await page.evaluate(() => document.getElementById('panel')._wallPlacements.entry_0);

    const rect = await canvasRect(page);
    // Dispatch synthetic multi-pointer touch events directly -- Playwright's
    // page.mouse is single-pointer, and this is the reliable way to
    // simulate two simultaneous touches landing at different points.
    await page.evaluate(({ x, y }) => {
      const canvas = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
      const tile = document.getElementById('panel').shadowRoot.querySelector('.wall-tile[data-entry-id="entry_0"]');
      const fire = (target, type, opts) => target.dispatchEvent(new PointerEvent(type, {
        bubbles: true, composed: true, cancelable: true, pointerType: 'touch', ...opts,
      }));
      // First touch lands on a tile -- starts a single-tile drag.
      fire(tile, 'pointerdown', { pointerId: 1, clientX: x, clientY: y, button: 0 });
      // Second touch lands on empty canvas -- upgrades to two-finger pan,
      // cancelling the tile drag the first touch just started.
      fire(canvas, 'pointerdown', { pointerId: 2, clientX: x + 100, clientY: y, button: 0 });
      window.__wallZoomPanTestPoint = { x, y };
    }, { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 });

    await page.evaluate(() => {
      const canvas = document.getElementById('panel').shadowRoot.getElementById('wall-canvas');
      const { x, y } = window.__wallZoomPanTestPoint;
      const fire = (type, opts) => window.dispatchEvent(new PointerEvent(type, {
        bubbles: true, cancelable: true, pointerType: 'touch', ...opts,
      }));
      fire('pointermove', { pointerId: 1, clientX: x - 40, clientY: y - 30, button: 0 });
      fire('pointermove', { pointerId: 2, clientX: x + 60, clientY: y - 30, button: 0 });
      fire('pointerup', { pointerId: 1, clientX: x - 40, clientY: y - 30, button: 0 });
      fire('pointerup', { pointerId: 2, clientX: x + 60, clientY: y - 30, button: 0 });
    });

    const after = await scrollPos(page);
    expect(after.left).toBeGreaterThan(before.left);
    expect(after.top).toBeGreaterThan(before.top);

    const state = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      return {
        dragGhost: panel.shadowRoot.querySelector('.wall-drag-ghost'),
        draggingClass: panel.shadowRoot.querySelector('.wall-tile.dragging'),
        pos: panel._wallPlacements.entry_0,
      };
    });
    // The tile drag the first touch started must have been torn down, not
    // left as a stuck floating ghost -- and the tile itself never moved.
    expect(state.dragGhost).toBeNull();
    expect(state.draggingClass).toBeNull();
    expect(state.pos).toEqual(posBefore);
  });
});
