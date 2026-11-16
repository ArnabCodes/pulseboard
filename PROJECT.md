# Project: PulseApp UI & Performance Architecture (v24 Zero-Jank Optical Glass + Editorial Surface System)

## Architecture
PulseApp is a client-side progressive web application delivering daily briefings, secular teachings, quantum spin simulation, academic preprints, career/postdoc trackers, and focus workflows.
- **Frontend Core**: Single-page architecture in `index.html` with Tailwind Play CDN (`darkMode: 'class'`), inline `<style>` design tokens, and a single inline `<script>` block.
- **v24 Optical Glass + Editorial Surface System**:
  - **Floating Chrome Only** (`.lg-bar-shell`, `#cmd-palette-modal`, `#page-layer` `md+`, `.pb-toast`, `.pin-key`, `.gate-sensor-btn`, `.lg-media-badge`): isolated onto GPU compositor layers (`isolation: isolate; transform: translateZ(0)`) with single-layer `backdrop-filter` and pure CSS `mask-composite: exclude` (`-webkit-mask-composite: xor`) specular prism rims (`.lg-bar-shell::before`).
  - **60fps Architectural Scrolling Cards & Controls** (`.lg-card`, `.lg-subcard`, `.lg-pill`, `.lg-pill-active`, `.lg-input`, `.lg-sliding-nav`, `.lg-sliding-thumb`, `.lg-switch`, `.lg-range-thumb`): clean elevated solid/tinted surfaces with **zero** nested `backdrop-filter` blur, zero `html2canvas`/`liquidGL.js` WebGL loops, zero SVG `<feDisplacementMap>` filters, zero animated canvas/CSS blur orbs, and zero `pointermove` layout reads.
  - **Typography & Theme Sync**: SF Pro UI (`Inter` fallback), editorial `Newsreader` serif leads/headlines (`.font-serif-editorial`), and tabular `JetBrains Mono` (`font-mono-tabular`); Day/Night editions toggle `document.documentElement.classList.toggle('dark', isNight)` in sync with `body.bg-slate-950`.
- **Streamlined Workspaces & Interactions**:
  - Single-row floating capsule header (`Today`, `Research`, `Vault`, `Plan`, `Mindful`), matching mobile bottom capsule dock, and safe-area-cleared floating controls (`bottom: calc(84px + env(safe-area-inset-bottom))`).
  - Editorial masthead with horizontal synthesis strip and collapsible mobile weather forecast (`#btn-weather-expand`).
  - Magazine-grade news cards (`.lg-media-badge`, circular saves, unread dot, serif lead) + `← Previous` / `Next →` pagination in Story Reader (`#story-prev-btn`, `#story-next-btn`).
  - Sticky right inspector defaulting to `Focus` (`pbInspectorMode = 'focus'`) with live counts (`pbUpdateInspectorCounts()`), expanding to a 3-column Bento layout in `Plan` (`rituals`) and centered sanctuary in `Mindful` (`stillness`).
  - Banner-free arXiv preprint cards with `⚛ Simulate` presets driving the Retina DPR Bloch sphere canvas (`#bloch-canvas`) with HTML superscript readout and hidden-tab interval guard.
  - Instant `⌘K` Spotlight live content search (`#cmd-live-results`) across stories, preprints, career/postdoc boards, and tasks alongside workspace commands.
- **Service Worker & PWA**: Offline caching, runtime image caching, and stale-while-revalidate strategies in `sw.js` (`CACHE_NAME = 'pulseboard-v24'`).
- **Quality Gates**: `tests/` validating static constraints (single `<script>`, 0 duplicate functions, matching `getElementById` IDs), platform headers/CSP/manifest/SW versioning, data file schemas, feed integrity (`validate_feed.py`), and v24 CSS/JS invariants (`test_liquidgl_specular.py`).

## Interface Contracts
- **Canonical Element IDs**: `#hero-banner`, `#wisdom-card`, `#quantum-lab-card`, `#routine-card`, `#schedule-card`, `#tasks-card`, `#deck-left-col`, `#deck-right-aside`, `#inspector-mode-bar`, `#cmd-live-results`, `#btn-weather-expand`, `#story-prev-btn`, `#story-next-btn`, `#apple-wallpaper`.
- **Compositor Invariants**: `#apple-wallpaper` stays behind content (`z-index: -1; pointer-events: none;`) with static radial gradients; only floating chrome uses `backdrop-filter`; scrolling `.lg-card`/`.lg-subcard`/`.lg-pill`/`.lg-input` rules never declare `backdrop-filter`.
- **Plan/Mindful Layout Switching**: `pbApplyCurrentDeck()` resets layout classes cleanly on `#deck-left-col`, `#deck-right-aside`, `#inspector-mode-bar`, and `#wisdom-card` across workspace switches without clobbering `pbInspectorMode`.

## Code Layout
- `/Users/arnabacharya/Documents/PulseApp/index.html`: Core PWA UI, v24 `<style>` sheet, and single inline `<script>`.
- `/Users/arnabacharya/Documents/PulseApp/sw.js`: Service worker managing PWA offline cache (`pulseboard-v24`).
- `/Users/arnabacharya/Documents/PulseApp/tests/`: Automated pytest and feed validation suites.
