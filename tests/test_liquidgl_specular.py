"""Empirical test suite for LiquidGL WebGL initialization and interactive specular highlights.

Validates:
1. `pbInitLiquidGL` safely guards against missing/offline `window.liquidGL` and headless WebGL errors.
2. `#apple-wallpaper` attribute `data-liquid-ignore` is removed dynamically by `pbInitLiquidGL()`.
3. `.liquidgl-lens` has `pointer-events: none !important` and `z-index: 0`.
4. `.lg-bar-shell::after` and `.lg-card::before` have `pointer-events: none` and `z-index: 1`, while interactive children have `z-index: 2` or higher.
5. `pbWireSpecularHighlights` uses `{ passive: true }` and `requestAnimationFrame` debouncing, and only modifies `--lg-mx` and `--lg-my` on hovered cards.
6. All clickable elements, inputs, buttons, and drawers remain interactive without interception.
"""

import json
import re
import subprocess
from pathlib import Path
import bs4
import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
JSC_PATH = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


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
    proc = subprocess.run(
        [JSC_PATH, "-e", js_code],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"JSC execution failed (exit code {proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc.stdout.strip()


def test_pb_init_liquidgl_guards_missing_and_offline():
    """Verify pbInitLiquidGL safely guards against missing window.liquidGL and offline envs."""
    html = _read_html()
    script = _extract_script(html)
    m = re.search(r"function pbInitLiquidGL\(\)\s*\{[\s\S]*?\n    \}", script)
    assert m, "pbInitLiquidGL declaration not found"
    fn_code_json = json.dumps(m.group(0))

    js = f"""
    const fnCode = {fn_code_json};
    const makeRunner = () => new Function('window', 'document', 'console', fnCode + '; pbInitLiquidGL();');

    // Case 1: window.liquidGL is undefined
    let runner1 = makeRunner();
    runner1({{}}, null, console);

    // Case 2: window.liquidGL is null
    let runner2 = makeRunner();
    runner2({{ liquidGL: null }}, null, console);

    // Case 3: window.liquidGL is an object instead of function
    let runner3 = makeRunner();
    runner3({{ liquidGL: {{ notA: 'function' }} }}, null, console);

    print('OK');
    """
    out = _run_jsc(js)
    assert out == "OK"


def test_pb_init_liquidgl_removes_wallpaper_data_liquid_ignore():
    """Verify #apple-wallpaper data-liquid-ignore is present statically and removed dynamically."""
    html = _read_html()
    soup = bs4.BeautifulSoup(html, "html.parser")
    wallpaper = soup.find(id="apple-wallpaper")
    assert wallpaper is not None, "#apple-wallpaper element not found"
    assert wallpaper.get("data-liquid-ignore") == "true", (
        "#apple-wallpaper must statically declare data-liquid-ignore='true'"
    )

    script = _extract_script(html)
    m = re.search(r"function pbInitLiquidGL\(\)\s*\{[\s\S]*?\n    \}", script)
    assert m, "pbInitLiquidGL declaration not found"
    fn_code_json = json.dumps(m.group(0))

    js = f"""
    const fnCode = {fn_code_json};

    let attrs = {{ 'data-liquid-ignore': 'true' }};
    let wallpaperEl = {{
        hasAttribute: (a) => a in attrs,
        removeAttribute: (a) => {{ delete attrs[a]; }}
    }};

    let liquidGLCalled = false;
    let liquidGLConfig = null;
    let win = {{
        liquidGL: (cfg) => {{
            liquidGLCalled = true;
            liquidGLConfig = cfg;
        }}
    }};
    let doc = {{
        getElementById: (id) => (id === 'apple-wallpaper' ? wallpaperEl : null)
    }};

    let runner = new Function('window', 'document', fnCode + '; pbInitLiquidGL();');
    runner(win, doc);

    if (attrs['data-liquid-ignore'] !== undefined) {{
        throw new Error('data-liquid-ignore was not removed from #apple-wallpaper');
    }}
    if (!liquidGLCalled) {{
        throw new Error('window.liquidGL was not called');
    }}
    if (liquidGLConfig.target !== '.liquidgl-lens') {{
        throw new Error('Target lens selector must be .liquidgl-lens');
    }}
    if (liquidGLConfig.snapshot !== '#apple-wallpaper') {{
        throw new Error('Snapshot selector must be #apple-wallpaper');
    }}
    print('OK:' + JSON.stringify(liquidGLConfig));
    """
    out = _run_jsc(js)
    assert out.startswith("OK:")
    cfg = json.loads(out[3:])
    assert cfg["target"] == ".liquidgl-lens"
    assert cfg["snapshot"] == "#apple-wallpaper"
    assert cfg["specular"] is True
    assert cfg["shadow"] is False


def test_pb_init_liquidgl_catches_webgl_failure():
    """Verify pbInitLiquidGL catches WebGL context creation failure in headless/virtualized envs."""
    html = _read_html()
    script = _extract_script(html)
    m = re.search(r"function pbInitLiquidGL\(\)\s*\{[\s\S]*?\n    \}", script)
    fn_code_json = json.dumps(m.group(0))

    js = f"""
    const fnCode = {fn_code_json};
    let warnLogs = [];
    let consoleMock = {{
        warn: function() {{ warnLogs.push(Array.from(arguments).join(' ')); }}
    }};

    let win = {{
        liquidGL: () => {{
            throw new Error('WebGL 2 context creation failed: headless');
        }}
    }};
    let doc = {{
        getElementById: () => ({{
            hasAttribute: () => false,
            removeAttribute: () => {{}}
        }})
    }};

    let runner = new Function('window', 'document', 'console', fnCode + '; pbInitLiquidGL();');
    runner(win, doc, consoleMock);

    if (warnLogs.length === 0) {{
        throw new Error('Expected console.warn log when WebGL fails');
    }}
    print('OK:' + warnLogs[0]);
    """
    out = _run_jsc(js)
    assert out.startswith("OK:")
    assert "fallback to CSS backdrop-filter" in out


def test_pb_init_liquidgl_prevents_double_init():
    """Verify pbInitLiquidGL avoids double-initialization when renderer exists."""
    html = _read_html()
    script = _extract_script(html)
    m = re.search(r"function pbInitLiquidGL\(\)\s*\{[\s\S]*?\n    \}", script)
    fn_code_json = json.dumps(m.group(0))

    js = f"""
    const fnCode = {fn_code_json};
    let calls = 0;
    let win = {{
        __liquidGLRenderer__: {{ captureSnapshot: () => {{}} }},
        liquidGL: () => {{ calls++; }}
    }};
    let doc = {{ getElementById: () => null }};

    let runner = new Function('window', 'document', fnCode + '; pbInitLiquidGL();');
    runner(win, doc);

    if (calls !== 0) throw new Error('liquidGL called despite existing renderer');
    print('OK');
    """
    out = _run_jsc(js)
    assert out == "OK"


def test_liquidgl_lens_css_rules():
    """Verify .liquidgl-lens has pointer-events: none !important and z-index: 0."""
    html = _read_html()
    style = _extract_style(html)
    m = re.search(r"\.liquidgl-lens\s*\{([^}]+)\}", style)
    assert m, "CSS rule .liquidgl-lens not found"
    rule_content = m.group(1)

    assert "pointer-events: none !important" in rule_content, (
        f".liquidgl-lens must declare 'pointer-events: none !important'. Found: {rule_content}"
    )
    assert re.search(r"\bz-index\s*:\s*0\b", rule_content), (
        f".liquidgl-lens must declare 'z-index: 0'. Found: {rule_content}"
    )
    assert "position: absolute" in rule_content, ".liquidgl-lens must be position: absolute"
    assert "inset: 0" in rule_content, ".liquidgl-lens must span inset: 0"


def test_specular_pseudo_elements_css_rules():
    """Verify .lg-bar-shell::after and .lg-card::before have pointer-events: none and z-index: 1."""
    html = _read_html()
    style = _extract_style(html)

    # .lg-bar-shell::after
    m_bar = re.search(r"\.lg-bar-shell::after\s*\{([^}]+)\}", style)
    assert m_bar, ".lg-bar-shell::after CSS rule not found"
    bar_content = m_bar.group(1)
    assert "pointer-events: none" in bar_content
    assert re.search(r"\bz-index\s*:\s*1\b", bar_content)
    assert "--lg-mx" in bar_content and "--lg-my" in bar_content

    # .lg-card::before
    m_card = re.search(r"\.lg-card::before\s*\{([^}]+)\}", style)
    assert m_card, ".lg-card::before CSS rule not found"
    card_content = m_card.group(1)
    assert "pointer-events: none" in card_content
    assert re.search(r"\bz-index\s*:\s*1\b", card_content)
    assert "--lg-mx" in card_content and "--lg-my" in card_content


def test_interactive_children_stacking_order():
    """Verify .lg-card > * has z-index: 2 or higher, and .lg-bar-shell interactive elements are lifted."""
    html = _read_html()
    style = _extract_style(html)

    m_children = re.search(r"\.lg-card\s*>\s*\*\s*\{([^}]+)\}", style)
    assert m_children, ".lg-card > * CSS rule not found"
    children_content = m_children.group(1)
    assert re.search(r"\bz-index\s*:\s*2\b", children_content), (
        f".lg-card > * must specify z-index: 2. Found: {children_content}"
    )

    # Inspect #app-header-glass direct interactive children in DOM
    soup = bs4.BeautifulSoup(html, "html.parser")
    header_glass = soup.find(id="app-header-glass")
    assert header_glass is not None, "#app-header-glass not found"
    for child in header_glass.find_all(recursive=False):
        classes = child.get("class", [])
        if "liquidgl-lens" in classes:
            continue
        assert "z-10" in classes or "relative" in classes, (
            f"Header glass child {child.name} missing z-index lifting class: {classes}"
        )


def test_specular_highlights_passive_raf_and_hover_isolation():
    """Verify pbWireSpecularHighlights uses { passive: true }, rAF debouncing, and hovers only target."""
    html = _read_html()
    script = _extract_script(html)
    m = re.search(r"function pbWireSpecularHighlights\(\)\s*\{[\s\S]*?\n    \}", script)
    assert m, "pbWireSpecularHighlights not found"
    fn_code_json = json.dumps(m.group(0))

    js = f"""
    const fnCode = {fn_code_json};
    let registered = [];
    let winMock = {{
        addEventListener: function(t, fn, opts) {{ registered.push({{ t, fn, opts }}); }}
    }};
    let rafCallbacks = [];
    let rafIdCounter = 1;
    let rafMock = function(cb) {{
        let id = rafIdCounter++;
        rafCallbacks.push({{ id, cb }});
        return id;
    }};

    function mockEl(cls, left, top) {{
        let styles = {{}};
        return {{
            className: cls,
            style: {{
                setProperty: function(k, v) {{ styles[k] = v; }},
                getPropertyValue: function(k) {{ return styles[k] || ''; }}
            }},
            getBoundingClientRect: function() {{ return {{ left: left, top: top, width: 300, height: 200 }}; }},
            closest: function(sel) {{
                if (sel.indexOf('.lg-card') !== -1 && cls.indexOf('lg-card') !== -1) return this;
                if (sel.indexOf('.lg-bar-shell') !== -1 && cls.indexOf('lg-bar-shell') !== -1) return this;
                if (this.parent) return this.parent.closest(sel);
                return null;
            }},
            _styles: styles
        }};
    }}

    let cardA = mockEl('lg-card card-hover', 100, 200);
    let cardB = mockEl('lg-card', 500, 200);
    let childA = mockEl('lg-pill', 120, 220);
    childA.parent = cardA;
    let bg = mockEl('bg-slate-950', 0, 0);

    let runner = new Function('window', 'requestAnimationFrame', fnCode + '; pbWireSpecularHighlights();');
    runner(winMock, rafMock);

    // 1. Passive listener
    if (registered.length !== 1 || registered[0].t !== 'pointermove' || !registered[0].opts || registered[0].opts.passive !== true) {{
        throw new Error('Listener must be pointermove with passive: true');
    }}
    let handler = registered[0].fn;

    // 2. Debouncing: fire 4 events in rapid succession
    handler({{ target: childA, clientX: 140, clientY: 240 }});
    handler({{ target: childA, clientX: 150, clientY: 250 }});
    handler({{ target: childA, clientX: 160, clientY: 260 }});
    handler({{ target: childA, clientX: 170, clientY: 270 }});

    if (rafCallbacks.length !== 1) {{
        throw new Error('Expected exactly 1 rAF callback scheduled, found ' + rafCallbacks.length);
    }}

    // Flush rAF
    rafCallbacks.shift().cb();

    // Verify coordinates: clientX 170 - rect.left 100 = 70px; clientY 270 - rect.top 200 = 70px
    if (cardA._styles['--lg-mx'] !== '70px' || cardA._styles['--lg-my'] !== '70px') {{
        throw new Error('Card A coords incorrect: ' + JSON.stringify(cardA._styles));
    }}
    if (Object.keys(cardB._styles).length !== 0) {{
        throw new Error('Card B was modified when Card A was hovered');
    }}

    // 3. Move over background (no card hovered)
    handler({{ target: bg, clientX: 10, clientY: 10 }});
    rafCallbacks.shift().cb();
    if (cardA._styles['--lg-mx'] !== '70px') {{
        throw new Error('Card A was corrupted by background move');
    }}
    if (Object.keys(cardB._styles).length !== 0) {{
        throw new Error('Card B was corrupted by background move');
    }}

    print('OK');
    """
    out = _run_jsc(js)
    assert out == "OK"


def test_all_interactive_elements_non_intercepted():
    """Verify that all clickable elements, inputs, buttons, and drawers remain interactive."""
    html = _read_html()
    soup = bs4.BeautifulSoup(html, "html.parser")

    interactive_tags = ["button", "a", "input", "select", "textarea"]
    elements = soup.find_all(interactive_tags)
    assert len(elements) >= 150, f"Expected at least 150 interactive elements, found {len(elements)}"

    for el in elements:
        curr = el
        while curr:
            classes = curr.get("class", [])
            cid = curr.get("id", "")
            assert "liquidgl-lens" not in classes, f"Interactive element {el.name} (id={el.get('id')}) is inside .liquidgl-lens"
            assert cid != "apple-wallpaper", f"Interactive element {el.name} (id={el.get('id')}) is inside #apple-wallpaper"
            curr = curr.parent


def test_overlays_and_drawers_hidden_by_default():
    """Verify that modal layers and drawer pages are hidden by default to prevent click blocking."""
    html = _read_html()
    soup = bs4.BeautifulSoup(html, "html.parser")

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


def test_cascade_analysis_liquidgl_lens_and_card_children():
    """Verify that .liquidgl-lens and .lg-card > * rules exist and assess cascade specificity."""
    html = _read_html()
    style = _extract_style(html)

    m_lens = re.search(r"\.liquidgl-lens\s*\{([^}]+)\}", style)
    m_card_children = re.search(r"\.lg-card\s*>\s*\*\s*\{([^}]+)\}", style)
    assert m_lens and m_card_children

    lens_rule = m_lens.group(1)
    card_children_rule = m_card_children.group(1)

    # .liquidgl-lens specifies tier 0 background properties
    assert "pointer-events: none !important" in lens_rule
    assert "z-index: 0" in lens_rule
    assert "position: absolute" in lens_rule

    # .lg-card > * specifies tier 2 content properties
    assert "z-index: 2" in card_children_rule
    assert "position: relative" in card_children_rule
