"""Tests for the pure functions in scripts/curate.py.

curate.py was NOT refactored for testability; anything needing the network or
the RSS/arXiv pipeline is intentionally out of scope. Two reduced surfaces,
noted per the task:
  - the news-id generator is a closure inside pick_news_stories(), so its
    *recipe* (sha1(title)[:8]) is asserted directly plus conformance of the
    committed pulse_feed.json ids;
  - feed-shape invariants are asserted on synthetic stories and on the
    committed pulse_feed.json via tests/validate_feed.py's checker.

Run: python3 -m pytest tests/ -v
"""
import hashlib
import importlib
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

curate = importlib.import_module('curate')
validate_feed = importlib.import_module('validate_feed')

GEO_POOL = curate.FALLBACK_CATEGORY_IMAGES['Geopolitics & Global']
BASE = 'https://example.com/story/page'


def make_story(sid, title, image, category='Geopolitics & Global'):
    return {'id': sid, 'title': title, 'image': image, 'category': category}


# --------------------------------------------------------------------------
# keyword_score / matched_keywords
# --------------------------------------------------------------------------

def test_keyword_score_sums_weights_case_insensitively():
    weights = {'nmr': 4, 'nv center': 4, 'quantum': 0.2}
    assert curate.keyword_score('NV CENTER sensing with NMR', weights) == pytest.approx(8.0)


def test_keyword_score_multiplier_and_no_match():
    weights = {'floquet': 4}
    assert curate.keyword_score('Floquet engineering', weights, 3) == 12
    assert curate.keyword_score('a story about pelicans', weights) == 0
    assert curate.keyword_score('', weights, 3) == 0


def test_matched_keywords_reports_only_present_keywords_ordered_by_weight():
    blob = 'NMR pulse sequence NV center diamond magnetometry'
    hits = curate.matched_keywords(blob, '')
    assert hits
    assert all(k in blob.lower() for k in hits)  # honesty: only real hits
    weights = [curate.PAPER_KEYWORDS[k] for k in hits]
    assert weights == sorted(weights, reverse=True)  # highest-signal first
    assert {'nmr', 'nv center', 'diamond'} <= set(hits)


def test_matched_keywords_no_hits():
    assert curate.matched_keywords('a story about pelicans') == []


# --------------------------------------------------------------------------
# _paragraphize — verbatim, presentation-only regrouping
# --------------------------------------------------------------------------

def test_paragraphize_is_word_preserving():
    text = ('One sentence here. Two sentences now! Three, with care; still three. '
            'Four follows. Five ends it.')
    paras = curate._paragraphize(text, per=3)
    assert paras
    assert ' '.join(paras).split() == text.split()  # no word added/dropped/reordered


def test_paragraphize_groups_three_sentences_default():
    assert curate._paragraphize('S1. S2. S3. S4. S5.') == ['S1. S2. S3.', 'S4. S5.']


def test_paragraphize_short_and_empty_inputs():
    assert curate._paragraphize('Only one sentence.') == ['Only one sentence.']
    assert curate._paragraphize('   ') == []


# --------------------------------------------------------------------------
# sha1 id generator (recipe + committed-feed conformance)
# --------------------------------------------------------------------------

def test_news_id_recipe_is_deterministic_sha1_prefix():
    # build_story() inside pick_news_stories() builds ids as
    # news-<topic-word>-<yyyymmdd>-<sha1(title)[:8]>; assert the recipe.
    title = 'Crews search for survivors after quake'
    h1 = hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]
    h2 = hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]
    assert h1 == h2 and len(h1) == 8
    int(h1, 16)  # hex


def test_committed_feed_ids_conform_to_recipe():
    with open(os.path.join(ROOT, 'pulse_feed.json'), encoding='utf-8') as f:
        feed = json.load(f)
    news = [s for s in feed['stories'] if str(s.get('id', '')).startswith('news-')]
    assert news, 'expected at least one automated story in the committed feed'
    pat = re.compile(r'^news-\w+-\d{8}-[0-9a-f]{8}$')
    for s in news:
        assert pat.match(s['id']), f'malformed auto id: {s["id"]}'
        # where the title wasn't truncated to 140 chars, the hash is
        # recomputable from the stored title
        if not s['title'].endswith('...') and len(s['title']) <= 140:
            expected = hashlib.sha1(s['title'].encode('utf-8')).hexdigest()[:8]
            assert s['id'].endswith(expected), f'id hash mismatch for {s["id"]}'


# --------------------------------------------------------------------------
# _gallery_images — junk/small/tracking filters on fixture HTML
# --------------------------------------------------------------------------

def test_gallery_filters_junk_small_and_tracking():
    scope = (
        '<img src="https://cdn.example.com/logo.png">'
        '<img src="https://cdn.example.com/site-icon.png">'
        '<img src="https://cdn.example.com/avatar.png">'
        '<img src="https://cdn.example.com/chart.svg">'
        '<img src="https://cdn.example.com/pixel-1.png">'
        '<img width="320" src="https://cdn.example.com/too-small.jpg">'
        '<img height="240" src="https://cdn.example.com/short.jpg">'
        '<img src="https://cdn.example.com/track.jpg?w=1">'
        '<img src="https://cdn.example.com/other.jpg?width=1">'
        '<img src="data:image/png;base64,AAAA">'
        '<img src="https://cdn.example.com/real-photo.jpg">'
    )
    out = curate._gallery_images(scope, BASE, 'https://cdn.example.com/lead.jpg')
    assert out == ['https://cdn.example.com/real-photo.jpg']


def test_gallery_dedupes_caps_at_three_and_absolutizes():
    scope = ('<img src="/a.jpg">' * 2
             + '<img src="/b.jpg"><img src="/c.jpg"><img src="/d.jpg">')
    out = curate._gallery_images(scope, BASE, '')
    assert out == ['https://example.com/a.jpg',
                   'https://example.com/b.jpg',
                   'https://example.com/c.jpg']


def test_gallery_skips_lead_image_including_query_variant():
    scope = ('<img src="https://cdn.example.com/lead.jpg">'
             '<img src="https://cdn.example.com/other.jpg">')
    assert curate._gallery_images(scope, BASE, 'https://cdn.example.com/lead.jpg') \
        == ['https://cdn.example.com/other.jpg']
    # lead matched by path even when its URL carries a query string
    assert curate._gallery_images(scope, BASE, 'https://cdn.example.com/lead.jpg?w=1200') \
        == ['https://cdn.example.com/other.jpg']


def test_gallery_ad_filter_is_boundary_guarded():
    # 'download'/'road' contain "ad" but must NOT be treated as ads
    keep = '<img src="/download-report.jpg"><img src="/road-trip.jpg">'
    assert curate._gallery_images(keep, BASE, '') == [
        'https://example.com/download-report.jpg',
        'https://example.com/road-trip.jpg']
    # real ad basenames are filtered (the junk regex scans the basename only)
    drop = '<img src="/ad-banner.jpg"><img src="/ads.jpg"><img src="/advert.png">'
    assert curate._gallery_images(drop, BASE, '') == []


def test_gallery_prefers_lazy_src():
    scope = '<img data-lazy-src="/lazy.jpg" src="data:image/gif;base64,R0lGOD">'
    assert curate._gallery_images(scope, BASE, '') == ['https://example.com/lazy.jpg']


# --------------------------------------------------------------------------
# ensure_distinct_covers — the distinct-covers invariant
# --------------------------------------------------------------------------

def test_missing_covers_get_distinct_pool_images():
    stories = [make_story('news-a', 'Alpha', ''), make_story('news-b', 'Bravo', '')]
    curate.ensure_distinct_covers(stories)
    assert stories[0]['image'] in GEO_POOL
    assert stories[1]['image'] in GEO_POOL
    assert stories[0]['image'] != stories[1]['image']


def test_duplicate_covers_get_reassigned():
    dup = 'https://cdn.example.com/dup.jpg'
    stories = [make_story('news-a', 'Alpha', dup), make_story('news-b', 'Bravo', dup)]
    curate.ensure_distinct_covers(stories)
    assert stories[0]['image'] == dup           # first claim keeps it
    assert stories[1]['image'] != dup
    assert stories[1]['image'] in GEO_POOL      # deterministic fallback


def test_hand_authored_covers_take_precedence_over_automated():
    shared = 'https://cdn.example.com/shared.jpg'
    hand = make_story('mind-1', 'Handwritten', shared, category='Mind & Habits')
    auto = make_story('news-x', 'Automated', shared)
    curate.ensure_distinct_covers([auto, hand])  # order in list must not matter
    assert hand['image'] == shared               # authored cover is claimed first
    assert auto['image'] != shared               # automated story gets a fallback


def test_ensure_distinct_covers_is_deterministic_across_calls():
    def run():
        stories = [make_story('news-a', 'Alpha', ''),
                   make_story('news-b', 'Bravo', ''),
                   make_story('news-c', 'Charlie', '')]
        curate.ensure_distinct_covers(stories)
        return [s['image'] for s in stories]
    assert run() == run()


def test_pool_exhaustion_is_deterministic():
    # 5 stories vs a 4-URL pool: the first four are distinct; the fifth
    # deterministically reuses its hash slot (documented behavior — full
    # uniqueness is only guaranteed up to the pool size).
    titles = [f'Story number {i}' for i in range(5)]

    def run():
        stories = [make_story(f'news-{i}', t, '') for i, t in enumerate(titles)]
        curate.ensure_distinct_covers(stories)
        return [s['image'] for s in stories]

    a, b = run(), run()
    assert a == b
    assert len(set(a[:4])) == 4


def test_unknown_category_is_left_alone_without_crash():
    s = make_story('news-z', 'Zulu', '', category='Nowhere')
    curate.ensure_distinct_covers([s])
    assert s['image'] == ''  # no pool for the category: unchanged, no crash


# --------------------------------------------------------------------------
# Feed shape invariants — synthetic and committed feed
# --------------------------------------------------------------------------

def test_synthetic_feed_shape_after_curation():
    stories = ([make_story(f'news-{i}', f'News story {i}', '') for i in range(3)]
               + [make_story('mind-1', 'Mind column', '', category='Mind & Habits')])
    curate.ensure_distinct_covers(stories)
    for s in stories:
        for field in ('id', 'title', 'image'):
            assert s.get(field), f'{field} empty after curation'
    imgs = [s['image'] for s in stories]
    assert len(set(imgs)) == len(imgs)  # the hard invariant


def test_committed_feed_passes_all_hard_invariants():
    with open(os.path.join(ROOT, 'pulse_feed.json'), encoding='utf-8') as f:
        feed = json.load(f)
    errors, warnings = validate_feed.check_feed(feed, check_images=False)
    assert errors == [], errors


def test_validator_catches_a_synthetic_bad_feed():
    bad = {
        'stories': [
            {'id': 'x', 'title': 'T', 'content': 'C', 'image': 'dup.jpg'},
            {'id': 'x', 'title': 'T2', 'content': 'C', 'image': 'dup.jpg'},
            {'id': 'y', 'title': 'T3', 'content': 'C'},  # missing image
        ],
        'papers': [],  # none
    }
    errors, _ = validate_feed.check_feed(bad, check_images=False)
    assert any('duplicate story id' in e for e in errors)
    assert any('duplicate cover image' in e for e in errors)
    assert any('missing/empty image' in e for e in errors)
    assert any('no papers' in e for e in errors)


# --------------------------------------------------------------------------
# clean_paragraph — the fetch_full_text paragraph filter (NY Post regression:
# a <p> whose content mixes a <style> block, a <script> block, a promo
# prefix, and the real sentence)
# --------------------------------------------------------------------------

def test_strip_html_removes_style_and_script_blocks_first():
    raw = ('<style>a{display:none}</style>'
           "<script>var x = 1; window.alert('hi');</script>"
           'Real text here')
    assert curate.strip_html(raw) == 'Real text here'


def test_clean_paragraph_strips_promo_prefix_keeps_sentence():
    raw = ('Make New York Post a Preferred Source '
           'The quake struck the border region at dawn and damaged dozens of buildings across the valley.')
    out = curate.clean_paragraph(raw)
    assert out.startswith('The quake struck')
    assert 'Preferred Source' not in out


def test_clean_paragraph_survives_style_script_inside_the_p():
    # the NY Post bug: one <p> carrying a <style> block, a <script> block
    # AND the real sentence — the blocks must vanish, the sentence must stay
    raw = ('<style>.hideme{display:none}</style>'
           "<script>function x(){document.getElementById('a')}</script>"
           'The minister signed the accord after three days of talks in the capital city.')
    out = curate.clean_paragraph(raw)
    assert out.startswith('The minister signed')
    assert 'display' not in out
    assert 'function' not in out
    assert 'getElementById' not in out


def test_clean_paragraph_drops_pure_junk_paragraph():
    raw = ('<style>a{display:none}</style>'
           '<script>var x=1; window.alert(1)</script>')
    assert curate.clean_paragraph(raw) == ''


def test_clean_paragraph_drops_callouts_and_short_captions():
    callout = ('Please subscribe to our daily email digest for the best '
               'coverage every single morning, straight to your inbox.')
    assert curate.clean_paragraph(callout) == ''
    assert curate.clean_paragraph('Photo credit: Getty Images') == ''  # < 60 chars
    assert curate.clean_paragraph('') == ''


# --------------------------------------------------------------------------
# _gallery_images / _caption_ok — captioned figures + junk (regression test)
# --------------------------------------------------------------------------

def test_gallery_keeps_captioned_figures_drops_avatar_thumb_and_lead_dupe():
    lead = 'https://cdn.example.com/lead.jpg'
    scope = (
        # the good stuff: real <figure> blocks with real figcaptions
        '<figure><img src="https://cdn.example.com/real.jpg">'
        '<figcaption>Real caption naming the people in the photo</figcaption></figure>'
        # author avatar (junk basename)
        '<img src="https://cdn.example.com/avatar-author-100.png" alt="author photo">'
        # explicit thumbnail size (?width=100 < 400)
        '<img src="https://cdn.example.com/thumb.jpg?width=100" alt="thumb">'
        # the lead image under a dimension-suffixed URL (dedupe must catch it)
        '<img src="https://cdn.example.com/lead-2560x1440.jpg" alt="lead dupe">'
        # second good figure, sized attributes large enough to pass
        '<figure><img src="https://cdn.example.com/second.jpg" width="1200" height="800">'
        '<figcaption>Another real caption describing the scene</figcaption></figure>'
    )
    out = curate._gallery_images(scope, BASE, lead)
    assert out == [
        {'url': 'https://cdn.example.com/real.jpg',
         'alt': 'Real caption naming the people in the photo'},
        {'url': 'https://cdn.example.com/second.jpg',
         'alt': 'Another real caption describing the scene'},
    ]


def test_caption_ok_rejects_generic_and_keeps_real():
    assert curate._caption_ok('photo') == ''
    assert curate._caption_ok('Getty Images') == ''
    assert curate._caption_ok('x') == ''
    real = 'Ministers meet at the palace to sign the accord'
    assert curate._caption_ok(real) == real


# --------------------------------------------------------------------------
# also_covered_by — cross-outlet coverage of the chosen cluster story
# --------------------------------------------------------------------------

def test_also_covered_by_collects_other_outlets_max_four():
    rep = {'outlet': 'BBC World', 'link': 'https://bbc.example/y', 'title': 't'}
    cl = {'items': [
        rep,
        {'outlet': 'The Guardian', 'link': 'https://guardian.example/1'},
        {'outlet': 'The Guardian', 'link': 'https://guardian.example/2'},  # dupe outlet
        {'outlet': 'NY Post', 'link': 'https://nypost.example/1'},
        {'outlet': 'NPR World', 'link': 'https://npr.example/1'},
        {'outlet': 'CBC World', 'link': 'https://cbc.example/1'},
        {'outlet': 'Israel Hayom', 'link': 'https://ih.example/1'},  # beyond max 4
    ]}
    assert curate.also_covered_by(cl, rep) == [
        {'outlet': 'The Guardian', 'url': 'https://guardian.example/1'},
        {'outlet': 'NY Post', 'url': 'https://nypost.example/1'},
        {'outlet': 'NPR World', 'url': 'https://npr.example/1'},
        {'outlet': 'CBC World', 'url': 'https://cbc.example/1'},
    ]


def test_also_covered_by_empty_for_solo_cluster():
    rep = {'outlet': 'BBC World', 'link': 'https://bbc.example/y'}
    assert curate.also_covered_by({'items': [rep]}, rep) == []
    # a second outlet with no link contributes nothing
    other = {'outlet': 'Phys.org', 'link': ''}
    assert curate.also_covered_by({'items': [rep, other]}, rep) == []


# --------------------------------------------------------------------------
# extract_author — bylines from JSON-LD, meta, or the conservative regex
# --------------------------------------------------------------------------

def test_extract_author_prefers_structured_sources():
    raw = ('<script type="application/ld+json">'
           '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Sarah K. Chen"}]}'
           '</script>')
    assert curate.extract_author(raw) == 'Sarah K. Chen'
    meta = '<meta property="article:author" content="James P. Osei">'
    assert curate.extract_author(meta) == 'James P. Osei'


def test_extract_author_byline_regex_fallback():
    raw = '<p>By Maria Delgado-Martinez</p><p>More text follows this paragraph here.</p>'
    assert curate.extract_author(raw, raw) == 'Maria Delgado-Martinez'


def test_extract_author_absent_and_non_person():
    assert curate.extract_author('<p>Nothing but plain prose in this paragraph.</p>') == ''
    assert curate.extract_author(
        '<meta property="article:author" content="Staff Reporter">') == ''
    assert curate.extract_author(
        '<script type="application/ld+json">{"author":"newsroom"}</script>') == ''


# --------------------------------------------------------------------------
# arxiv_pdf_url / merge_stories — pdfUrl + hand-field passthrough
# --------------------------------------------------------------------------

def test_arxiv_pdf_url():
    assert curate.arxiv_pdf_url('2401.12345') == 'https://arxiv.org/pdf/2401.12345'
    assert curate.arxiv_pdf_url('quant-ph/0508202') == 'https://arxiv.org/pdf/quant-ph/0508202'


def test_merge_stories_passes_hand_fields_through_untouched():
    hand = {'id': 'mind-1', 'title': 'Habit stacking for deep work',
            'author': 'Anne Author',
            'alsoCoveredBy': [{'outlet': 'BBC World', 'url': 'https://bbc.example/x'}],
            'whyItMatters': 'Because focus compounds.'}
    auto = {'id': 'news-a', 'title': 'Quake hits the region', 'author': 'Wire Name'}
    auto_dup = {'id': 'news-b', 'title': 'Habit stacking for deep work'}  # overlaps hand
    out = curate.merge_stories([auto, auto_dup], [hand])
    assert [s['id'] for s in out] == ['news-a', 'mind-1']  # dup dropped, hand last
    assert out[1] is hand                                   # same object: no rebuild/whitelist
    assert out[1]['author'] == 'Anne Author'
    assert out[1]['alsoCoveredBy'][0]['outlet'] == 'BBC World'
    assert out[0]['author'] == 'Wire Name'                  # auto fields kept too


def test_gallery_filters_spacer_logo_alt_and_author_profile_paths():
    scope = (
        '<img src="https://www.thehindu.com/theme/images/th-online/1x1_spacer.png" alt="The Hindu Logo">'
        '<img src="https://platform.theverge.com/wp-content/uploads/sites/2/chorus/author_profile_images/195820/JESSICA_WEATHERBED.0.jpg" alt="Jess Weatherbed">'
        '<img src="https://cdn.example.com/brand-mark.jpg" alt="Site Logo">'
        '<img src="https://cdn.example.com/genuine-scene.jpg" alt="Protesters gather outside parliament at dusk">'
    )
    out = curate._gallery_images(scope, BASE, '')
    assert out == [{
        'url': 'https://cdn.example.com/genuine-scene.jpg',
        'alt': 'Protesters gather outside parliament at dusk',
    }]

