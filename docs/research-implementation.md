# Research implementation and evidence

The supplied SolarFit report is a design brief. Its suggested deadlines and
external actions are not runtime requirements. The deterministic core is retained.

| Report recommendation | Implementation / evidence |
|---|---|
| Official faces, orthonormal surface metres, robust DSM fit | `map_service`, `roof_plane`, `elevation_service`; synthetic and live placement checks |
| Adaptive residual threshold and diagnostics | Existing seeded lower-deck fit, MAD-based noise multiplier, 0.28 m minimum; retained pending labelled regression evidence instead of arbitrarily raising the floor |
| Narrow PV computer vision; height obstacles and visual rooflights | Existing YOLO PV checkpoint, elevation residuals, image heuristic; manual PV/obstacle correction |
| Official versus additional potential | Results card distinguishes roof area/source yield from fitted modules; exclusive area accounting |
| Configurable energy assumptions | Performance ratio and explicit yield override; zero irradiation gives zero yield; no second annual shade multiplier |
| Registry/EGID and temporal corroboration | PV-register service, acquisition dates, mismatch findings, per-input confidence |
| Conditional planning rules | User-marked RWA with 2 m advisory clearance in all modes, including neighbouring-face effects; installer margins and unassessed requirements shown separately |
| Local shadow demonstration | Date/month and half-hour UTC controls in the roof editor; cached directional horizons; purple shade and grey unknown coverage; original surveyed geometry only |
| Repeatable benchmark and cache preparation | `python -m scripts.benchmark_roofs`; three fixed coordinates, geometry assertions, first-pass/warm timings, saved image/result/shadow snapshots |
| PV IoU, F1 and recall | `python -m training.evaluate_pixels`; 172 held-out tiles, source-group overlap audit, checkpoint hash, measured pixel metrics |
| Local deployment and optional CPU container | Existing launcher/ngrok flow; new Dockerfile and Compose with persistent DSM cache and mounted weights |
| Demo preparation | Runbook below; bundled offline examples already available |

## Measured on 9 September 2026

131 automated backend tests and the frontend HTTP error-handling regression test
passed. Production TypeScript/Vite build passed. Three live
Swiss roof cases passed deterministic-repeat, module-area, containment and
non-overlap assertions; 929 proposed panels were checked. Their new shadow
responses also completed, including Bern's complex multi-face geometry.
Fresh-process HTTP checks passed for health, the built frontend, the shadow
route and expired-capture handling.

Follow-up runtime verification used the actual server on port 8000: all 16
automatic/drawn roof cases across eight Swiss cities passed preparation and
surface analysis, and 45 shadow requests across three roofs passed. A terrain
exclusion with missing residual heights previously emitted NaN and caused JSON
serialization to fail; missing height is now explicitly null. The launcher and
health response identify outdated backend code, and frontend API calls handle
plain-text/HTML failures without exposing JSON parser errors. After a backend
restart, reload the page and select the roof again to replace expired captures.

| Case | Additional modules | Empty-roof grid baseline | Warm range, seconds |
|---|---:|---:|---:|
| Zurich | 834 | 1692 | 0.92–1.08 |
| Bern | 44 | 243 | 0.28–0.30 |
| Brugg | 51 | 68 | 0.06–0.10 |

Warm end-to-end in-process p50 was 0.29 s and p95 1.06 s (nine samples).
First-pass p50 was 2.09 s and p95 6.90 s (three samples, existing disk caches
retained, model warmup included). These are local observations, not cold-download
or production latency promises. See [raw benchmark](../models/roof-benchmark.json).
The empty-roof baseline uses the same module and edge settings but ignores
occupancy and screening; its difference is planning impact, not an accuracy score.

PV micro pixel IoU **0.560**, F1 **0.718**, precision **0.615**, recall **0.861** at
640 px / 0.25 confidence. See [raw evaluation](../models/pixel-evaluation.json).
Evaluation uses converted polygon masks: holes and tiny components lost in
conversion are not recovered. Kilometre groups are disjoint, but adjacent groups
can cross splits. Negative tiles were subsampled. These limitations apply to all
reported pixel metrics.

## Remaining empirical and operational work

- A manually reviewed 17-roof failure-mode set and obstacle footprint labels
  have not been supplied. No obstacle precision/recall, survey-level geometry
  accuracy or capacity accuracy is claimed from the automated smoke cases.
- A stricter spatial holdout with a geographic buffer requires a newly defined
  split and model retraining; existing test groups are disjoint, not necessarily distant.
- Container configuration validates, but image build/start remains unverified:
  Docker Desktop's Linux engine was not running during implementation.
- Browser interaction and visual inspection remain unverified because no browser
  was exposed to the computer-use tool in this session.
- No public deployment, national dataset download or new model training was
  performed. Point-cloud diagnostics and hourly weather-based energy remain
  future extensions, as the report recommends for work beyond the MVP.
- Site-specific legal, structural and fire-envelope certification requires
  information beyond aerial imagery and is explicitly unassessed in the app.

## Five-minute demonstration

1. Start `START_SOLARFIT.bat`. Select Brugg at 47.48139895, 8.20664208.
2. Explain official geometry, measured height obstacles and image-detected PV.
3. Open the official/additional comparison and provenance. Show actual module
   dimensions and performance ratio, then change the module and recalculate.
4. Open the editor's **Explore local shadows** control. Compare June and December
   and move the UTC time slider. Explain that this leaves annual energy unchanged.
5. Mark one missed rooflight or confirmed RWA, recompute, and show the resulting
   exclusion. RWA is a user confirmation of opening type, not a model guess.
6. Show Bern at 46.95239282, 7.42833943 for existing PV and many-face geometry.
7. Close with: official geodata defines the roof, geometry places modules, and
   computer vision locates existing PV that the records cannot localise.

Before presenting, visit demo roofs in the running app to warm its process caches.
The benchmark warms disk tiles, but its process-local captures expire when it
exits. It writes `.cache/benchmark/{case}.jpg`, result JSON and shadow JSON for
offline inspection. Bundled image examples support a demo without map services.
After restarting the backend, select buildings again: old capture IDs are
process-local and intentionally expire.

For the optional CPU container, start Docker Desktop then run `docker compose up
--build -d`. Open http://127.0.0.1:8000. Weights are mounted from `models/`, and a
named volume retains the DSM cache. Use a single worker because captures live in
process memory. The existing local/ngrok launcher remains the verified runtime;
starting a public tunnel is a separate operational action.
