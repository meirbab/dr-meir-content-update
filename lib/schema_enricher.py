"""
Schema enricher: auto-detect FAQs from any post's Elementor structure,
generate FAQPage + MedicalProcedure schema, append as html widget.

Idempotent: skips if schema already injected (looks for our marker class id).
Use for fast batch processing of posts that already have content but no
custom schema.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wp_client import (
    get_post, update_elementor, clear_elementor_cache,
    submit_indexnow, fetch_live_html
)
from elementor_tree import ElementorDoc
from schema import medical_procedure_faq_schema


SCHEMA_WIDGET_ID_PREFIX = 'schauto'


def extract_faqs_from_tree(tree: list) -> list:
    """Walk the Elementor tree and find ALL FAQ-like Q&A pairs.

    Detects:
    1. nested-accordion widgets — items[].item_title + child container's first text-editor
    2. accordion widgets — same pattern
    3. toggle widgets
    4. Inline H3+P pairs in text-editor widgets (where content has '<h3>...</h3>...<p>...</p>')

    Defensive: wraps every node visit in try/except so a malformed widget
    can't crash the whole extraction. Returns whatever FAQs we extracted
    successfully before any errors.
    """
    faqs = []

    def strip_html(s):
        if not isinstance(s, str):
            s = str(s)
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()

    def visit(node):
        try:
            return _visit_unsafe(node)
        except Exception:
            # Don't let one malformed widget crash extraction
            return

    def _visit_unsafe(node):
        if isinstance(node, list):
            for n in node:
                visit(n)
            return
        if not isinstance(node, dict):
            return
        wt = node.get('widgetType', '')
        s = node.get('settings', {})
        # Pattern 1: nested-accordion / accordion with items + child containers
        if wt in ('nested-accordion', 'accordion'):
            items = s.get('items', []) or []
            if not isinstance(items, list):
                items = []
            children = node.get('elements', [])
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                q = strip_html(item.get('item_title', '') or item.get('tab_title', '') or item.get('title', ''))
                q = re.sub(r'^\d+[\.\)]\s*', '', q).strip()
                a = ''
                if i < len(children):
                    # Find first text-editor inside this child container
                    def find_first_text(n):
                        if isinstance(n, dict):
                            if n.get('widgetType') == 'text-editor':
                                return n.get('settings', {}).get('editor', '')
                            for c in n.get('elements', []):
                                r = find_first_text(c)
                                if r: return r
                        elif isinstance(n, list):
                            for c in n:
                                r = find_first_text(c)
                                if r: return r
                        return ''
                    raw = find_first_text(children[i])
                    a = strip_html(raw)
                if q and a and len(q) > 5 and len(a) > 20:
                    faqs.append({'q': q, 'a': a[:600]})
        # Pattern 2: toggle widget — items only (older Elementor)
        elif wt == 'toggle':
            tabs = s.get('tabs', []) or s.get('items', []) or []
            if not isinstance(tabs, list):
                tabs = []
            for item in tabs:
                if not isinstance(item, dict):
                    continue
                q = strip_html(item.get('tab_title', '') or item.get('title', ''))
                a = strip_html(item.get('tab_content', '') or item.get('content', ''))
                if q and a and len(q) > 5 and len(a) > 20:
                    faqs.append({'q': q, 'a': a[:600]})
        # Pattern 3: H3+P pairs inside text-editor
        elif wt == 'text-editor':
            html = s.get('editor', '')
            if html.lower().count('<h3') >= 3:  # only worth parsing if multiple H3s
                pattern = re.compile(
                    r'<h3[^>]*>(.*?)</h3>\s*(<p[^>]*>(.*?)</p>(?:\s*<p[^>]*>(.*?)</p>)?)',
                    re.S | re.I,
                )
                for m in pattern.finditer(html):
                    q = strip_html(m.group(1))
                    a_parts = [strip_html(m.group(3) or '')]
                    if m.group(4):
                        a_parts.append(strip_html(m.group(4)))
                    a = ' '.join(a_parts).strip()
                    if q and a and len(q) > 5 and len(a) > 20 and '?' in q:
                        faqs.append({'q': q, 'a': a[:600]})
        # Recurse
        children = node.get('elements', []) or []
        if isinstance(children, list):
            for c in children:
                visit(c)

    visit(tree)
    # Dedupe by question text
    seen = set()
    uniq = []
    for f in faqs:
        if f['q'] not in seen:
            uniq.append(f)
            seen.add(f['q'])
    return uniq


def has_schema_already(tree: list, marker_prefix: str = SCHEMA_WIDGET_ID_PREFIX) -> bool:
    """Detect if our schema widget was already added to this post."""
    def visit(node):
        if isinstance(node, dict):
            if marker_prefix in (node.get('id', '') or ''):
                return True
            return any(visit(c) for c in node.get('elements', []))
        elif isinstance(node, list):
            return any(visit(n) for n in node)
        return False
    return visit(tree)


def enrich_post_with_schema(post_id: int, dry_run: bool = False) -> dict:
    """Fetch post, extract FAQs from existing structure, add MedicalProcedure +
    FAQPage schema as a new HTML widget at the end. Push + cache clear + IndexNow.

    Returns dict with status info.
    """
    post = get_post(post_id)
    title_raw = post.get('title', {}).get('rendered', '')
    title = re.sub(r'<[^>]+>', '', title_raw).strip()
    link = post.get('link', '')
    elem_str = post['meta']['_elementor_data']
    elem = json.loads(elem_str)

    if has_schema_already(elem):
        return {
            'post_id': post_id,
            'title': title,
            'status': 'skip',
            'reason': 'schema already present',
        }

    # Extract FAQs
    faqs = extract_faqs_from_tree(elem)
    if len(faqs) < 3:
        return {
            'post_id': post_id,
            'title': title,
            'status': 'skip',
            'reason': f'only {len(faqs)} FAQs found (need >=3)',
            'faq_count': len(faqs),
        }

    # Try to extract a meta description for the procedure description
    try:
        live = fetch_live_html(link, mobile=False, timeout=20)
        m = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            live, re.I,
        )
        meta_desc = m.group(1) if m else f'מדריך מקיף בנושא {title}'
    except Exception:
        meta_desc = f'מדריך מקיף בנושא {title}'

    # Build schema
    schema_html = medical_procedure_faq_schema(
        canonical_url=link,
        procedure_name=title,
        procedure_description=meta_desc,
        alternate_names=[title_raw],
        body_locations=[],  # generic, not all posts have body location
        procedure_type='https://schema.org/TherapeuticProcedure',
        faq=faqs,
    )

    # Build new tree — append HTML widget at end
    doc = ElementorDoc(elem)
    cid = f'{SCHEMA_WIDGET_ID_PREFIX}{post_id}c'
    wid = f'{SCHEMA_WIDGET_ID_PREFIX}{post_id}w'
    doc.append_to_root(ElementorDoc.html_section(cid, wid, schema_html))
    new_str = doc.to_string()

    if dry_run:
        return {
            'post_id': post_id,
            'title': title,
            'status': 'dry-run',
            'faq_count': len(faqs),
            'new_chars': len(new_str),
            'old_chars': len(elem_str),
        }

    # Push
    update_elementor(post_id, new_str)
    cache_status = clear_elementor_cache()
    indexnow = submit_indexnow(link)

    # Quick verify
    import time as _t
    _t.sleep(2)
    html = fetch_live_html(link, mobile=False, timeout=20)
    has_faqpage = 'FAQPage' in html
    has_medproc = 'MedicalProcedure' in html

    return {
        'post_id': post_id,
        'title': title,
        'status': 'ok' if (has_faqpage and has_medproc) else 'partial',
        'faq_count': len(faqs),
        'cache_status': cache_status,
        'indexnow': indexnow.get('message', indexnow),
        'verify_faqpage': has_faqpage,
        'verify_medicalprocedure': has_medproc,
    }
