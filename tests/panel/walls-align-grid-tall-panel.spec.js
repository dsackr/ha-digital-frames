// Regression: "Align Wall to Grid" must not overlap a physically tall
// panel (e.g. 31.5", which renders far taller on-canvas than 13.3" once
// tiles are scaled to true physical size -- see KPF 19) with whatever row
// gets auto-placed below it. _alignWallToGrid used to assume every row was
// a fixed 160px tall, which held only back when every tile was
// independently normalized to the same longest-pixel-edge size.

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel, openScenesTab, getWallTiles } = require('./fixtures/panel-page');

// Five frames force two auto-placement rows (MAX_PER_ROW=4). The 31.5"
// panel sits first so it lands in row 0; entry_5 is the sole occupant of
// row 1 and must land below the 31.5" tile's real bottom edge.
const FRAMES = [
  { entry_id: 'entry_tall', title: 'Big Wall Frame', width: 1440, height: 2560, size: '31.5', orientation: 'auto' },
  { entry_id: 'entry_2', title: 'Frame 2', width: 1200, height: 1600, size: '13.3', orientation: 'auto' },
  { entry_id: 'entry_3', title: 'Frame 3', width: 1200, height: 1600, size: '13.3', orientation: 'auto' },
  { entry_id: 'entry_4', title: 'Frame 4', width: 1200, height: 1600, size: '13.3', orientation: 'auto' },
  { entry_id: 'entry_5', title: 'Frame 5', width: 1200, height: 1600, size: '13.3', orientation: 'auto' },
];
const DEFAULT_WALL = {
  wall_id: 'default', name: 'All Frames', kind: 'default',
  placements: {
    entry_tall: { x: 50, y: 50 },
    entry_2: { x: 300, y: 10 },
    entry_3: { x: 500, y: 10 },
    entry_4: { x: 700, y: 10 },
    entry_5: { x: 10, y: 400 },
  },
};

test.describe('Align Wall to Grid with a physically tall panel', () => {
  let mockServer;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({ frames: FRAMES, walls: [DEFAULT_WALL] });
    const baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await openScenesTab(page);
    await page.waitForFunction(
      () => document.getElementById('panel').shadowRoot.querySelectorAll('.wall-tile').length === 5
    );
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  test('the next row starts below the tall panel, not overlapping it', async ({ page }) => {
    await page.evaluate(() => {
      document.getElementById('panel').shadowRoot.getElementById('wall-grid-align-btn').click();
    });

    const dimsById = await page.evaluate(() => {
      const panel = document.getElementById('panel');
      const out = {};
      for (const frame of panel._frames) {
        out[frame.entryId] = panel._wallTileDims(frame);
      }
      return out;
    });

    const tiles = await getWallTiles(page);
    const byId = Object.fromEntries(tiles.map((t) => [t.entryId, { x: parseFloat(t.left), y: parseFloat(t.top) }]));

    // The 31.5" tile must actually render taller than the old fixed 160px
    // row height, or this test wouldn't exercise the bug at all.
    expect(dimsById.entry_tall.height).toBeGreaterThan(160);

    // Row 1's sole occupant (entry_5) must start at/after the tall tile's
    // real bottom edge -- strict AABB non-overlap on the y-axis.
    expect(byId.entry_5.y).toBeGreaterThanOrEqual(byId.entry_tall.y + dimsById.entry_tall.height);
    const ids = Object.keys(byId);
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = { ...byId[ids[i]], ...dimsById[ids[i]] };
        const b = { ...byId[ids[j]], ...dimsById[ids[j]] };
        const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
        expect(overlap).toBe(false);
      }
    }
  });
});
