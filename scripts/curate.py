#!/usr/bin/env python3
"""
PulseBoard autonomous curator.

Three honest content channels, merged into pulse_feed.json:

1. HAND-CURATED (articles_db.json, human/Gemini-written): evergreen stories
   and the Mind & Habits column. Always included, verbatim.
2. ARXIV PAPERS: weighted keyword scoring over recent submissions to
   quant-ph / cond-mat.mes-hall / physics.app-ph, filtered to the user's
   research profile (NMR & spin control, NV/diamond sensing, Floquet,
   coherence). TLDRs and takeaways are extracted VERBATIM from the authors'
   abstracts - extractive summarization only, so nothing is ever invented.
3. MULTI-SOURCE NEWS: RSS from a curated list of reputable outlets. Balance
   is structural - topic quotas, max one story per outlet per topic, and a
   cross-source corroboration boost (stories covered by several outlets
   score higher). Text is the outlet's own summary, never rewritten.
   Briefings are paragraph-structured, carry the article's own inline image
   gallery, and every cover image in the feed is guaranteed unique.

Run locally or via .github/workflows/update-pulse.yml (04:00/19:00 UTC).
The workflow commits the result; Vercel deploys; the app pulls the feed
after every unlock.
"""
import email.utils
import hashlib
import html as htmllib
import json
import math
import os
import re
import time
import urllib.request
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = 'PulseBoard-Curator/2.0'
EDITION = 'morning'  # automation serves the morning briefing


# --------------------------------------------------------------------------
# Editorial profile
# --------------------------------------------------------------------------

ARXIV_CATEGORIES = ['quant-ph', 'cond-mat.mes-hall', 'physics.app-ph']
ARXIV_PER_CATEGORY = 150

PAPER_KEYWORDS = {
    # NMR / control
    'nmr': 4, 'nuclear magnetic resonance': 4, 'trosy': 4, 'methyl': 4,
    'grape': 4, 'optimal control': 4, 'pulse sequence': 3, 'spin dynamics': 4,
    'hyperpolarization': 3, 'dnp': 3, 'dynamic nuclear polarization': 3,
    # NV / sensing
    'nv center': 4, 'nitrogen-vacancy': 4, 'diamond': 3, 'magnetometry': 3,
    'quantum sensing': 4, 'relaxometry': 3, 'sensor': 1,
    # driven systems / coherence
    'floquet': 4, 'dynamical decoupling': 3, 'decoherence': 3, 'spin bath': 4,
    'liouvillian': 3, 'open quantum system': 3, 'master equation': 2,
    'coherence': 2, 'qubit': 1,
    # foundations / misc
    'wigner': 3, 'measurement': 1, 'entanglement': 1,
    # weak generic signal (keeps purely-tangential papers out)
    'quantum': 0.2, 'spin': 0.5,
}

PAPER_TAG_RULES = [
    ('NMR & Spin Control', ['nmr', 'nuclear magnetic', 'trosy', 'methyl', 'grape',
                            'optimal control', 'pulse sequence', 'spin dynamics',
                            'hyperpolarization', 'dynamic nuclear polarization']),
    ('NV & Quantum Sensing', ['nv center', 'nitrogen-vacancy', 'diamond', 'magnetometry',
                              'quantum sensing', 'relaxometry']),
    ('Floquet & Driven Systems', ['floquet', 'dynamical decoupling', 'driven']),
    ('Coherence & Open Systems', ['decoherence', 'liouvillian', 'open quantum',
                                  'master equation', 'spin bath', 'coherence']),
    ('Quantum Foundations', ['wigner', 'measurement', 'entanglement', 'nonlocal']),
]
PAPER_TAG_DEFAULT = 'Spin & Quantum'

NEWS_SOURCES = {
    # Balanced across the political spectrum; ~15 outlets were tested and only
    # ones with working RSS kept. Text-fetchability varies (bot walls) and the
    # picker rotates to whichever outlet's copy is fetchable, so an
    # RSS-corroboration-only outlet (Times of Israel, Israel Hayom) still
    # boosts stories it covers without ever having to serve the briefing.
    'Geopolitics & Global': [
        ('BBC World', 'http://feeds.bbci.co.uk/news/world/rss.xml'),          # center
        ('The Guardian', 'https://www.theguardian.com/world/rss'),            # left
        ('NPR World', 'https://feeds.npr.org/1004/rss.xml'),                  # center-left
        ('CBC World', 'https://www.cbc.ca/webfeed/rss/rss-world'),            # center-left
        ('The Hindu', 'https://www.thehindu.com/news/national/feeder/default.rss'),  # center-left (India)
        ('Times of Israel', 'https://www.timesofisrael.com/feed/'),           # center-right (Israel)
        ('Israel Hayom', 'https://www.israelhayom.com/feed/'),                # right (Israel)
        ('NY Post', 'https://nypost.com/world-news/feed/'),                   # right
    ],
    'Tech & AI': [
        ('Ars Technica', 'https://feeds.arstechnica.com/arstechnica/index'),
        ('The Verge', 'https://www.theverge.com/rss/index.xml'),
    ],
    'Quantum & Physics': [
        ('Phys.org', 'https://phys.org/rss-feed/'),
        ('ScienceDaily Physics', 'https://www.sciencedaily.com/rss/matter_energy/physics.xml'),
    ],
}

# Political-spectrum tag per outlet (for the cross-spectrum corroboration
# bonus): stories covered by outlets on BOTH sides rank higher, so the
# briefing favors what left and right agree is news.
NEWS_SPECTRUM = {
    'The Guardian': 'left', 'NPR World': 'left', 'CBC World': 'left',
    'The Hindu': 'left',
    'BBC World': 'center',
    'Times of Israel': 'right', 'Israel Hayom': 'right', 'NY Post': 'right',
}

NEWS_KEYWORDS = {
    'Geopolitics & Global': {
        'israel': 4, 'gaza': 3, 'lebanon': 3, 'iran': 3, 'mediterranean': 3,
        'levant': 3, 'syria': 3, 'egypt': 2, 'turkey': 2, 'cyprus': 3,
        'india': 3, 'bengal': 2, 'energy': 2, 'gas': 2, 'oil': 1,
        'diplomacy': 2, 'ceasefire': 3, 'peace': 2, 'election': 2,
        'court': 1, 'war': 1, 'sanction': 2, 'treaty': 2,
    },
    'Tech & AI': {
        'ai': 3, 'artificial intelligence': 3, 'chip': 2, 'semiconductor': 3,
        'quantum computer': 3, 'model': 1, 'open source': 2, 'privacy': 2,
        'security': 2, 'apple': 1, 'google': 1, 'regulation': 2, 'compute': 2,
    },
    'Quantum & Physics': {
        'quantum': 3, 'spin': 3, 'nmr': 4, 'diamond': 3, 'nv center': 4,
        'sensor': 2, 'magnet': 2, 'superconduct': 2, 'particle': 2,
        'dark matter': 2, 'gravitational': 2, 'physic': 1, 'coherence': 2,
    },
}

NEWS_QUOTAS = {'Geopolitics & Global': 3, 'Tech & AI': 1, 'Quantum & Physics': 1}

# A full briefing must be at least this many words of the outlet's own text.
BRIEF_MIN_WORDS = 200

# Cover-image fallback POOLS (4 distinct verified URLs per category). Member 0
# is the long-standing default; the rest were extracted from real Unsplash
# search pages for each topic (never hand-typed — a guessed photo id 404s
# silently) and curl-verified HTTP 200 with a browser UA. Assignment is
# deterministic per story title and guaranteed distinct within a feed; see
# ensure_distinct_covers().
FALLBACK_CATEGORY_IMAGES = {
    'Geopolitics & Global': [
        'https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1524661135-423995f22d0b?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1706823871410-ed8b01faef7e?auto=format&fit=crop&w=1200&q=80',
    ],
    'Quantum & Physics': [
        'https://images.unsplash.com/photo-1635070041078-e363dbe005cb?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1576319155264-99536e0be1ee?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1666112835145-d79fc3f2e008?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1527409335569-f0e5c91fa707?auto=format&fit=crop&w=1200&q=80',
    ],
    'Tech & AI': [
        'https://images.unsplash.com/photo-1677442136019-21780ecad995?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1697577418970-95d99b5a55cf?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1674027444485-cec3da58eef4?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1694903110330-cc64b7e1d21d?auto=format&fit=crop&w=1200&q=80',
    ],
    'Mind & Habits': [
        'https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1506126613408-eca07ce68773?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1512438248247-f0f2a5a8b7f0?auto=format&fit=crop&w=1200&q=80',
        'https://images.unsplash.com/photo-1522075782449-e45a34f1ddfb?auto=format&fit=crop&w=1200&q=80',
    ],
}

BROWSER_UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 6a) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36')


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def http_get(url, timeout=20, ua=None):
    req = urllib.request.Request(url, headers={'User-Agent': ua or UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# Inline-article-image junk filter: logos, icons, avatars, badges, sprites,
# tracking pixels, ad hosts. The ad token is boundary-guarded so words like
# 'download' or 'road' in a filename are not mistaken for an ad.
GALLERY_JUNK_RE = re.compile(
    r'logo|icon|avatar|sprite|emoji|gravatar|badge|placeholder|tracking'
    r'|pixel|advert|doubleclick|(?<![a-z])ad[sv]?(?![a-z])'
    # people-shots are author headshots, not article figures
    r'|headshot|profile[-_]?pic|portrait|author'
    # The Verge's default author avatar (Firstname_BLURPLE.jpg)
    r'|_blurple', re.I)

# Dimension suffixes CDNs append ("-2560x1440", "_640x427") — the same
# picture as the lead image often appears under a suffixed URL, so gallery
# dedupe compares suffix-stripped basenames too.
_DIM_SUFFIX_RE = re.compile(r'[-_]\d{2,5}x\d{2,5}(?=\.[a-z]{3,4}$)', re.I)


def _img_normalize(url):
    """Canonical form for image-URL comparison: strip query + dimension suffix."""
    path = url.split('?', 1)[0]
    return _DIM_SUFFIX_RE.sub('', path).lower()

GALLERY_MAX = 3


def _absolutize(cand, base):
    """Resolve a candidate image URL against the page URL; '' if unusable."""
    cand = htmllib.unescape(cand or '').strip()
    if cand.startswith(('http://', 'https://')):
        return cand
    if cand and not cand.startswith('data:'):
        return urljoin(base, cand)
    return ''


def _jsonld_images(raw):
    """Image URLs from <script type="application/ld+json"> blocks, walked
    deeply (covers @graph nesting). The image may be a string, a list, or an
    object with url/@id. Order of appearance is preserved."""
    urls = []

    def harvest(node):
        if isinstance(node, list):
            for n in node:
                harvest(n)
        elif isinstance(node, dict):
            img = node.get('image')
            for v in (img if isinstance(img, list) else [img]):
                if isinstance(v, str):
                    urls.append(v)
                elif isinstance(v, dict):
                    urls.append(v.get('url') or v.get('@id') or '')
            for n in node.values():
                harvest(n)

    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                            raw, re.S | re.I):
        try:
            harvest(json.loads(block))
        except Exception:
            continue
    return [u for u in urls if isinstance(u, str) and u.startswith(('http://', 'https://'))]


def _lead_image_candidates(raw, url):
    """Lead-image candidates, best first: og:image, twitter:image,
    og:image:secure_url, then JSON-LD image. Absolutized, deduped."""
    cands = []

    def meta(*names):
        for name in names:
            m = (re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(name)
                           + r'["\'][^>]+content=["\']([^"\']+)', raw, re.I)
                 or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)='
                              + re.escape(name) + r'["\']', raw, re.I))
            if m:
                yield m.group(1)

    cands += list(meta('og:image'))
    cands += list(meta('twitter:image', 'twitter:image:src'))
    cands += list(meta('og:image:secure_url'))
    cands += _jsonld_images(raw)
    out = []
    for c in cands:
        c = _absolutize(c, url)
        if c and c not in out:
            out.append(c)
    return out


def _caption_ok(c):
    """Clean a candidate caption; '' if missing/generic/junk. Real captions
    say who or what the image shows; 'photo' or 'image' does not."""
    c = strip_html(c or '').strip()
    if not (4 <= len(c) <= 220):
        return ''
    low = c.lower().rstrip('.')
    if low in ('image', 'photo', 'picture', 'img', 'illustration', 'untitled',
               'placeholder', 'graphic', 'getty images', 'ap photo'):
        return ''
    if CODE_JUNK_RE.search(c):
        return ''
    return c


def _gallery_images(scope, base, lead):
    """Inline article images with their captions, when the page provides
    them. Sources, in order of authority: the enclosing <figure>'s
    <figcaption>, then the img's own alt text. Entries are {'url', 'alt'}
    dicts when a meaningful caption exists, plain URL strings otherwise.
    Junk-filtered (data: URIs, .svg, logo/icon/avatar/headshot basenames,
    explicit thumbnail sizes, tracking pixels, the lead image under any
    dimension-suffixed URL), deduped, capped at GALLERY_MAX."""
    out, seen = [], set()
    seen_norm = set()
    lead_norm = _img_normalize(lead) if lead else None

    def accept(tag, u, caption):
        if not u or u in seen or _img_normalize(u) in seen_norm:
            return False
        for dim in ('width', 'height'):
            m = re.search(r'\b' + dim + r'=["\'](\d+)["\']', tag, re.I)
            if m and int(m.group(1)) < 400:
                return False
        path = u.split('?', 1)[0]
        if path.lower().endswith('.svg'):
            return False
        if GALLERY_JUNK_RE.search(path.rsplit('/', 1)[-1].lower()):
            return False
        m_w = re.search(r'[?&](?:width|w)=(\d{1,4})\b', u)
        if m_w and int(m_w.group(1)) < 400:
            return False  # explicit thumbnail size (e.g. Guardian ?width=100)
        if lead and (u == lead or _img_normalize(u) == lead_norm):
            return False  # the lead/og image itself (also under suffixed URLs)
        seen.add(u)
        seen_norm.add(_img_normalize(u))
        cap = _caption_ok(caption)
        out.append({'url': u, 'alt': cap} if cap else u)
        return True

    def img_src(tag):
        m = (re.search(r'data-(?:lazy-)?src=["\']([^"\']+)["\']', tag, re.I)
             or re.search(r'(?<![\w-])src=["\']([^"\']+)["\']', tag, re.I))
        return m.group(1) if m else None

    # 1) <figure> blocks — the figcaption is the authoritative caption
    taken = []
    for fm in re.finditer(r'<figure\b[^>]*>.*?</figure\s*>', scope, re.S | re.I):
        fig = fm.group(0)
        tm = re.search(r'<img\b[^>]*>', fig, re.I)
        if not tm:
            continue
        tag = tm.group(0)
        src = img_src(tag)
        if not src:
            continue
        cm = re.search(r'<figcaption\b[^>]*>(.*?)</figcaption\s*>', fig, re.S | re.I)
        alt_m = re.search(r'\balt=["\']([^"\']*)["\']', tag, re.I)
        caption = strip_html(cm.group(1)) if cm else (alt_m.group(1) if alt_m else '')
        taken.append(fm.span())
        if accept(tag, _absolutize(src, base), caption):
            if len(out) >= GALLERY_MAX:
                return out
    # 2) bare <img> tags outside any figure — alt text only
    for im in re.finditer(r'<img\b[^>]*>', scope, re.I):
        if any(a <= im.start() < b for a, b in taken):
            continue
        tag = im.group(0)
        src = img_src(tag)
        if not src:
            continue
        alt_m = re.search(r'\balt=["\']([^"\']*)["\']', tag, re.I)
        if accept(tag, _absolutize(src, base), alt_m.group(1) if alt_m else ''):
            if len(out) >= GALLERY_MAX:
                return out
    return out


def _paragraphize(text, per=3):
    """Group a verbatim text's own sentences into paragraphs of `per`.
    Presentation only: no word is added, dropped, or reordered."""
    sents = sentences(text)
    if len(sents) <= 1:
        return [text] if text.strip() else []
    return [' '.join(sents[i:i + per]) for i in range(0, len(sents), per)]


# Residual code/boilerplate that survives as text (script content in JS
# strings, CSS in comments) — used on paragraphs AND captions.
CODE_JUNK_RE = re.compile(
    r'function\s*\(|getElementById|requestAnimationFrame|addEventListener\('
    r'|display\s*:\s*none|\{[a-zA-Z-]+\s*:\s*|var\s+\w+\s*=|window\.|document\.'
    r'|\.google-|@media|@import|<!\[CDATA',
    re.I,
)

# Promotional callouts that prefix real prose inside the same <p>
# ("Make New York Post a Preferred Source The Iran War may…").
PROMO_PREFIX_RE = re.compile(
    r'^(?:Make [A-Z][A-Za-z\'&. ]{2,40}? a Preferred Source'
    r'|Click here[^.]{0,60}\.?'
    r'|Thank you for reading[^.]{0,60}\.?)\s*',
)

# Callout phrases that disqualify a "paragraph" entirely (subscribe walls,
# share prompts, syndication notes). Kept as a tuple so tests can import it.
PARAGRAPH_JUNK_TOKENS = (
    'sign up', 'subscribe', 'newsletter', 'all rights reserved',
    'cookie', 'follow us', 'read more:', 'related:', 'originally published',
    'preferred source', 'daily email digest', 'posts from this topic',
    'homepage feed', 'share gift',
)


def clean_paragraph(t):
    """Verbatim paragraph text, or '' when the line is junk: promo prefixes
    bolted onto real prose, subscribe/callout text, captions/bylines/nav
    crumbs (too short), and CSS/JS that survived as text. This is the
    fetch_full_text() paragraph filter factored out so tests can hit the
    exact production path (the NY Post <style>/<script>-inside-<p>
    regression lives here)."""
    t = strip_html(t)  # strips <script>/<style> BLOCKS before tags (see below)
    t = PROMO_PREFIX_RE.sub('', t)
    if len(t) < 60:
        return ''  # captions, bylines, nav crumbs
    low = t.lower()
    if any(k in low for k in PARAGRAPH_JUNK_TOKENS):
        return ''
    if CODE_JUNK_RE.search(t):
        return ''  # CSS/JS that survived as text
    return t


# Conservative byline pattern: "By First Last" (1–4 capitalized words,
# hyphens/apostrophes/periods allowed). Deliberately strict — it must only
# fire on text the page itself presents as a byline.
BYLINE_RE = re.compile(r"By\s+((?:[A-Z][\w.'-]+)(?:\s+(?:[A-Z][\w.'-]+)){0,3})")

# Author strings that name a role/service, not a person.
NON_PERSON_AUTHORS = (
    'staff', 'editorial', 'newsroom', 'wire', 'reporter', 'contributor',
    'correspondent', 'associated press', 'reuters', 'bloomberg', 'afp',
    'the editorial board', 'news services', 'freelance',
)


def _author_ok(a):
    """Validate a candidate byline; '' when it is not a plausible person."""
    a = strip_html(a or '').strip()
    if not (3 <= len(a) <= 80):
        return ''
    low = a.lower()
    if any(k in low for k in NON_PERSON_AUTHORS):
        return ''
    if CODE_JUNK_RE.search(a) or '@' in a or 'http' in low:
        return ''
    return a


def _jsonld_authors(raw):
    """Author names from <script type="application/ld+json"> blocks, walked
    deeply (covers @graph nesting). The author may be a string, a list, or
    an object with a name (Person)."""
    names = []

    def harvest(node):
        if isinstance(node, list):
            for n in node:
                harvest(n)
        elif isinstance(node, dict):
            if 'author' in node:
                for v in (node['author'] if isinstance(node['author'], list)
                          else [node['author']]):
                    if isinstance(v, str):
                        names.append(v)
                    elif isinstance(v, dict) and isinstance(v.get('name'), str):
                        names.append(v['name'])
            for n in node.values():
                harvest(n)

    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                            raw, re.S | re.I):
        try:
            harvest(json.loads(block))
        except Exception:
            continue
    return names


def _byline_from_paragraphs(scope):
    """Byline from the article's own <p> fragments, searched per paragraph so
    the greedy name pattern can never swallow a capitalized word from the
    NEXT sentence/paragraph. Pass A: a standalone byline paragraph (the whole
    <p> is just "By Name"). Pass B: a byline at the very start of the first
    paragraph. '' when neither is present."""
    paras = [strip_html(p).strip()
             for p in re.findall(r'<p[^>]*>(.*?)</p>', scope or '', re.S | re.I)]
    paras = [t for t in paras if t][:6]
    for t in paras:  # Pass A: the paragraph IS the byline
        m = BYLINE_RE.match(t)
        if m and m.end() >= len(t):
            a = _author_ok(m.group(1))
            if a:
                return a
    if paras:  # Pass B: byline opens the first paragraph
        m = BYLINE_RE.match(paras[0])
        if m:
            a = _author_ok(m.group(1))
            if a:
                return a
    return ''


def extract_author(raw, scope=''):
    """Best-effort byline, '' when absent. Structured sources first (JSON-LD
    author, og:article:author / author meta), then the conservative byline
    pattern over the article's own paragraphs. Never invents: only text the
    page itself provides."""
    for name in _jsonld_authors(raw):
        a = _author_ok(name)
        if a:
            return a
    m = (re.search(r'<meta[^>]+(?:property|name)=["\'](?:article:)?author["\'][^>]+'
                   r'content=["\']([^"\']+)["\']', raw, re.I)
         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                      r'(?:property|name)=["\'](?:article:)?author["\']', raw, re.I))
    if m:
        a = _author_ok(m.group(1))
        if a:
            return a
    return _byline_from_paragraphs(scope)


def fetch_full_text(url, max_words=380):
    """Fetch the article page and extract, verbatim: its own paragraphs, its
    lead image (og:image > twitter:image > og:image:secure_url > JSON-LD
    image), up to GALLERY_MAX inline article images, and the article's
    byline when the page states one. Returns (paragraphs, lead_image,
    gallery, author); ([], '', [], '') if the page is unreachable."""
    try:
        raw = http_get(url, timeout=15, ua=BROWSER_UA).decode('utf-8', 'ignore')
    except Exception:
        return [], '', [], ''
    leads = _lead_image_candidates(raw, url)
    lead = leads[0] if leads else ''
    scope = raw
    m = re.search(r'<article[^>]*>(.*?)</article>', raw, re.S | re.I) \
        or re.search(r'<main[^>]*>(.*?)</main>', raw, re.S | re.I)
    if m:
        scope = m.group(1)
    # Drop script/style/etc BLOCKS before any text/img scanning, or their
    # contents masquerade as paragraphs and their HTML strings as images.
    scope = re.sub(r'<(script|style|noscript|template|svg)\b[^>]*>.*?</\1\s*>',
                   ' ', scope, flags=re.S | re.I)
    paras, total = [], 0
    for p in re.findall(r'<p[^>]*>(.*?)</p>', scope, re.S | re.I):
        t = clean_paragraph(p)
        if not t:
            continue
        paras.append(t)
        total += len(t.split())
        if total >= max_words:
            break
    author = extract_author(raw, scope)
    return paras, lead, _gallery_images(scope, url, lead), author


def strip_html(s):
    if not s:
        return ''
    # Non-prose BLOCKS must go first — removing just the tags would leave
    # their JS/CSS text behind as fake "paragraphs" (NY Post shipped
    # "…{display:none} (function() {…})()" into briefings this way).
    s = re.sub(r'<(script|style|noscript|template|svg)\b[^>]*>.*?</\1\s*>', ' ', s,
               flags=re.S | re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    s = s.replace('&quot;', '"').replace('&#39;', "'").replace('&apos;', "'")
    return re.sub(r'\s+', ' ', s).strip()


def heal_escapes(s):
    """Hand-authored content sometimes carries literal backslash-n; heal."""
    if not isinstance(s, str):
        return s
    return s.replace('\\n', '\n').replace('\\r', '')


def sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def read_time_minutes(*texts):
    words = sum(len(t.split()) for t in texts if t)
    return max(2, math.ceil(words / 200))


def keyword_score(text, weights, multiplier=1.0):
    t = text.lower()
    return sum(w * multiplier for kw, w in weights.items() if kw in t)


def matched_keywords(*texts):
    """Which research-profile keywords actually appear — powers the honest
    'why this paper' chips in the app (no hidden magic in curation)."""
    blob = ' '.join(texts).lower()
    hits = [kw for kw in PAPER_KEYWORDS if kw in blob]
    hits.sort(key=lambda k: -PAPER_KEYWORDS[k])
    return hits


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        iso = s[:-1] + '+00:00' if s.endswith('Z') else s
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


# --------------------------------------------------------------------------
# arXiv: score hundreds of recent papers, extract abstracts verbatim
# --------------------------------------------------------------------------

def fetch_arxiv_candidates():
    entries, seen = [], set()
    for cat in ARXIV_CATEGORIES:
        url = (f'https://export.arxiv.org/api/query?search_query=cat:{cat}'
               f'&sortBy=submittedDate&sortOrder=descending&max_results={ARXIV_PER_CATEGORY}')
        try:
            root = ET.fromstring(http_get(url))
        except Exception as e:
            print(f'arXiv fetch failed for {cat}: {e}')
            continue
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('a:entry', ns):
            id_el = entry.find('a:id', ns)
            title_el = entry.find('a:title', ns)
            summary_el = entry.find('a:summary', ns)
            if id_el is None or title_el is None or summary_el is None or not title_el.text:
                continue
            authors = []
            for a in entry.findall('a:author', ns):
                name = a.find('a:name', ns)
                if name is not None and name.text:
                    authors.append(' '.join(name.text.split()))
            pub_el = entry.find('a:published', ns)
            abs_id = (id_el.text or '').strip().rsplit('/', 1)[-1]
            base_id = abs_id.split('v')[0]
            if base_id in seen:
                continue
            seen.add(base_id)
            entries.append({
                'id': base_id,
                'title': ' '.join((title_el.text or '').split()),
                'summary': ' '.join((summary_el.text or '').split()),
                'cats': [c.get('term') for c in entry.findall('a:category', ns)],
                'authors': authors,
                'year': (pub_el.text or '')[:4] if pub_el is not None and pub_el.text else '',
            })
        time.sleep(3)  # arXiv API etiquette
    return entries


def arxiv_pdf_url(arxiv_id):
    """Direct PDF link for an arXiv paper (every digest paper is arXiv)."""
    return f'https://arxiv.org/pdf/{arxiv_id}'


def pick_papers():
    cand = fetch_arxiv_candidates()
    if not cand:
        raise RuntimeError('no arXiv candidates fetched')
    scored = []
    for p in cand:
        s = keyword_score(p['title'], PAPER_KEYWORDS, 3) + keyword_score(p['summary'], PAPER_KEYWORDS, 1)
        if s < 3:
            continue
        tag = PAPER_TAG_DEFAULT
        for tag_name, keys in PAPER_TAG_RULES:
            if any(k in p['title'].lower() or k in p['summary'].lower() for k in keys):
                tag = tag_name
                break
        scored.append((s, tag, p))
    scored.sort(key=lambda x: -x[0])
    picked = scored[:5]
    if not picked:  # nothing passed the bar: take the closest matches
        picked = sorted(((keyword_score(p['title'], PAPER_KEYWORDS, 3), PAPER_TAG_DEFAULT, p)
                         for p in cand), key=lambda x: -x[0])[:3]

    papers = []
    for s, tag, p in picked:
        sents = sentences(p['summary'])
        tldr = ' '.join(sents[:2]) if len(sents) > 1 else p['summary'][:220]
        # Extractive takeaways: the abstract's most keyword-dense sentences, verbatim
        ranked = sorted(sents, key=lambda x: -keyword_score(x, PAPER_KEYWORDS))[:3]
        takeaways = [sent for sent in sents if sent in ranked] or sents[:2]
        primary_cat = p['cats'][0] if p['cats'] else 'quant-ph'
        author_str = ''
        if p.get('authors'):
            author_str = ', '.join(p['authors'][:3]) + (' et al.' if len(p['authors']) > 3 else '')
        papers.append({
            'id': f'arxiv-{p["id"]}',
            'edition': EDITION,
            'tag': tag,
            'title': p['title'][:140] + ('...' if len(p['title']) > 140 else ''),
            'authors': author_str or 'arXiv authors',
            'year': p.get('year') or '',
            'arxivId': p['id'],
            'journal': f'arXiv:{p["id"]} [{primary_cat}]',
            'url': f'https://arxiv.org/abs/{p["id"]}',
            # Direct PDF link for the reader's "PDF ↗" affordance
            'pdfUrl': arxiv_pdf_url(p['id']),
            'readTime': f'{read_time_minutes(tldr, " ".join(takeaways))} min read',
            'tldr': tldr,
            'takeaways': takeaways,
            # Honest 'why this paper': the profile keywords it actually matched
            'matched': matched_keywords(p['title'], p['summary'])[:4],
            'saved': False,
        })
    return papers


# arXiv serves no per-paper imagery (only the generic site logo), so research
# digests get distinct CATEGORY visuals — verified Unsplash pool, larger than
# any single edition's paper count, deterministic pick by paper id.
PAPER_IMAGE_POOL = (
    FALLBACK_CATEGORY_IMAGES['Quantum & Physics']
    + FALLBACK_CATEGORY_IMAGES['Tech & AI']
)


def ensure_distinct_paper_images(papers):
    """Assign each paper a distinct category visual (deterministic, no repeats
    while the pool lasts — mirrors ensure_distinct_covers for stories)."""
    pool = PAPER_IMAGE_POOL
    used = set()
    for paper in papers:
        if paper.get('image'):
            used.add(paper['image'])
            continue
        seed = int(hashlib.sha1(paper['id'].encode()).hexdigest()[:8], 16) % len(pool)
        for off in range(len(pool)):
            url = pool[(seed + off) % len(pool)]
            if url not in used:
                used.add(url)
                paper['image'] = url
                paper['imageKind'] = 'category'
                break
        else:
            # Pool exhausted (more papers than images): deterministic reuse
            paper['image'] = pool[seed]
            paper['imageKind'] = 'category'
    return papers


# --------------------------------------------------------------------------
# News: multi-source RSS, structural balance, outlet-written text
# --------------------------------------------------------------------------

def item_image_from_xml(el):
    """The story's own image from feed XML: media:thumbnail / media:content /
    image enclosure / first inline <img>. Returns '' when absent."""
    try:
        raw = ET.tostring(el, encoding='unicode')
    except Exception:
        return ''
    m = (re.search(r'<media:thumbnail[^>]+url="([^"]+)"', raw)
         or re.search(r'<media:content[^>]+url="([^"]+)"', raw))
    if not m:
        m = (re.search(r'<enclosure[^>]+url="([^"]+)"[^>]+type="image', raw)
             or re.search(r'<enclosure[^>]+type="image[^"]*"[^>]+url="([^"]+)"', raw))
    if not m:
        m = re.search(r'<img[^>]+src="([^"]+)"', raw)
    if not m:
        return ''
    url = htmllib.unescape(m.group(1)).strip()
    return url if url.startswith(('http://', 'https://')) else ''


def parse_feed_items(xml_bytes):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return items
    for item in root.iter('item'):  # RSS 2.0
        items.append({
            'title': strip_html(item.findtext('title') or ''),
            'link': (item.findtext('link') or '').strip(),
            'description': strip_html(item.findtext('description') or ''),
            'pubDate': item.findtext('pubDate') or '',
            'image': item_image_from_xml(item),
        })
    if not items:  # Atom fallback
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('a:entry', ns):
            link = ''
            for l in entry.findall('a:link', ns):
                link = l.get('href') or link
                if l.get('rel') == 'alternate':
                    break
            items.append({
                'title': strip_html(entry.findtext('a:title', namespaces=ns) or ''),
                'link': link,
                'description': strip_html(entry.findtext('a:summary', namespaces=ns) or ''),
                'pubDate': entry.findtext('a:updated', namespaces=ns) or '',
                'image': item_image_from_xml(entry),
            })
    return [i for i in items if i['title'] and i['link']]


STOPWORDS = set('''the a an in on of for to and with as at by from is are after over into
amid says say report reports news new update live why how what who
will would could should its it his her their our your'''.split())


def title_tokens(title):
    toks = re.sub(r'[^a-z0-9 ]', ' ', title.lower()).split()
    return set(t for t in toks if t not in STOPWORDS and len(t) > 2)


def cluster_items(items):
    """Group near-identical stories across outlets (Jaccard on title tokens)."""
    clusters = []
    for it in items:
        placed = False
        for cl in clusters:
            a, b = title_tokens(it['title']), cl['tokens']
            if a and b and len(a & b) / len(a | b) >= 0.45:
                cl['items'].append(it)
                cl['tokens'] |= a
                placed = True
                break
        if not placed:
            clusters.append({'tokens': title_tokens(it['title']), 'items': [it]})
    return clusters


def ensure_distinct_covers(stories):
    """Guarantee every cover image in the feed is unique (hard app
    requirement — two stories sharing a fallback cover was a visible bug).

    Hand-curated stories claim their authored covers first; any story whose
    cover is missing or already claimed gets a deterministic distinct
    fallback from its category pool: pool[sha1(title) % len(pool)], walking
    forward through the pool until an unused URL is found (wrapping around;
    if a pool is ever exhausted, the hash slot is reused deterministically).
    """
    used = set()

    def claim(st):
        img = st.get('image') or ''
        if img and img not in used:
            used.add(img)
            return
        pool = FALLBACK_CATEGORY_IMAGES.get(st.get('category')) or []
        if not pool:
            return
        start = int(hashlib.sha1(st.get('title', '').encode('utf-8')).hexdigest(), 16) % len(pool)
        for i in range(len(pool)):
            cand = pool[(start + i) % len(pool)]
            if cand not in used:
                st['image'] = cand
                used.add(cand)
                return
        st['image'] = pool[start]  # pool exhausted: deterministic reuse
        used.add(pool[start])

    hand = [s for s in stories if not str(s.get('id', '')).startswith('news-')]
    auto = [s for s in stories if str(s.get('id', '')).startswith('news-')]
    for st in hand:  # authored covers take precedence
        claim(st)
    for st in auto:
        claim(st)


def also_covered_by(cl, rep):
    """Other outlets covering the same cluster as the chosen representative —
    honest verbatim links (they already exist in the cluster items), max 4,
    one per outlet, representative excluded."""
    out, seen = [], set()
    for it in cl.get('items', []):
        if it is rep or it.get('outlet') in seen:
            continue
        link = (it.get('link') or '').strip()
        if not link:
            continue
        seen.add(it.get('outlet'))
        out.append({'outlet': it['outlet'], 'url': link})
        if len(out) >= 4:
            break
    return out


def merge_stories(auto, hand):
    """Assemble the story list: hand-curated wins on title overlap with
    automated picks; hand entries pass through with ALL their fields intact
    (alsoCoveredBy / author / whyItMatters …) — there is no field whitelist."""
    hand_titles = [title_tokens(st.get('title', '')) for st in hand]
    auto_final = []
    for st in auto:
        tt = title_tokens(st['title'])
        dup = any(tt and ht and len(tt & ht) / len(tt | ht) >= 0.5 for ht in hand_titles if ht)
        if not dup:
            auto_final.append(st)
    return auto_final + hand


def _load_previous_auto_stories():
    """Return (prev_urls, prev_token_sets) from the currently committed
    pulse_feed.json so daily runs rotate in fresh stories instead of
    repeating yesterday's high-keyword picks."""
    prev_urls, prev_tokens = set(), []
    feed_path = os.path.join(BASE, 'pulse_feed.json')
    try:
        with open(feed_path, 'r', encoding='utf-8') as f:
            prev = json.load(f)
        for st in prev.get('stories', []):
            if not str(st.get('id', '')).startswith('news-'):
                continue
            u = (st.get('sourceUrl') or '').strip()
            if u:
                prev_urls.add(u)
            toks = title_tokens(st.get('title', ''))
            if toks:
                prev_tokens.append(toks)
    except Exception:
        pass
    return prev_urls, prev_tokens


def pick_news_stories():
    kw = NEWS_KEYWORDS
    now = datetime.now(timezone.utc)
    auto, used_sources = [], set()
    prev_urls, prev_tokens = _load_previous_auto_stories()

    for topic, sources in NEWS_SOURCES.items():
        items = []
        for outlet, url in sources:
            try:
                items += [{'outlet': outlet, **i} for i in parse_feed_items(http_get(url))]
            except Exception as e:
                print(f'{outlet} fetch failed: {e}')
        if not items:
            print(f'no items at all for {topic}')
            continue

        clusters = cluster_items(items)
        scored = []
        for cl in clusters:
            best = None
            for it in cl['items']:
                date = parse_date(it.get('pubDate'))
                fresh = 1.0
                if date:
                    age_h = (now - date).total_seconds() / 3600
                    if age_h <= 12:
                        fresh = 2.0
                    elif age_h <= 24:
                        fresh = 1.6
                    elif age_h <= 36:
                        fresh = 1.1
                    elif age_h <= 72:
                        fresh = 0.6
                    else:
                        fresh = 0.25
                s = (keyword_score(it['title'], kw[topic], 3)
                     + keyword_score(it['description'], kw[topic], 1)) * fresh
                if best is None or s > best[0]:
                    best = (s, it)
            # corroboration boost: several outlets running the same story,
            # plus a cross-spectrum bonus — coverage agreed on by both the
            # left- and right-tagged outlets ranks highest
            if best is not None:
                sides = {NEWS_SPECTRUM.get(i['outlet'], 'center') for i in cl['items']}
                spread = 1 + 0.1 * (len(sides) - 1)
                score = best[0] * (1 + 0.4 * (len(cl['items']) - 1)) * spread
                # Demote stories already present in the previous feed so new
                # daily articles rotate in while keeping old ones as fallback.
                already_shown = any((i.get('link') or '').strip() in prev_urls for i in cl['items'])
                if not already_shown and cl['tokens']:
                    already_shown = any(
                        len(cl['tokens'] & pt) / len(cl['tokens'] | pt) >= 0.45
                        for pt in prev_tokens if pt
                    )
                if already_shown:
                    score *= 0.15
                scored.append((score, best[1], cl))
        scored.sort(key=lambda x: -x[0])

        # Detailed-briefing-aware selection, three passes:
        #   1. strict: one story per outlet, prefer clusters whose source page
        #      yields a full (>=BRIEF_MIN_WORDS) briefing; short ones become
        #      fallbacks in score order.
        #   2. relaxed: if the quota still lacks full briefings, allow a
        #      second story from an already-used outlet — a detailed story
        #      beats a 30-word stub.
        #   3. promote the best short fallbacks if nothing extractable exists.
        quota = NEWS_QUOTAS[topic]
        picks, fallbacks = [], []
        consumed = set()   # indices of scored clusters already tried
        cache = {}         # link -> extracted text (dedupes refetches)
        fetches = {'n': 0}
        FETCH_BUDGET = 60  # per-topic page-fetch cap so bad days stay fast

        def full_text(link):
            if link not in cache:
                if fetches['n'] >= FETCH_BUDGET:
                    cache[link] = ([], '', [])
                else:
                    fetches['n'] += 1
                    cache[link] = fetch_full_text(link)
            return cache[link]

        def attempt(cl, allow_used):
            """Rotate the cluster's outlets (same corroborated story) until
            one copy yields a full briefing; return (rep, desc, paragraphs,
            image, gallery, author)."""
            cands = [c for c in cl['items'] if allow_used or c['outlet'] not in used_sources]
            if not cands:
                return None
            cands.sort(key=lambda x: -len(x['description']))
            best = None  # (words, rep, desc, paragraphs, image, gallery, author)
            for c in cands:
                d = c['description'] or ''
                if len(d) > 1000:
                    d = d[:1000].rsplit(' ', 1)[0] + '…'
                # Detailed briefing: the article's own paragraphs, verbatim;
                # keep whichever text is longer so a failed fetch never
                # degrades the summary. The lead image beats the feed image.
                paras, og, gallery, author = full_text(c['link'])
                if len(' '.join(paras).split()) <= len(d.split()):
                    # the feed summary wins: its own sentences, regrouped
                    # into paragraphs (verbatim — presentation only)
                    paras = _paragraphize(d)
                story_img = og or c.get('image') or ''
                words = len(' '.join(paras).split())
                if words >= BRIEF_MIN_WORDS:
                    return c, d, paras, story_img, gallery, author
                if best is None or words > best[0]:
                    best = (words, c, d, paras, story_img, gallery, author)
            return (best[1], best[2], best[3], best[4], best[5], best[6]) if best is not None else None

        def build_story(rep, desc, paragraphs, image, gallery, also=None, author=''):
            dek = sentences(desc)[0] if sentences(desc) else desc[:180]
            date_slug = now.strftime('%Y%m%d')
            # Unique per story (topic+date alone would collide when a topic
            # yields several stories), but stable across same-day reruns so
            # the app can carry saved flags between regenerations.
            title_hash = hashlib.sha1(rep['title'].encode('utf-8')).hexdigest()[:8]
            # Paragraph-structured verbatim briefing; the app renders the
            # \n\n breaks.
            content = '\n\n'.join(paragraphs)
            img = image or (FALLBACK_CATEGORY_IMAGES.get(topic) or [''])[0]
            story = {
                'id': f"news-{topic.split(' ')[0].lower()}-{date_slug}-{title_hash}",
                'edition': EDITION,
                'featured': False,
                'category': topic,
                'source': rep['outlet'],
                'readMin': read_time_minutes(content),
                # Political lean of the outlet in the curated pool; the app
                # shows a tiny chip so balance is visible, not just claimed.
                'spectrum': NEWS_SPECTRUM.get(rep['outlet'], ''),
                'sourceUrl': rep['link'],
                'title': rep['title'][:140] + ('...' if len(rep['title']) > 140 else ''),
                'dek': dek[:200] + ('…' if len(dek) > 200 else ''),
                'content': content,
                # The story's own lead image (og:image or the feed's media/
                # enclosure); a distinct category-pool fallback is assigned
                # in ensure_distinct_covers when missing or duplicated.
                'image': img,
                # The article's own inline images (junk-filtered; never the
                # cover), max GALLERY_MAX.
                'gallery': [g for g in (gallery or []) if g and g != img][:GALLERY_MAX],
                'saved': False,
            }
            # Byline, only when the article page itself states one — and not
            # when it merely repeats the outlet's own name ("By CBC")
            if author:
                a_low, o_low = author.lower(), rep['outlet'].lower()
                if a_low not in o_low and o_low not in a_low:
                    story['author'] = author
            # Cross-outlet coverage of the same cluster (verbatim links)
            if also:
                story['alsoCoveredBy'] = [a for a in also
                                          if a.get('outlet') and a.get('url')][:4]
            return story

        for idx, (s, it, cl) in enumerate(scored[:35]):
            if len(picks) >= quota:
                break
            consumed.add(idx)
            got = attempt(cl, allow_used=False)
            if got is None:
                continue
            rep, desc, paragraphs, image, gallery, author = got
            used_sources.add(rep['outlet'])
            story = build_story(rep, desc, paragraphs, image, gallery,
                                also_covered_by(cl, rep), author)
            if len(story['content'].split()) >= BRIEF_MIN_WORDS:
                picks.append(story)
            else:
                fallbacks.append(story)
        if len(picks) < quota:
            for idx, (s, it, cl) in enumerate(scored):
                if len(picks) >= quota:
                    break
                if idx in consumed:
                    continue
                got = attempt(cl, allow_used=True)
                if got is None:
                    continue
                rep, desc, paragraphs, image, gallery, author = got
                if len(' '.join(paragraphs).split()) < BRIEF_MIN_WORDS:
                    continue
                used_sources.add(rep['outlet'])
                picks.append(build_story(rep, desc, paragraphs, image, gallery,
                                         also_covered_by(cl, rep), author))
        for story in fallbacks:
            if len(picks) >= quota:
                break
            picks.append(story)
        auto.extend(picks)
    return auto


# --------------------------------------------------------------------------
# Autonomous Deadlines & Academic/Quantum Job Board Refresh
# --------------------------------------------------------------------------

JOB_FEED_URLS = [
    ('AcademicJobsOnline Physics', 'https://academicjobsonline.org/ajo?joblist-0-0-0-0----r--'),
]

JOB_PROFILE_KEYWORDS = [
    'open quantum', 'quantum control', 'quantum sensing', 'nv center',
    'nitrogen-vacancy', 'nmr', 'nuclear magnetic', 'spin dynamics',
    'floquet', 'decoherence', 'master equation', 'lindblad', 'diamond',
    'magnetometry', 'hyperpolarization', 'quantum information',
    'computational physics', 'quantum optics', 'condensed matter',
]


def refresh_deadlines_db():
    """Keep deadlines.json fresh during daily GitHub Actions runs:
    1. Roll recurring faculty/fellowship cutoffs that are >30 days past forward
       by 1 year so annual cycles stay current automatically.
    2. Poll live academic job RSS feeds (best-effort) for matching quantum/spin/
       physics roles and merge any new verified entries.
    """
    path = os.path.join(BASE, 'deadlines.json')
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            db = json.load(f)
    except Exception:
        return

    today = datetime.now(timezone.utc).date()
    changed = False

    # 1. Auto-advance recurring career_jobs & postdocs cutoffs >30 days past
    for section in ('career_jobs', 'postdocs'):
        for item in db.get(section, []):
            d_str = item.get('date', '')
            try:
                dt = datetime.strptime(d_str, '%Y-%m-%d').date()
            except ValueError:
                continue
            if (today - dt).days > 30:
                try:
                    next_dt = dt.replace(year=dt.year + 1)
                except ValueError:
                    # Feb 29 -> Feb 28
                    next_dt = dt.replace(year=dt.year + 1, day=28)
                item['date'] = next_dt.strftime('%Y-%m-%d')
                changed = True

    # 2. Best-effort live RSS poll from academic job boards
    existing_urls = {
        x.get('url') for sec in ('career_jobs', 'postdocs')
        for x in db.get(sec, []) if x.get('url')
    }
    for source_name, feed_url in JOB_FEED_URLS:
        raw = http_get(feed_url, timeout=12)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            desc = strip_html(item.findtext('description') or '')
            if not title or not link or not link.startswith('https://') or link in existing_urls:
                continue
            hay = (title + ' ' + desc).lower()
            matched = [kw for kw in JOB_PROFILE_KEYWORDS if kw in hay]
            if not matched:
                continue
            is_postdoc = any(w in hay for w in ('postdoc', 'post-doctoral', 'fellowship'))
            # Extract deadline YYYY-MM-DD if present in description, else default 45d out
            m_date = re.search(r'\b(202[6-9]-\d{2}-\d{2})\b', desc)
            if m_date:
                dl_date = m_date.group(1)
            else:
                from datetime import timedelta
                dl_date = (today + timedelta(days=45)).strftime('%Y-%m-%d')
            slug = hashlib.sha1(link.encode('utf-8')).hexdigest()[:8]
            if is_postdoc:
                db.setdefault('postdocs', []).append({
                    'id': f'pd-auto-{slug}',
                    'name': title[:130],
                    'org': source_name,
                    'subType': 'lab-opening',
                    'region': 'Global Feed',
                    'date': dl_date,
                    'cycle': 'Auto-discovered via daily GitHub Actions job feed',
                    'location': 'See official posting',
                    'tags': [m.title() for m in matched[:4]],
                    'url': link,
                })
            else:
                db.setdefault('career_jobs', []).append({
                    'id': f'job-auto-{slug}',
                    'name': title[:130],
                    'org': source_name,
                    'track': 'faculty',
                    'region': 'US & Global',
                    'filterGroup': 'faculty-us-me',
                    'date': dl_date,
                    'cycle': 'Auto-discovered via daily GitHub Actions job feed',
                    'location': 'See official posting',
                    'tags': [m.title() for m in matched[:4]],
                    'fit': f'Matched research profile keywords: {", ".join(matched[:4])}.',
                    'url': link,
                })
            existing_urls.add(link)
            changed = True

    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')


# --------------------------------------------------------------------------
# Assemble the feed
# --------------------------------------------------------------------------

def main():
    refresh_deadlines_db()
    # hand-curated stories: heal + keep (they are the evergreen / Mind column)
    with open(os.path.join(BASE, 'articles_db.json'), 'r', encoding='utf-8') as f:
        hand = json.load(f)
    for st in hand:
        for k in ('title', 'dek', 'content', 'whyItMatters', 'source'):
            if k in st:
                st[k] = heal_escapes(st[k])

    auto = pick_news_stories()

    # hand-curated wins on title overlap with automated picks; hand fields
    # (alsoCoveredBy / author / …) pass through untouched — see merge_stories
    stories = merge_stories(auto, hand)

    # hard requirement: no two stories in a feed share a cover image
    ensure_distinct_covers(stories)
    papers = ensure_distinct_paper_images(pick_papers())

    feed = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stories': stories,
        'papers': papers,
    }
    out = os.path.join(BASE, 'pulse_feed.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
    print(f'pulse_feed.json: {len(stories)} stories ({len(stories) - len(hand)} auto + {len(hand)} hand), '
          f'{len(feed["papers"])} papers, stamp {feed["generated_at"]}')


if __name__ == '__main__':
    main()
