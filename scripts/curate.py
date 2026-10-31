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

Run locally or via .github/workflows/update-pulse.yml (04:00/19:00 UTC).
The workflow commits the result; Vercel deploys; the app pulls the feed
after every unlock.
"""
import email.utils
import hashlib
import json
import math
import os
import re
import time
import urllib.request
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
    'Geopolitics & Global': [
        ('Al Jazeera', 'https://www.aljazeera.com/xml/rss/all.xml'),
        ('BBC World', 'http://feeds.bbci.co.uk/news/world/rss.xml'),
        ('The Guardian', 'https://www.theguardian.com/world/rss'),
        ('Times of Israel', 'https://www.timesofisrael.com/feed/'),
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

NEWS_QUOTAS = {'Geopolitics & Global': 2, 'Tech & AI': 1, 'Quantum & Physics': 1}

FALLBACK_CATEGORY_IMAGES = {
    'Geopolitics & Global': 'https://images.unsplash.com/photo-1544620347-c4fd4a3ca5b7?w=800&q=70&auto=format&fit=crop',
    'Quantum & Physics': 'https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=800&q=70&auto=format&fit=crop',
    'Tech & AI': 'https://images.unsplash.com/photo-1677442136019-21780ecad995?w=800&q=70&auto=format&fit=crop',
    'Mind & Habits': 'https://images.unsplash.com/photo-1506703719100-a0fd414b6bed?w=800&q=70&auto=format&fit=crop',
}


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def strip_html(s):
    if not s:
        return ''
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


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
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
            })
        time.sleep(3)  # arXiv API etiquette
    return entries


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
        papers.append({
            'id': f'arxiv-{p["id"]}',
            'edition': EDITION,
            'tag': tag,
            'title': p['title'][:140] + ('...' if len(p['title']) > 140 else ''),
            'journal': f'arXiv:{p["id"]} [{primary_cat}]',
            'url': f'https://arxiv.org/abs/{p["id"]}',
            'readTime': f'{read_time_minutes(tldr, " ".join(takeaways))} min read',
            'tldr': tldr,
            'takeaways': takeaways,
            'saved': False,
        })
    return papers


# --------------------------------------------------------------------------
# News: multi-source RSS, structural balance, outlet-written text
# --------------------------------------------------------------------------

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


def images_map():
    """Category images: inherit from hand-curated entries where available."""
    imgs = dict(FALLBACK_CATEGORY_IMAGES)
    try:
        with open(os.path.join(BASE, 'articles_db.json'), 'r', encoding='utf-8') as f:
            for st in json.load(f):
                if st.get('image') and st.get('category'):
                    imgs.setdefault(st['category'], st['image'])
    except Exception:
        pass
    return imgs


def pick_news_stories():
    kw = NEWS_KEYWORDS
    imgs = images_map()
    now = datetime.now(timezone.utc)
    auto, used_sources = [], set()

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
                    if age_h <= 24:
                        fresh = 1.5
                    elif age_h <= 48:
                        fresh = 1.2
                    elif age_h > 96:
                        fresh = 0.7
                s = (keyword_score(it['title'], kw[topic], 3)
                     + keyword_score(it['description'], kw[topic], 1)) * fresh
                if best is None or s > best[0]:
                    best = (s, it)
            # corroboration boost: several outlets running the same story
            if best is not None:
                scored.append((best[0] * (1 + 0.4 * (len(cl['items']) - 1)), best[1], cl))
        scored.sort(key=lambda x: -x[0])

        picked = 0
        for s, it, cl in scored:
            if picked >= NEWS_QUOTAS[topic]:
                break
            if it['outlet'] in used_sources:
                continue
            # prefer the cluster item with the longest description for readability
            rep = max(cl['items'], key=lambda x: len(x['description']))
            if rep['outlet'] in used_sources and it['outlet'] not in used_sources:
                rep = it
            used_sources.add(rep['outlet'])
            desc = rep['description'] or it['description']
            if len(desc) > 1000:
                desc = desc[:1000].rsplit(' ', 1)[0] + '…'
            dek = sentences(desc)[0] if sentences(desc) else desc[:180]
            date_slug = now.strftime('%Y%m%d')
            # Unique per story (topic+date alone would collide when a topic
            # yields several stories), but stable across same-day reruns so
            # the app can carry saved flags between regenerations.
            title_hash = hashlib.sha1(rep['title'].encode('utf-8')).hexdigest()[:8]
            auto.append({
                'id': f"news-{topic.split(' ')[0].lower()}-{date_slug}-{title_hash}",
                'edition': EDITION,
                'featured': False,
                'category': topic,
                'source': f"{rep['outlet']} • {read_time_minutes(desc)} min read",
                'sourceUrl': rep['link'],
                'title': rep['title'][:140] + ('...' if len(rep['title']) > 140 else ''),
                'dek': dek[:200] + ('…' if len(dek) > 200 else ''),
                'content': desc,
                'image': imgs.get(topic, FALLBACK_CATEGORY_IMAGES.get(topic, '')),
                'saved': False,
            })
            picked += 1
    return auto


# --------------------------------------------------------------------------
# Assemble the feed
# --------------------------------------------------------------------------

def main():
    # hand-curated stories: heal + keep (they are the evergreen / Mind column)
    with open(os.path.join(BASE, 'articles_db.json'), 'r', encoding='utf-8') as f:
        hand = json.load(f)
    for st in hand:
        for k in ('title', 'dek', 'content', 'whyItMatters', 'source'):
            if k in st:
                st[k] = heal_escapes(st[k])

    auto = pick_news_stories()

    # hand-curated wins on title overlap with automated picks
    hand_titles = [title_tokens(st.get('title', '')) for st in hand]
    auto_final = []
    for st in auto:
        tt = title_tokens(st['title'])
        dup = any(tt and ht and len(tt & ht) / len(tt | ht) >= 0.5 for ht in hand_titles if ht)
        if not dup:
            auto_final.append(st)

    # freshest news first; the reflective hand-written column closes the briefing
    stories = auto_final + hand

    feed = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stories': stories,
        'papers': pick_papers(),
    }
    out = os.path.join(BASE, 'pulse_feed.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
    print(f'pulse_feed.json: {len(stories)} stories ({len(auto_final)} auto + {len(hand)} hand), '
          f'{len(feed["papers"])} papers, stamp {feed["generated_at"]}')


if __name__ == '__main__':
    main()
