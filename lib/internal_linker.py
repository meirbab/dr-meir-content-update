"""
Internal linking module for dr-meir.com.

Scans post/page/category bodies for mentions of OTHER content's keywords and
adds anchor tags linking to those URLs. Safe HTML replacement that respects:
  - existing anchor tags (don't link inside <a>)
  - HTML attributes (don't replace text inside attribute values)
  - headings (skip H1/H2/H3 — anchors inside headings look spammy)
  - self-links (don't link a post to itself)
  - duplicate anchors (don't link the same text twice on the same page)

Uses a longest-match-first strategy so specific terms (e.g.,
"שאיבת שומן Quantum RF") match before generic ones (e.g., "שאיבת שומן").
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def normalize_anchor(s: str) -> str:
    """Strip HTML, normalize whitespace, lowercase for comparison."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip().lower()


def build_corpus(posts: list, categories: list, exclude_keywords=None) -> list:
    """Build [(keyword_lower, keyword_original, url, source_id, source_type)].

    posts: list of {id, slug, title:{rendered}, link, ...}
    categories: list of {id, name, link, count}
    """
    exclude = set((exclude_keywords or []))
    # Generic noise that's too short or appears in too many posts to be useful
    GENERIC_BLOCKLIST = {
        'טיפול', 'טיפולים', 'רפואה', 'רפואי', 'עור', 'הזרקה', 'הזרקות',
        'מטופל', 'מטופלים', 'מטפלים', 'תוצאה', 'תוצאות', 'הליך', 'הליכים',
        'אסתטי', 'אסתטית', 'אסתטיקה',
        'דר מאיר', 'מאיר באבאיב', 'באבאיב',
        # Single Hebrew words that are too generic
        'נשים', 'גברים', 'פנים', 'גוף', 'בטן', 'ירכיים', 'זרועות', 'בטן וירכיים',
    }

    corpus = []
    seen_keywords = set()

    # Posts: use title as primary anchor candidate
    for p in posts:
        if p.get('status') != 'publish':
            continue
        title_raw = p.get('title', {}).get('rendered', '')
        title = re.sub(r'<[^>]+>', '', title_raw).strip()
        # Decode common HTML entities
        try:
            import html as _html
            title = _html.unescape(title)
        except Exception:
            pass
        if not title:
            continue
        if len(title) < 6:
            continue
        if title in exclude or title in GENERIC_BLOCKLIST:
            continue
        link = p.get('link', '')
        if not link:
            continue
        title_lower = title.lower()
        if title_lower in seen_keywords:
            continue
        # Skip very generic post titles
        if title_lower in GENERIC_BLOCKLIST:
            continue
        corpus.append((title_lower, title, link, p['id'], 'post'))
        seen_keywords.add(title_lower)

    # Categories: name → category archive URL
    for c in categories:
        if c.get('count', 0) < 5:
            continue  # only categories with substantial post count
        name = c.get('name', '').strip()
        if not name or name == 'ללא קטגוריה':
            continue
        if name in GENERIC_BLOCKLIST:
            continue
        link = c.get('link', f'https://dr-meir.com/category/{c.get("slug","")}/')
        name_lower = name.lower()
        if name_lower in seen_keywords:
            continue
        corpus.append((name_lower, name, link, c['id'], 'category'))
        seen_keywords.add(name_lower)

    # Sort by keyword length DESC — longer matches first to win specificity
    corpus.sort(key=lambda x: -len(x[0]))
    return corpus


# Regex helpers — these segment HTML so we don't replace inside dangerous regions

_TAG_RE = re.compile(r'(<[^>]+>)')
_HEADING_BLOCK_RE = re.compile(r'<h[1-6][^>]*>.*?</h[1-6]>', re.S | re.I)
_ANCHOR_BLOCK_RE = re.compile(r'<a\b[^>]*>.*?</a>', re.S | re.I)


def _mark_no_replace_regions(html: str):
    """Find ranges in HTML where we should NOT replace text:
       - inside HTML tags (attributes)
       - inside existing <a>...</a>
       - inside headings <h1>..<h6>
    Returns set of (start, end) byte ranges to avoid.
    """
    ranges = []
    for m in _TAG_RE.finditer(html):
        ranges.append((m.start(), m.end()))
    for m in _ANCHOR_BLOCK_RE.finditer(html):
        ranges.append((m.start(), m.end()))
    for m in _HEADING_BLOCK_RE.finditer(html):
        ranges.append((m.start(), m.end()))
    return ranges


def _is_in_no_replace(pos: int, ranges) -> bool:
    for s, e in ranges:
        if s <= pos < e:
            return True
    return False


def insert_links(html: str, corpus: list, current_url: str,
                 current_id: int, max_links: int = 5) -> tuple:
    """For a given HTML body, insert anchor tags wherever a corpus keyword
    matches outside protected regions. Returns (new_html, links_added).

    Protections:
      - skip self-links (current_url match)
      - skip if text is already inside an <a> or <h1-6> or HTML tag
      - one link per anchor text per page
      - max_links cap per page
    """
    if not html or not corpus:
        return html, 0

    used_anchors = set()
    links_added = 0
    out = html

    for keyword_lower, keyword_original, url, src_id, src_type in corpus:
        if links_added >= max_links:
            break
        if src_id == current_id:
            continue
        if url == current_url:
            continue
        if keyword_lower in used_anchors:
            continue
        # Find first occurrence outside protected regions
        # Use case-insensitive match but preserve original case in replacement
        pattern = re.compile(re.escape(keyword_original), re.IGNORECASE)
        protected = _mark_no_replace_regions(out)
        m = pattern.search(out)
        while m and _is_in_no_replace(m.start(), protected):
            m = pattern.search(out, m.end())
        if not m:
            continue
        # Construct replacement — keep the matched text's original case
        matched_text = out[m.start():m.end()]
        link_html = f'<a href="{url}">{matched_text}</a>'
        out = out[:m.start()] + link_html + out[m.end():]
        used_anchors.add(keyword_lower)
        links_added += 1

    return out, links_added


def update_post_links(post_id: int, corpus: list, dry_run: bool = False,
                      max_links: int = 5) -> dict:
    """Apply internal linking to all text-editor widgets in a post."""
    from wp_client import (
        get_post, update_elementor, clear_elementor_cache, submit_indexnow,
    )
    from elementor_tree import ElementorDoc

    post = get_post(post_id)
    title = re.sub(r'<[^>]+>', '', post.get('title', {}).get('rendered', '')).strip()
    link = post.get('link', '')
    elem_str = post['meta'].get('_elementor_data', '') or ''
    if not elem_str:
        return {'post_id': post_id, 'title': title, 'status': 'skip',
                'reason': 'no elementor data'}
    try:
        elem = json.loads(elem_str)
    except Exception:
        return {'post_id': post_id, 'title': title, 'status': 'error',
                'reason': 'invalid elementor json'}

    total_added = 0
    widgets_modified = 0

    def visit(node):
        nonlocal total_added, widgets_modified
        if isinstance(node, list):
            for n in node:
                visit(n)
            return
        if not isinstance(node, dict):
            return
        if node.get('widgetType') == 'text-editor' and total_added < max_links:
            settings = node.setdefault('settings', {})
            html = settings.get('editor', '')
            if html:
                remaining = max_links - total_added
                new_html, n = insert_links(
                    html, corpus, link, post_id, max_links=remaining,
                )
                if n > 0:
                    settings['editor'] = new_html
                    total_added += n
                    widgets_modified += 1
        for c in node.get('elements', []) or []:
            visit(c)

    visit(elem)

    if total_added == 0:
        return {'post_id': post_id, 'title': title, 'status': 'skip',
                'reason': 'no link opportunities'}

    if dry_run:
        return {'post_id': post_id, 'title': title, 'status': 'dry-run',
                'links_added': total_added, 'widgets_modified': widgets_modified}

    new_str = json.dumps(elem, ensure_ascii=False, separators=(',', ':'))
    update_elementor(post_id, new_str)
    clear_elementor_cache()
    submit_indexnow(link)

    return {
        'post_id': post_id,
        'title': title,
        'status': 'ok',
        'links_added': total_added,
        'widgets_modified': widgets_modified,
    }
