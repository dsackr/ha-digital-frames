// Image library sort order (KPF 8 extension): the My Gallery grid defaults
// to last-uploaded-first, and the #lib-sort-select dropdown lets a user
// switch to oldest-first or alphabetical (A-Z / Z-A).

const { test, expect } = require('@playwright/test');
const { createMockServer } = require('./fixtures/mock-server');
const { gotoPanel } = require('./fixtures/panel-page');

const FRAMES = [
  { entry_id: 'entry_1', title: 'Living Room Frame', width: 1200, height: 1600, orientation: 'auto' },
];

// uploaded_at values deliberately out of manifest order, so a passing test
// proves the grid is genuinely re-sorted and not just echoing array order.
const IMAGES = [
  { image_id: 'image_b', filename: 'bravo.png', albums: [], uploaded_at: 200 },
  { image_id: 'image_a', filename: 'alpha.png', albums: [], uploaded_at: 300 },
  { image_id: 'image_c', filename: 'charlie.png', albums: [], uploaded_at: 100 },
];

test.describe('Image library sort', () => {
  let mockServer;
  let baseUrl;

  test.beforeEach(async ({ page }) => {
    mockServer = createMockServer({
      frames: FRAMES,
      images: IMAGES,
      scenes: [],
      albums: [{ name: 'Images', count: 3, cover_image_id: 'image_a' }],
    });
    baseUrl = await mockServer.start();
    await gotoPanel(page, baseUrl, { frames: FRAMES });
    await page.locator('#panel #library-open-btn').click();
    await page.locator('#panel .album-tile').filter({ hasText: 'Images' }).click();
    await expect(page.locator('#panel .lib-card')).toHaveCount(3);
  });

  test.afterEach(async () => {
    await mockServer.stop();
  });

  function cardNames(page) {
    return page.locator('#panel .lib-card .preview-name').allTextContents();
  }

  test('defaults to last uploaded first', async ({ page }) => {
    await expect(page.locator('#panel #lib-sort-select')).toHaveValue('uploaded_desc');
    expect(await cardNames(page)).toEqual(['alpha.png', 'bravo.png', 'charlie.png']);
  });

  test('switching to first uploaded first reorders the grid', async ({ page }) => {
    await page.locator('#panel #lib-sort-select').selectOption('uploaded_asc');
    await expect.poll(() => cardNames(page)).toEqual(['charlie.png', 'bravo.png', 'alpha.png']);
  });

  test('switching to name A-Z reorders the grid alphabetically', async ({ page }) => {
    await page.locator('#panel #lib-sort-select').selectOption('name_asc');
    await expect.poll(() => cardNames(page)).toEqual(['alpha.png', 'bravo.png', 'charlie.png']);
  });

  test('switching to name Z-A reorders the grid in reverse alphabetical order', async ({ page }) => {
    await page.locator('#panel #lib-sort-select').selectOption('name_desc');
    await expect.poll(() => cardNames(page)).toEqual(['charlie.png', 'bravo.png', 'alpha.png']);
  });
});
