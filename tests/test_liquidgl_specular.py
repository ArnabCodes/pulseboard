"""Automated verification suite for PulseBoard v24 zero-jank Liquid Glass & redesigned UX.

Validates:
1. Elimination of heavy WebGL / html2canvas / SVG feDisplacementMap / animated blur-orb bloat.
2. Floating chrome (.lg-bar-shell) isolated optical glass with mask-composite prism rim & safe stacking.
3. Zero backdrop-filter on scrolling cards, pills, inputs, switches, and sliders (60fps compositing).
4. Tailwind Play CDN darkMode: 'class' sync and absence of invalid v3 tokens or raw LaTeX delimiters.
5. Retina HiDPI Bloch canvas scaling, hidden-tab Floquet guard, spotlight live search, mobile forecast toggle,
   story prev/next controls, 3-column Plan Bento layout, centered Mindful mode, and interactive DOM safety.
"""

from html.parser import HTMLParser
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
JSC_PATH = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _DomNode:
    def __init__(self, name, attrs=None, parent=None):
        self.name = name
        self.attrs = dict(attrs or [])
        self.parent = parent
        self.children = []

    def get(self, key, default=None):
        if key == "class":
            raw = self.attrs.get("class")
            return raw.split() if raw else (default if default is not None else [])
        return self.attrs.get(key, default)

    def find(self, id=None):
        for n in self._walk():
            if id is not None and n.attrs.get("id") == id:
                return n
        return None

    def find_all(self, tags=None, recursive=True):
        tag_set = set(tags) if isinstance(tags, (list, tuple, set)) else ({tags} if tags else None)
        it = self._walk() if recursive else self.children
        return [n for n in it if tag_set is None or n.name in tag_set]

    def _walk(self):
        for ch in self.children:
            yield ch
            yield from ch._walk()


class _MiniDOMParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _DomNode("[document]")
        self._stack = [self.root]
        self._raw_tag = None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if self._raw_tag:
            return
        node = _DomNode(t, attrs, parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if t in ("script", "style"):
            self._raw_tag = t
        elif t not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        t = tag.lower()
        if self._raw_tag:
            return
        node = _DomNode(t, attrs, parent=self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        t = tag.lower()
        if self._raw_tag:
            if t == self._raw_tag:
                self._raw_tag = None
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].name == t:
                del self._stack[i:]
                break


def _parse_dom(html):
    p = _MiniDOMParser()
    p.feed(html)
    return p.root


def _read_html():
    return INDEX.read_text(encoding="utf-8")


def _extract_script(html):
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    assert m, "Inline <script> not found in index.html"
    return m.group(1)


def _extract_style(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "Inline <style> not found in index.html"
    return m.group(1)


def _run_jsc(js_code):
    node_bin = shutil.which("node")
    if node_bin:
        shim = "const print = (...args) => console.log(args.join(' '));\n"
        cmd = [node_bin, "-e", shim + js_code]
    elif os.path.exists(JSC_PATH):
        cmd = [JSC_PATH, "-e", js_code]
    else:
        pytest.skip("Neither node nor macOS JavaScriptCore (jsc) is available")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"JS execution failed (exit code {proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout.strip()


def test_zero_webgl_svg_bloat_and_removed_observers():
    """Verify legacy liquidGL, html2canvas, SVG displacement filters, blurred orbs, and pointer tracking are removed."""
    html = _read_html()
    for banned in (
        "liquidGL",
        "html2canvas",
        "liquidgl-lens",
        "pb-optical-svg",
        "<feDisplacementMap",
        "macos-wallpaper-canvas",
        "apple-mesh-orb",
        "gate-aurora-orb",
        "pbWireSpecularHighlights",
        "pbRefreshLiquidGL",
        "pbDrawMacWallpaper",
        "pbBuildDisplacementFilters",
    ):
        assert banned not in html, f"Removed scroll/GPU bloat token '{banned}' must not exist in index.html"

    script = _extract_script(html)
    assert "pointermove" not in script or "getBoundingClientRect" not in script.split("pointermove", 1)[1][:300], (
        "Removed per-frame pointermove getBoundingClientRect() loop must not return"
    )


def test_floating_chrome_isolated_optical_glass_and_prism_rim():
    """Verify .lg-bar-shell uses isolated GPU compositing, mask-composite prism rim, and reduced-motion fallbacks."""
    html = _read_html()
    style = _extract_style(html)

    m_bar = re.search(r"(?<!\.pb-dim )\.lg-bar-shell\s*\{([^}]+)\}", style)
    m_rim = re.search(r"\.lg-bar-shell::before\s*\{([^}]+)\}", style)
    m_children = re.search(r"\.lg-bar-shell\s*>\s*\*\s*\{([^}]+)\}", style)
    assert m_bar and m_rim and m_children, "Missing .lg-bar-shell / ::before / > * rules"

    bar_css = m_bar.group(1)
    rim_css = m_rim.group(1)
    children_css = m_children.group(1)

    assert "isolation: isolate" in bar_css
    assert "backdrop-filter:" in bar_css
    assert "pointer-events: none" in rim_css
    assert "z-index: 1" in rim_css
    assert ("mask-composite: exclude" in rim_css or "-webkit-mask-composite: xor" in rim_css)
    assert "z-index: 2" in children_css
    assert "position: relative" in children_css

    assert "prefers-reduced-transparency: reduce" in style
    assert "prefers-reduced-motion: reduce" in style


def test_scrolling_cards_and_controls_have_zero_backdrop_filter():
    """Verify scrolling content cards, subcards, pills, inputs, and range/switch controls omit backdrop-filter."""
    html = _read_html()
    style = _extract_style(html)

    # Strip @media reduced-transparency block before inspecting base rules
    base_style = style.split("@media (prefers-reduced-transparency", 1)[0]

    for selector in (
        r"\.lg-card",
        r"\.lg-subcard",
        r"\.lg-pill",
        r"\.lg-pill-active",
        r"\.lg-input",
        r"\.lg-sliding-nav",
        r"\.lg-sliding-thumb",
        r"\.lg-switch",
        r"\.lg-switch-thumb",
        r"\.lg-range-thumb",
        r"\.lg-range-bubble",
    ):
        matches = re.findall(rf"(?:^|\n)\s*{selector}\s*\{{([^}}]+)\}}", base_style)
        assert matches, f"Expected base CSS rule for {selector}"
        for body in matches:
            assert "backdrop-filter" not in body, (
                f"Scrolling card/control rule matching {selector} must NOT use backdrop-filter"
            )


def test_dark_mode_class_sync_and_clean_tailwind_tokens():
    """Verify Tailwind Play CDN uses darkMode: 'class', Day/Night toggles html.dark, and invalid tokens are gone."""
    html = _read_html()
    script = _extract_script(html)

    assert "darkMode: 'class'" in script or 'darkMode: "class"' in script, (
        "Tailwind Play CDN config must set darkMode: 'class'"
    )
    assert "document.documentElement.classList.toggle('dark', isNight)" in script, (
        "renderApp() must sync html.dark with Night edition"
    )

    invalid_tokens = re.findall(
        r"\b(?:p-4\.5|w-4\.5|h-4\.5|py-0\.2|max-h-84|(?:bg|text|border|ring|from|to|via)-[a-z0-9-]+/12)\b",
        html,
    )
    assert not invalid_tokens, f"Found invalid Tailwind utility classes: {invalid_tokens}"

    # Verify zero unrendered literal LaTeX formulas in quantum UI markup or Bloch readout
    soup = _parse_dom(html)
    qlab = soup.find(id="quantum-lab-card")
    assert qlab is not None
    raw_html_chunk = html[html.index('id="quantum-lab-card"'):html.index('id="papers-section"')]
    assert "$" not in raw_html_chunk, "Quantum Lab HTML must not contain raw unrendered $...$ LaTeX strings"
    assert "e^{iφ}" not in html, "Bloch state readout should render HTML superscript instead of literal e^{iφ}"


def test_bloch_retina_hidpi_and_hidden_tab_guard():
    """Verify Retina HiDPI scaling in renderBloch() and hidden-tab pause inside Floquet timer."""
    html = _read_html()
    script = _extract_script(html)
    assert "window.devicePixelRatio" in script
    assert "ctx.scale(dpr, dpr)" in script
    m_floq = re.search(r"floquetTimer\s*=\s*setInterval\(\(\)\s*=>\s*\{([\s\S]*?)\},\s*30\)", script)
    assert m_floq, "floquetTimer interval not found"
    assert "if (document.hidden) return;" in m_floq.group(1)


def test_v24_ui_elements_and_inspector_defaults():
    """Verify v24 UI IDs, single-row header labels, mobile safe clearance, and Focus-first default."""
    html = _read_html()
    soup = _parse_dom(html)
    script = _extract_script(html)
    style = _extract_style(html)

    for required_id in (
        "today-synthesis-strip",
        "btn-weather-expand",
        "cmd-live-results",
        "story-prev-btn",
        "story-next-btn",
        "deck-left-col",
        "deck-right-aside",
    ):
        assert soup.find(id=required_id) is not None, f"Missing v24 UI element #{required_id}"

    assert re.search(r"let pbInspectorMode\s*=\s*'focus'", script), (
        "pbInspectorMode must default to 'focus' so the sticky right sidebar never clips tall lists"
    )
    assert "calc(84px + env(safe-area-inset-bottom))" in style, (
        "Mobile bottom clearance rule must lift #btn-scroll-top/#offline-badge above #mobile-deck-bar"
    )


def test_inspector_counts_and_deck_bento_behavior():
    """Exercise pbApplyInspectorMode, pbUpdateInspectorCounts, and pbApplyCurrentDeck in Node/JSC."""
    html = _read_html()
    script = _extract_script(html)

    m_insp = re.search(r"function pbApplyInspectorMode\(mode\)\s*\{[\s\S]*?\n    \}", script)
    m_cnt = re.search(r"function pbUpdateInspectorCounts\(\)\s*\{[\s\S]*?\n    \}", script)
    m_deck = re.search(r"function pbApplyCurrentDeck\(shouldScroll = false\)\s*\{[\s\S]*?\n    \}", script)
    assert m_insp and m_cnt and m_deck, "Expected controller functions not found in index.html"

    code_blob = "\n".join([m_insp.group(0), m_cnt.group(0), m_deck.group(0)])
    js = f"""
    const makeClassList = (init) => {{
      const s = new Set(init || []);
      return {{
        add: (...c) => c.forEach(x => s.add(x)),
        remove: (...c) => c.forEach(x => s.delete(x)),
        toggle: (c, force) => force === undefined ? (s.has(c) ? (s.delete(c), false) : (s.add(c), true)) : (force ? (s.add(c), true) : (s.delete(c), false)),
        contains: (c) => s.has(c),
        toString: () => Array.from(s).join(' '),
      }};
    }};
    const makeEl = (attrs = {{}}) => {{
      const el = {{
        _attrs: {{ ...attrs }},
        _children: [],
        textContent: '',
        className: '',
        classList: makeClassList(),
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        setAttribute: (k, v) => {{ el._attrs[k] = String(v); }},
        appendChild: (c) => {{ el._children.push(c); return c; }},
        querySelectorAll: () => [],
      }};
      return el;
    }};

    const inspBtns = ['focus', 'habits', 'schedule', 'all'].map(k => makeEl({{ 'data-inspector-mode': k }}));
    const elements = {{
      'inspector-mode-bar': Object.assign(makeEl(), {{ querySelectorAll: () => inspBtns }}),
      'tasks-card': makeEl(),
      'routine-card': makeEl(),
      'schedule-card': makeEl(),
      'toolbar-view-title': makeEl(),
      'deck-nav-bar': makeEl(),
      'mobile-deck-bar': makeEl(),
      'hero-banner': makeEl(),
      'wisdom-card': makeEl(),
      'quantum-lab-card': makeEl(),
      'workspace-lens-bar': makeEl(),
      'vault-subnav-bar': makeEl(),
      'newsboard-section': makeEl(),
      'today-arxiv-spotlight': makeEl(),
      'backup-articles-section': makeEl(),
      'papers-section': makeEl(),
      'career-board-section': makeEl(),
      'postdoc-board-section': makeEl(),
      'smart-radar-strip': makeEl(),
      'smart-dossiers-summary': makeEl(),
      'deck-left-col': makeEl(),
      'deck-right-aside': makeEl(),
    }};
    globalThis.document = {{
      getElementById: (id) => elements[id] || null,
      querySelector: () => null,
      createElement: () => makeEl(),
      createTextNode: (t) => ({{ text: t }}),
    }};
    globalThis.window = {{ scrollTo: () => {{}} }};
    globalThis.state = {{
      edition: 'morning',
      tasks: [{{ id: 't1', done: false }}, {{ id: 't2', done: true }}],
      routines: {{ morning: [{{ id: 'r1', done: true }}, {{ id: 'r2', done: false }}] }},
      schedules: {{ morning: [{{ time: '09:00' }}, {{ time: '11:00' }}] }},
    }};
    let pbCurrentDeck = 'briefing';
    let pbInspectorMode = 'focus';
    let pbVaultSubtab = 'all';
    const pbSyncSlidingPill = () => {{}};
    const pbSyncAllSlidingPills = () => {{}};
    const pbApplyVaultSubtab = () => {{}};

    {code_blob}

    pbUpdateInspectorCounts();
    if (inspBtns[0]._children[1].textContent !== '1') throw new Error('Focus count expected 1');
    if (inspBtns[1]._children[1].textContent !== '1/2') throw new Error('Habits count expected 1/2');
    if (inspBtns[2]._children[1].textContent !== '2') throw new Error('Schedule count expected 2');

    pbCurrentDeck = 'rituals';
    pbApplyCurrentDeck(false);
    if (!elements['deck-right-aside'].className.includes('lg:grid-cols-3')) {{
      throw new Error('Plan view must apply 3-col Bento grid: ' + elements['deck-right-aside'].className);
    }}
    if (!elements['inspector-mode-bar'].classList.contains('hidden')) {{
      throw new Error('Plan view must hide inspector-mode-bar');
    }}

    pbCurrentDeck = 'stillness';
    pbApplyCurrentDeck(false);
    if (!elements['wisdom-card'].classList.contains('max-w-3xl')) {{
      throw new Error('Mindful view must center wisdom-card with max-w-3xl');
    }}
    if (elements['routine-card'].classList.contains('hidden')) {{
      throw new Error('Mindful view must keep routine-card visible');
    }}
    if (!elements['tasks-card'].classList.contains('hidden')) {{
      throw new Error('Mindful view must hide tasks-card');
    }}

    pbCurrentDeck = 'briefing';
    pbApplyCurrentDeck(false);
    if (!elements['deck-right-aside'].className.includes('lg:col-span-4')) {{
      throw new Error('Today briefing must restore lg:col-span-4 aside');
    }}
    print('OK');
    """
    assert _run_jsc(js) == "OK"


def test_all_interactive_elements_non_intercepted():
    """Verify that all clickable elements, inputs, buttons, and drawers remain interactive."""
    html = _read_html()
    soup = _parse_dom(html)

    interactive_tags = ["button", "a", "input", "select", "textarea"]
    elements = soup.find_all(interactive_tags)
    assert len(elements) >= 140, f"Expected at least 140 interactive elements, found {len(elements)}"

    for el in elements:
        curr = el
        while curr:
            cid = curr.get("id", "")
            assert cid != "apple-wallpaper", (
                f"Interactive element {el.name} (id={el.get('id')}) must not be inside #apple-wallpaper"
            )
            curr = curr.parent


def test_overlays_and_drawers_hidden_by_default():
    """Verify that modal layers and drawer pages are hidden by default to prevent click blocking."""
    html = _read_html()
    soup = _parse_dom(html)

    overlays = [
        "page-layer",
        "cmd-palette-backdrop",
        "page-story",
        "page-settings",
        "page-teaching",
        "page-dayclose",
        "page-search",
        "page-focus",
        "page-week",
    ]
    for oid in overlays:
        el = soup.find(id=oid)
        assert el is not None, f"Overlay element #{oid} not found"
        classes = el.get("class", [])
        assert "hidden" in classes, f"Overlay element #{oid} must have class 'hidden' by default. Classes: {classes}"


def test_wallpaper_pointer_events_none():
    """Verify #apple-wallpaper has pointer-events: none and negative z-index."""
    html = _read_html()
    style = _extract_style(html)
    m = re.search(r"#apple-wallpaper\s*\{([^}]+)\}", style)
    assert m, "CSS rule #apple-wallpaper not found"
    content = m.group(1)
    assert "pointer-events: none" in content
    assert re.search(r"\bz-index\s*:\s*-1\b", content)


def test_no_fake_macos_window_chrome():
    """Verify fake desktop OS window traffic lights and desktop sidebar chrome are removed."""
    html = _read_html()
    soup = _parse_dom(html)
    for banned_id in (
        "macos-sidebar",
        "btn-traffic-close",
        "btn-traffic-min",
        "btn-traffic-zoom",
    ):
        assert soup.find(id=banned_id) is None, f"Fake OS chrome #{banned_id} should not exist in webapp"
    assert soup.find(id="webapp-shell") is not None


def test_liquid_glass_tabs_toggles_and_quantum_sliders():
    """Verify sliding droplet tabs, swelling switches, Quantum drag bars, and redesigned UX elements."""
    html = _read_html()
    soup = _parse_dom(html)

    for nav_id in ("deck-nav-bar", "edition-switcher", "category-filters", "inspector-mode-bar", "mobile-deck-bar"):
        nav = soup.find(id=nav_id)
        assert nav is not None, f"Missing sliding nav #{nav_id}"
        assert "has-sliding-thumb" in nav.get("class", []), f"#{nav_id} must include has-sliding-thumb"

    for sw_id in ("btn-unread-first", "bloch-vec-toggle", "set-notifications", "set-haptics"):
        sw = soup.find(id=sw_id)
        assert sw is not None, f"Missing switch #{sw_id}"
        assert "lg-switch" in sw.get("class", []), f"#{sw_id} must use .lg-switch"

    for slider_id in ("bloch-rabi-slider", "bloch-detuning-slider", "bloch-gamma-slider"):
        sl = soup.find(id=slider_id)
        assert sl is not None, f"Missing Quantum slider #{slider_id}"
        assert "lg-range-native" in sl.get("class", []), f"#{slider_id} must use .lg-range-native"
        assert sl.parent is not None and "lg-range-wrap" in sl.parent.get("class", []), (
            f"#{slider_id} must be wrapped in .lg-range-wrap"
        )

    for feat_id in ("btn-audio-briefing", "today-arxiv-spotlight", "vault-subnav-bar", "inline-focus-bar", "btn-pulse-ramsey"):
        assert soup.find(id=feat_id) is not None, f"Missing redesigned UX feature #{feat_id}"
