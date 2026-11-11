# Project: PulseApp Visual Overhaul (SwiftUI & Liquid Glass)

## Architecture
PulseApp is a client-side progressive web application delivering daily briefings, secular teachings, quantum laboratory simulations, academic preprints, and productivity trackers.
- **Frontend Core**: Single-page architecture in `index.html` with Tailwind CSS CDN, inline `<style>` Apple HIG design tokens, and a single inline `<script>` block.
- **Visual Design Language**: Apple / macOS design system, SF Pro typography hierarchy (`--font-sf-display`, `--font-sf-text`, `--font-sf-rounded`, `--font-sf-mono`), and Liquid Glass (`.lg-card`, `.lg-subcard`, `.lg-bar-shell`, `.lg-pill`, `.lg-input`, `.liquidgl-lens`, specular radial glints `--lg-mx`/`--lg-my`).
- **Dynamic Renderers**: JavaScript rendering engine updating dynamic content cards and managing Morning and Night editions.
- **Service Worker & PWA**: Offline caching, runtime image caching, and stale-while-revalidate strategies in `sw.js`.
- **Quality Gates**: `tests/` validating static constraints (single `<script>`, 0 duplicate functions, 273 matching IDs), platform headers, service worker cache versioning, and feed invariants.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Stray Markup & Duplicate Bar Removal | Delete rogue `</div>` (line 10180) and redundant `#mobile-deck-bar` (lines 10183-10205) after `</script>`. | M1 | Survey 1, Survey 2 |
| 2 | CSS Token & Style Harmonization | Add daylight Spotlight frosted glass CSS, iOS safe area inset padding for `#mobile-deck-bar`, and specular glint defaults. | M1 | Survey 1 |
| 3 | Static Main Cards Liquid Glass Overhaul | Upgrade `#hero-banner`, `#weather-card`, `#thisday-card`, `#wisdom-card`, `#quantum-lab-card`, `#routine-card`, `#schedule-card`, `#tasks-card` to `.lg-card`, `.lg-subcard`, `.liquidgl-lens`, `.lg-pill`. | M1 | Survey 1 |
| 4 | Section Controls & Boards Overhaul | Upgrade `#category-filters`, `#career-board-section`, `#postdoc-board-section`, search inputs, and filter chips to `.lg-pill`, `.lg-input`, `.lg-subcard`. | M1 | Survey 1 |
| 5 | Overlay & Slide-Over Pages Overhaul | Upgrade `#page-story`, `#page-settings`, `#page-teaching`, `#page-dayclose`, `#page-search`, `#page-focus`, `#page-week` to Liquid Glass cards, Apple capsule headers, and `.lg-pill` buttons. | M1 | Survey 1 |
| 6 | Spotlight Command Palette Frosted Glass | Upgrade `#cmd-palette-backdrop` and `#cmd-palette-modal` with daylight frosted glass, Apple squircle radius, and SF Pro typography. | M1 | Survey 1 |
| 7 | Mobile Bottom Tab Bar Liquid Glass | Upgrade primary `#mobile-deck-bar` with `.lg-bar-shell`, Apple active tint, and safe-area insets. | M1 | Survey 1 |
| 8 | Central App & Theme Dynamic Rendering | Update `renderApp()` to emit `.lg-card` and Apple typography without overriding glass tokens on Morning and Night edition switches. | M2 | Survey 2 |
| 9 | Content Cards Dynamic Renderers | Update `renderWisdom`, `renderRoutine`, `renderVault`, `renderNewsGrid`, `renderPapers`, `renderSchedule`, `renderTasks`, `renderStoryPage` to emit `.lg-card`, `.lg-subcard`, `.lg-pill`, `.lg-pill-active`. | M2 | Survey 2 |
| 10 | Board & Intelligence Dynamic Renderers | Update `renderSmartRadar`, `renderSmartDossiersSummary`, `renderWorkspaceLens`, `renderDeadlines`, `renderCareerBoard`, `renderPostdocBoard` to emit `.lg-card`, `.lg-subcard`, `.lg-input`, `.lg-pill`. | M2 | Survey 2 |
| 11 | Telemetry & Navigation Renderers | Update `updatePinDots`, `renderBloch`, `pbRenderSettings`, `pbApplyCurrentDeck` to use Apple SF Pro/SF Mono styling and clean single mobile bar targeting. | M2 | Survey 2 |
| 12 | LiquidGL WebGL Optical Lens Initialization | Add `pbInitLiquidGL()` wrapping `window.liquidGL({...})` targeting `.liquidgl-lens` with `#apple-wallpaper` snapshot, fallback handling, and theme snapshot capture. | M2 | Survey 2 |
| 13 | Pointer-Tracked Specular Highlights | Implement non-blocking, passive `pointermove` listener updating `--lg-mx` and `--lg-my` with `requestAnimationFrame` debouncing. | M2 | Survey 2 |
| 14 | Comprehensive E2E Verification Suite | Add automated tests verifying R1, R2, markup validity, single script, zero duplicate functions, LiquidGL initialization, and CSS token coverage. | M3 / E2E | Survey 3 |
| 15 | Service Worker Cache Bump | Bump `CACHE_NAME = 'pulseboard-v21'` in `sw.js`. | M3 | Survey 3 |
| 16 | Git Rebase & Clean Production Deployment | Fetch and rebase against `origin/main` (incorporating bot commits `5d0b6a1`), stage clean files, commit, and push to GitHub `origin main`. | M3 | Survey 3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Static Markup & CSS Foundation Overhaul | Features 1, 2, 3, 4, 5, 6, 7 (index.html static HTML & CSS) | none | DONE |
| M2 | Dynamic Renderers, LiquidGL & Specular Wiring | Features 8, 9, 10, 11, 12, 13 (index.html JavaScript) | M1 | DONE |
| M3 | E2E Tests, Service Worker, Rebase & Deployment | Features 14, 15, 16 (tests/, sw.js, git deployment) | M2 | DONE |

## Interface Contracts
### HTML Markup ↔ Dynamic Renderers
- All content cards retain their canonical IDs (`#hero-banner`, `#wisdom-card`, `#quantum-lab-card`, `#routine-card`, `#schedule-card`, `#tasks-card`, etc.) so `document.getElementById` references in `test_static.py` and JavaScript remain 100% valid.
- Cards adopt CSS class `.lg-card` and `.card-hover`.
- Primary cards contain `<div class="liquidgl-lens" aria-hidden="true"></div>` for WebGL optical refraction.
- Dynamic renderers in JS must preserve `.lg-card` and `.lg-subcard` classes during re-rendering rather than overwriting with flat Tailwind stone/slate colors.
- CSS variables `--lg-card-bg`, `--lg-card-border`, `--lg-card-shadow`, `--lg-subcard-bg`, and `--apple-tint` automatically handle day/night styling based on `body.bg-slate-950`.

### LiquidGL WebGL ↔ Pointer Tracking
- `window.liquidGL` targets `.liquidgl-lens` elements. Canvas uses `pointer-events: none; z-index: 0;`.
- Specular highlights use pseudo-elements (`.lg-bar-shell::after`, `.lg-card::before`) with `pointer-events: none; z-index: 1;`.
- Card interactive children are positioned at `z-index: 2` ensuring clicks/taps are never intercepted.
- Pointer tracking uses passive `pointermove` with `requestAnimationFrame` debouncing, updating CSS custom properties `--lg-mx` and `--lg-my` on hovered cards.

## Code Layout
- `/Users/arnabacharya/Documents/PulseApp/index.html`: Core PWA UI, Apple HIG `<style>` sheet, and single `<script>` block.
- `/Users/arnabacharya/Documents/PulseApp/sw.js`: Service worker managing PWA offline capabilities and cache versioning.
- `/Users/arnabacharya/Documents/PulseApp/tests/`: Automated pytest verification suite.
