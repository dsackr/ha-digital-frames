# Test ledger

Append-only, durable record of test-suite runs against `main`. CI appends
one row per suite per push (see the "Record result in the test ledger"
step in `.github/workflows/python-tests.yaml` and `panel-tests.yaml`);
rows are committed back to this file with `[skip ci]`, so recording never
triggers more CI. Failures are recorded too — a red row is the point of
having a ledger.

Notes on reading it:
- Both test workflows are path-filtered, so a push that touches neither
  the backend nor the frontend (docs, CI) legitimately has no row.
- `Coverage` is the backend suite's overall `custom_components.digital_frames`
  percentage; the Playwright suite doesn't measure coverage.
- Rows marked `local` were recorded by hand before CI recording existed
  (or for suites run outside CI); everything after 2026-07-12 should come
  from CI.

| Date (UTC) | Commit | Suite | Result | Detail | Coverage | Source |
|---|---|---|---|---|---|---|
| 2026-07-12 | 7f34f0e | backend-pytest | pass | 253 passed | 64% | CI + local |
| 2026-07-12 | 7f34f0e | panel-playwright | pass | 132 passed | — | CI + local |
| 2026-07-12 | 4489da6 | panel-playwright | pass | 133 passed | — | CI + local |
| 2026-07-13 | 9520461 | panel-playwright | success | 133 passed | — | CI |
| 2026-07-13 | 9520461 | backend-pytest | success | 253 passed in 66.99s (0:01:06) | 64% | CI |
| 2026-07-13 | 9520461 | smoke-hapi | pass | 8/8 KPF checks vs hapi.dalesackrider.com (v0.12.87, real 13.3" frame at .117; card fields verified live) | — | local |
| 2026-07-13 | 7b545ea | panel-playwright | success | 133 passed | — | CI |
| 2026-07-13 | 6d9040b | panel-playwright | success | 134 passed | — | CI |
| 2026-07-14 | a468e13 | backend-pytest | success | 258 passed in 67.22s (0:01:07) | 64% | CI |
| 2026-07-14 | b49a3ca | panel-playwright | success | 135 passed | — | CI |
| 2026-07-14 | ed47648 | backend-pytest | success | 258 passed in 67.06s (0:01:07) | 64% | CI |
| 2026-07-14 | 4c7dbb4 | panel-playwright | success | 136 passed | — | CI |
| 2026-07-14 | 4c7dbb4 | backend-pytest | success | 260 passed in 68.79s (0:01:08) | 64% | CI |
| 2026-07-17 | 08b8c29 | backend-pytest | success | 261 passed in 68.88s (0:01:08) | 64% | CI |
| 2026-07-17 | 2ffe2f0 | backend-pytest | success | 263 passed in 68.86s (0:01:08) | 64% | CI |
| 2026-07-17 | 7c13c1a | panel-playwright | success | 136 passed | — | CI |
| 2026-07-17 | 7c13c1a | backend-pytest | success | 266 passed in 67.31s (0:01:07) | 64% | CI |
| 2026-07-17 | 51fb400 | backend-pytest | success | 266 passed in 66.81s (0:01:06) | 64% | CI |
| 2026-07-18 | aea1257 | backend-pytest | success | 267 passed in 68.54s (0:01:08) | 64% | CI |
| 2026-07-18 | 057393b | backend-pytest | success | 267 passed in 68.07s (0:01:08) | 64% | CI |
| 2026-07-19 | ddef7f0 | backend-pytest | success | 282 passed in 47.52s | 64% | CI |
| 2026-07-19 | 71ceb67 | backend-pytest | success | 285 passed in 67.80s (0:01:07) | 64% | CI |
| 2026-07-19 | aa7f2e0 | backend-pytest | success | 292 passed in 67.46s (0:01:07) | 64% | CI |
| 2026-07-19 | d32cbda | panel-playwright | success | 136 passed | — | CI |
| 2026-07-19 | 14b227a | panel-playwright | success | 136 passed | — | CI |
| 2026-07-19 | 14b227a | backend-pytest | success | 295 passed in 72.67s (0:01:12) | 62% | CI |
| 2026-07-19 | 02a3799 | panel-playwright | success | 137 passed | — | CI |
| 2026-07-19 | 22c6011 | backend-pytest | success | 298 passed in 72.10s (0:01:12) | 62% | CI |
| 2026-07-19 | 65dd95f | backend-pytest | success | 302 passed in 70.97s (0:01:10) | 61% | CI |
| 2026-07-19 | 2836ca7 | backend-pytest | success | 308 passed in 57.51s | 62% | CI |
| 2026-07-19 | 59e5ef0 | backend-pytest | success | 309 passed in 48.15s | 62% | CI |
| 2026-07-19 | 50db356 | backend-pytest | success | 311 passed in 71.31s (0:01:11) | 62% | CI |
| 2026-07-19 | 5ffd32d | backend-pytest | failure | 3 failed, 311 passed in 71.86s (0:01:11) | 62% | CI |
| 2026-07-19 | 595c090 | panel-playwright | success | 137 passed | — | CI |
| 2026-07-19 | 595c090 | backend-pytest | failure | 3 failed, 313 passed in 73.64s (0:01:13) | 61% | CI |
| 2026-07-19 | 7fb9599 | backend-pytest | failure | 3 failed, 317 passed in 71.69s (0:01:11) | 62% | CI |
| 2026-07-19 | 8a6d09d | backend-pytest | success | 320 passed in 72.38s (0:01:12) | 62% | CI |
| 2026-07-19 | 5641d60 | backend-pytest | success | 326 passed in 70.75s (0:01:10) | 61% | CI |
| 2026-07-19 | cc4909d | panel-playwright | success | 137 passed | — | CI |
| 2026-07-19 | cc4909d | backend-pytest | success | 328 passed in 72.53s (0:01:12) | 61% | CI |
| 2026-07-19 | 2ac25ab | backend-pytest | success | 329 passed in 73.20s (0:01:13) | 62% | CI |
| 2026-07-19 | b85803b | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | b85803b | backend-pytest | success | 339 passed in 72.02s (0:01:12) | 62% | CI |
| 2026-07-19 | 0907f9d | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | 0907f9d | backend-pytest | success | 342 passed in 71.85s (0:01:11) | 62% | CI |
| 2026-07-19 | 5d49b3d | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | 5d49b3d | backend-pytest | success | 344 passed in 74.25s (0:01:14) | 62% | CI |
| 2026-07-19 | 3686ab2 | backend-pytest | success | 345 passed in 59.60s | 62% | CI |
| 2026-07-19 | 72ee985 | backend-pytest | success | 348 passed in 74.94s (0:01:14) | 62% | CI |
| 2026-07-19 | e2edd47 | panel-playwright | success | 141 passed | — | CI |
| 2026-07-19 | e2edd47 | backend-pytest | success | 348 passed in 72.98s (0:01:12) | 62% | CI |
| 2026-07-20 | b7aad44 | panel-playwright | success | 141 passed | — | CI |
| 2026-07-20 | b7aad44 | backend-pytest | success | 363 passed in 74.03s (0:01:14) | 63% | CI |
| 2026-07-20 | b3c9daf | panel-playwright | success | 141 passed | — | CI |
| 2026-07-20 | b3c9daf | backend-pytest | success | 366 passed in 77.58s (0:01:17) | 62% | CI |
| 2026-07-20 | 136d13e | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | 136d13e | backend-pytest | success | 366 passed in 74.00s (0:01:13) | 64% | CI |
| 2026-07-20 | 6318eb0 | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | 6318eb0 | backend-pytest | success | 369 passed in 75.60s (0:01:15) | 64% | CI |
| 2026-07-20 | 172e104 | backend-pytest | success | 370 passed in 77.45s (0:01:17) | 64% | CI |
| 2026-07-20 | 63948d0 | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | b97e382 | panel-playwright | success | 132 passed | — | CI |
| 2026-07-20 | 63948d0 | backend-pytest | success | 371 passed in 75.97s (0:01:15) | 64% | CI |
| 2026-07-21 | 4a58d08 | panel-playwright | success | 140 passed | — | CI |
| 2026-07-21 | 4a58d08 | backend-pytest | success | 403 passed in 78.05s (0:01:18) | 64% | CI |
| 2026-07-24 | b7ed014 | panel-playwright | success | 151 passed | — | CI |
| 2026-07-24 | b7ed014 | backend-pytest | success | 471 passed in 80.30s (0:01:20) | 66% | CI |
| 2026-07-25 | 6521e0a | panel-playwright | success | 151 passed | — | CI |
| 2026-07-25 | 6521e0a | backend-pytest | success | 472 passed in 81.86s (0:01:21) | 66% | CI |
| 2026-07-25 | e8d8a71 | panel-playwright | failure | 7 failed 150 passed | — | CI |
| 2026-07-25 | e8d8a71 | backend-pytest | success | 476 passed in 81.88s (0:01:21) | 66% | CI |
| 2026-07-25 | a75323d | panel-playwright | success | 157 passed | — | CI |
| 2026-07-26 | 5790bea | panel-playwright | success | 158 passed | — | CI |
| 2026-07-26 | 9a6417c | panel-playwright | success | 158 passed | — | CI |
| 2026-07-26 | 9a6417c | backend-pytest | success | 475 passed in 64.09s (0:01:04) | 66% | CI |
| 2026-07-26 | 56e89ab | panel-playwright | success | 158 passed | — | CI |
| 2026-07-26 | 56e89ab | backend-pytest | success | 475 passed in 83.31s (0:01:23) | 66% | CI |
| 2026-07-27 | b464fc4 | panel-playwright | failure | 2 failed 156 passed | — | CI |
| 2026-07-27 | 60f6213 | panel-playwright | failure | 2 failed 156 passed | — | CI |
| 2026-07-27 | 60f6213 | backend-pytest | success | 475 passed in 82.47s (0:01:22) | 66% | CI |
| 2026-07-28 | 19f86b4 | panel-playwright | failure | 2 failed 156 passed | — | CI |
| 2026-07-28 | 19f86b4 | backend-pytest | success | 475 passed in 85.21s (0:01:25) | 66% | CI |
| 2026-07-28 | a00f183 | backend-pytest | failure | 476 passed, 29 errors in 85.44s (0:01:25) | 66% | CI |
| 2026-07-28 | 28123b7 | backend-pytest | failure | 476 passed, 29 errors in 66.22s (0:01:06) | 66% | CI |
| 2026-07-28 | 0a40eac | backend-pytest | failure | 1 failed, 479 passed, 29 errors in 88.24s (0:01:28) | 66% | CI |
| 2026-07-28 | e995822 | backend-pytest | failure | 1 failed, 479 passed, 29 errors in 87.85s (0:01:27) | 66% | CI |
| 2026-07-28 | 47ffe3b | backend-pytest | failure | 1 failed, 479 passed, 29 errors in 87.27s (0:01:27) | 66% | CI |
| 2026-07-28 | d4b4c46 | panel-playwright | failure | 2 failed 156 passed | — | CI |
| 2026-07-28 | d4b4c46 | backend-pytest | success | 488 passed in 85.62s (0:01:25) | 64% | CI |
| 2026-07-28 | 917e26b | panel-playwright | failure | 2 failed 156 passed | — | CI |
| 2026-07-28 | 60c587f | backend-pytest | success | 489 passed in 81.84s (0:01:21) | 65% | CI |
| 2026-07-28 | a746068 | panel-playwright | failure | 2 failed 156 passed | — | CI |
| 2026-07-28 | 4ee8d77 | backend-pytest | success | 495 passed in 82.80s (0:01:22) | 66% | CI |
| 2026-07-28 | 8f6ac18 | panel-playwright | failure | 2 failed 157 passed | — | CI |
| 2026-07-28 | 8f6ac18 | backend-pytest | success | 498 passed in 68.11s (0:01:08) | 66% | CI |
| 2026-07-28 | 3d68b69 | backend-pytest | success | 499 passed in 78.27s (0:01:18) | 66% | CI |
| 2026-07-28 | 2ee40b0 | panel-playwright | failure | 2 failed 159 passed | — | CI |
| 2026-07-28 | 2ee40b0 | backend-pytest | success | 503 passed in 84.36s (0:01:24) | 66% | CI |
| 2026-07-29 | df139a4 | panel-playwright | failure | 2 failed 160 passed | — | CI |
| 2026-07-29 | df139a4 | backend-pytest | success | 504 passed in 82.40s (0:01:22) | 66% | CI |
| 2026-07-29 | 02a7cbd | panel-playwright | failure | 2 failed 163 passed | — | CI |
| 2026-07-29 | 02a7cbd | backend-pytest | success | 508 passed in 85.62s (0:01:25) | 66% | CI |
| 2026-07-29 | 22c732f | backend-pytest | success | 508 passed in 86.63s (0:01:26) | 66% | CI |
| 2026-07-29 | 0b8ea5b | backend-pytest | success | 508 passed in 85.81s (0:01:25) | 66% | CI |
| 2026-07-29 | d22821a | backend-pytest | success | 508 passed in 84.20s (0:01:24) | 66% | CI |
| 2026-07-29 | 38940d1 | panel-playwright | failure | 2 failed 163 passed | — | CI |
| 2026-07-29 | 38940d1 | backend-pytest | success | 517 passed in 84.32s (0:01:24) | 67% | CI |
| 2026-07-30 | 994e1a0 | panel-playwright | failure | 2 failed 165 passed | — | CI |
| 2026-07-30 | 994e1a0 | backend-pytest | success | 517 passed in 87.10s (0:01:27) | 67% | CI |
| 2026-07-30 | 8faffb1 | backend-pytest | failure | 518 passed, 2 errors in 88.63s (0:01:28) | 67% | CI |
| 2026-07-30 | 6d44f47 | panel-playwright | failure | 2 failed 165 passed | — | CI |
| 2026-07-30 | 6d44f47 | backend-pytest | failure | 518 passed, 2 errors in 88.36s (0:01:28) | 67% | CI |
| 2026-07-30 | dce693c | panel-playwright | failure | 2 failed 165 passed | — | CI |
| 2026-07-30 | dce693c | backend-pytest | failure | 520 passed, 2 errors in 88.08s (0:01:28) | 67% | CI |
| 2026-07-30 | 2a4904e | panel-playwright | failure | 2 failed 165 passed | — | CI |
| 2026-07-30 | 2a4904e | backend-pytest | failure | 521 passed, 2 errors in 87.24s (0:01:27) | 67% | CI |
| 2026-07-30 | fb65c98 | panel-playwright | failure | 2 failed 166 passed | — | CI |
| 2026-07-30 | fb65c98 | backend-pytest | failure | 522 passed, 2 errors in 86.65s (0:01:26) | 67% | CI |
| 2026-07-30 | 9679ec5 | backend-pytest | failure | 1 failed, 523 passed, 2 errors in 97.67s (0:01:37) | 67% | CI |
| 2026-07-30 | 24367e1 | backend-pytest | failure | 1 failed, 526 passed, 2 errors in 3660.68s (1:01:00) | 67% | CI |
| 2026-07-30 | 825cb1d | backend-pytest | failure | 1 failed, 527 passed, 2 errors in 1373.27s (0:22:53) | 67% | CI |
| 2026-07-30 | 83c905d | backend-pytest | failure | 2 failed, 527 passed, 2 errors in 1767.16s (0:29:27) | 67% | CI |
| 2026-07-30 | 6d17f95 | backend-pytest | failure | 2 failed, 531 passed, 3 errors in 1810.38s (0:30:10) | 67% | CI |
| 2026-07-30 | 185c654 | backend-pytest | failure | 527 passed, 3 errors in 90.04s (0:01:30) | 67% | CI |
| 2026-08-01 | 5b7b1da | panel-playwright | failure | 2 failed 170 passed | — | CI |
| 2026-08-01 | 5b7b1da | backend-pytest | failure | 532 passed, 3 errors in 90.45s (0:01:30) | 67% | CI |
| 2026-08-03 | 8b8e873 | panel-playwright | success | 172 passed | — | CI |
| 2026-08-03 | 8b8e873 | backend-pytest | failure | 532 passed, 1 error in 88.59s (0:01:28) | 67% | CI |
| 2026-08-03 | 964d47e | panel-playwright | success | 172 passed | — | CI |
| 2026-08-03 | 964d47e | backend-pytest | failure | 539 passed, 1 error in 88.98s (0:01:28) | 63% | CI |
| 2026-08-03 | f0d04c1 | panel-playwright | success | 172 passed | — | CI |
| 2026-08-03 | f0d04c1 | backend-pytest | failure | 539 passed, 1 error in 79.64s (0:01:19) | 63% | CI |
| 2026-08-04 | b545745 | backend-pytest | failure | 541 passed, 1 error in 92.03s (0:01:32) | 63% | CI |
| 2026-08-04 | f1d6328 | backend-pytest | failure | 542 passed, 1 error in 95.41s (0:01:35) | 63% | CI |
| 2026-08-04 | eb5ca32 | backend-pytest | failure | 543 passed, 1 error in 93.28s (0:01:33) | 63% | CI |
| 2026-08-04 | e86c10d | backend-pytest | failure | 543 passed, 1 error in 92.81s (0:01:32) | 63% | CI |
