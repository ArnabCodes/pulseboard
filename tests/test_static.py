"""Static-analysis tests for the single-file app (item 92).

Guards three classes of wiring bugs that a browser would only reveal late:

1. Syntax — the one giant inline <script> is extracted to a temp file and run
   through `node --check` (skipped gracefully when node is not installed).
2. Duplicate top-level function declarations — a re-declared function name
   silently shadows the earlier one; the whole wave adds functions to a
   shared file, so a NEW duplicate must fail the suite. Pre-existing
   duplicates (none at the time of writing) would go into KNOWN_DUPS and get
   reported, not silently ignored.
3. getElementById wiring — every literal `getElementById('X')` in the script
   must have a matching `id="X"` somewhere in the file. The id set is built
   from the WHOLE file: static HTML attributes plus ids emitted inside the
   script's own template literals and `el.id = '...'` assignments, because
   several views are rendered entirely from JS.

Run: python3 -m pytest tests/test_static.py -v
"""
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / 'index.html'

# Function names that were ALREADY declared twice before this suite existed.
# Empty today; a new duplicate fails the test below and, if it is genuinely
# pre-existing across the merge, gets added here WITH a comment.
KNOWN_DUPS = set()


def _html():
    return INDEX.read_text(encoding='utf-8')


def _inline_scripts(html):
    scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
    assert scripts, 'no inline <script> found in index.html'
    return scripts


def test_index_html_exists_and_has_single_inline_script():
    html = _html()
    scripts = _inline_scripts(html)
    assert len(scripts) == 1, (
        f'expected exactly one inline <script>, found {len(scripts)} '
        '(the app is a deliberate single-file build)'
    )


def test_inline_script_passes_node_check():
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed — JS syntax check skipped')
    script = _inline_scripts(_html())[0]
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        proc = subprocess.run(
            [node, '--check', path],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass
    assert proc.returncode == 0, (
        f'node --check failed on the inline script:\n{proc.stderr}'
    )


def test_no_duplicate_function_declarations():
    script = _inline_scripts(_html())[0]
    names = re.findall(r'\bfunction\s+([A-Za-z_$][\w$]*)\s*\(', script)
    assert names, 'no function declarations found — extraction is broken'
    counts = Counter(names)
    dups = {n: c for n, c in counts.items() if c > 1}
    new_dups = {n: c for n, c in dups.items() if n not in KNOWN_DUPS}
    assert not new_dups, (
        'NEW duplicate function declarations (later declarations silently '
        f'shadow earlier ones): {new_dups}. '
        f'Pre-existing/allowed: {sorted(KNOWN_DUPS) or "none"}'
    )
    if dups:
        # known dups still get reported so the allowlist can be pruned
        print(f'known duplicate function declarations still present: {dups}')


def test_every_getelementbyd_ref_has_a_matching_id():
    html = _html()
    script = _inline_scripts(html)[0]

    # id="X" anywhere in the file — static HTML AND ids inside the script's
    # own template literals (several views are rendered from JS strings).
    ids_in_file = set(re.findall(r'id="([^"]+)"', html))
    # ids assigned in JS via el.id = '...' (dynamically created elements).
    ids_assigned = set(re.findall(r"\.id\s*=\s*'([^']+)'", script))
    known_ids = ids_in_file | ids_assigned

    # Literal single-argument lookups only: getElementById('page-' + kind)
    # and similar dynamic calls are intentionally out of scope.
    refs = set(re.findall(r"getElementById\(\s*'([A-Za-z0-9_-]+)'\s*\)", script))
    assert refs, 'no literal getElementById calls found — extraction is broken'

    missing = sorted(refs - known_ids)
    assert not missing, (
        'getElementById references without a matching id="..." anywhere in '
        f'the file (wiring typos): {missing}'
    )
