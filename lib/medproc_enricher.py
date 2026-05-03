"""
MedicalProcedure-only enricher for posts that lack FAQ accordion structure.
For posts skipped by schema_enricher, adds MedicalProcedure schema only.
This still gives SEO benefit (rich result eligibility, AI citation hint)
without needing real Q&A structure in the page.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wp_client import (
    get_post, update_elementor, clear_elementor_cache,
    submit_indexnow, fetch_live_html, _request,
)
from elementor_tree import ElementorDoc

SCHEMA_MARKER_PREFIX = 'mpauto'


def has_marker(tree, prefix=SCHEMA_MARKER_PREFIX):
    def visit(n):
        if isinstance(n, dict):
            if prefix in (n.get('id', '') or ''):
                return True
            return any(visit(c) for c in n.get('elements', []))
        elif isinstance(n, list):
            return any(visit(x) for x in n)
        return False
    return visit(tree)


def build_medical_procedure_schema(canonical_url: str, name: str, description: str) -> str:
    """Just MedicalProcedure (no FAQPage) for posts without Q&A structure."""
    schema = {
        '@context': 'https://schema.org',
        '@type': 'MedicalProcedure',
        '@id': f'{canonical_url}#procedure',
        'name': name,
        'description': description,
        'procedureType': 'https://schema.org/TherapeuticProcedure',
        'url': canonical_url,
    }
    return ('<script type="application/ld+json">'
            + json.dumps(schema, ensure_ascii=False)
            + '</script>')


def enrich_post_medproc_only(post_id: int, dry_run: bool = False) -> dict:
    """Add only MedicalProcedure schema to posts without FAQ structure."""
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

    # Skip if already has any of our schemas
    if has_marker(elem, 'mpauto') or has_marker(elem, 'schauto'):
        return {'post_id': post_id, 'title': title, 'status': 'skip',
                'reason': 'schema already present'}

    # Pull description from meta_description on live page (Rank Math output)
    try:
        live = fetch_live_html(link, mobile=False, timeout=30)
        m = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            live, re.I,
        )
        meta_desc = m.group(1) if m else f'מדריך מקיף בנושא {title}'
    except Exception:
        meta_desc = f'מדריך מקיף בנושא {title}'

    schema_html = build_medical_procedure_schema(link, title, meta_desc)

    doc = ElementorDoc(elem)
    cid = f'{SCHEMA_MARKER_PREFIX}{post_id}c'
    wid = f'{SCHEMA_MARKER_PREFIX}{post_id}w'
    doc.append_to_root(ElementorDoc.html_section(cid, wid, schema_html))
    new_str = doc.to_string()

    if dry_run:
        return {'post_id': post_id, 'title': title, 'status': 'dry-run'}

    update_elementor(post_id, new_str)
    clear_elementor_cache()
    submit_indexnow(link)
    time.sleep(2)
    try:
        html = fetch_live_html(link, mobile=False, timeout=30)
        ok = 'MedicalProcedure' in html
    except Exception:
        ok = None

    return {
        'post_id': post_id,
        'title': title,
        'status': 'ok' if ok else 'partial',
        'verify_medicalprocedure': ok,
    }
