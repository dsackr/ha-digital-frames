#!/usr/bin/env node
// PROTOTYPE LAUNCHER — THROWAWAY CODE
// Starts the Digital Frames panel mock server on http://localhost:4173/?variant=A
// so you can flip between UI Variants A, B, and C in your browser.

const { createMockServer } = require('./fixtures/mock-server');

const PORT = Number(process.env.PORT || 4173);

async function main() {
  const srv = createMockServer({
    frames: [
      { entry_id: 'entry_living_main', title: 'Living Room 13.3"', width: 1600, height: 1200, size: '13.3"', orientation: 'landscape' },
      { entry_id: 'entry_living_side', title: 'Reading Nook 7.3"', width: 480, height: 800, size: '7.3"', orientation: 'portrait' },
      { entry_id: 'entry_kitchen', title: 'Kitchen Counter 10.3"', width: 1872, height: 1404, size: '10.3"', orientation: 'landscape' },
      { entry_id: 'entry_study_meural', title: 'Study Meural 27"', width: 1920, height: 1080, size: 'meural', driver: 'meural', send_entity: 'ip', orientation: 'landscape' },
    ],
    onboardingComplete: true,
  });

  const baseUrl = await srv.start(PORT);
  console.log('\n=============================================================');
  console.log(' Digital Frames UI Prototype Running!');
  console.log('=============================================================');
  console.log(`  Variant A (Mobile App Shell & Frame Deck):     ${baseUrl}/?variant=A`);
  console.log(`  Variant B (Spatial Wall Stage & Drawer):       ${baseUrl}/?variant=B`);
  console.log(`  Variant C (Channel Stream & Broadcast Ribbon): ${baseUrl}/?variant=C`);
  console.log('\n  Use ← and → arrow keys or the bottom bar to switch variants.');
  console.log('  Press Ctrl+C to stop.');
  console.log('=============================================================\n');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
