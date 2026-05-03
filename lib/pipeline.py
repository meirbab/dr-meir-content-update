"""
Pipeline orchestrator for per-post optimization.

The pipeline has explicit phases and saves intermediate state to disk so a
batch run can be resumed if interrupted, and so each post's content additions
are reviewable before pushing.

Phases (per post):
  1. snapshot      - Backup current post state to backups/
  2. analyze       - Extract focus keyword, list current sections, current text
  3. research_serp - (PARTIAL — needs WebSearch from agent layer; this saves the
                     scaffolding and reads back results provided as JSON files)
  4. research_yt   - Auto: search YouTube, transcribe top 5, save facts
  5. gap_report    - Combine SERP + YouTube facts, compare against current post,
                     output a gap report ready for content writing
  6. write         - HUMAN STEP: write Hebrew content blocks against the gap
                     report (or load pre-written blocks from runs/<post_id>/blocks.py)
  7. integrate     - Apply blocks to Elementor JSON
  8. push          - update_elementor() + clear_elementor_cache()
  9. submit        - submit_indexnow() + verify live page
  10. report       - Save before/after stats to runs/<post_id>/report.json

Each phase reads its inputs from runs/<post_id>/ and writes its outputs there.
"""
import json
import time
from datetime import datetime
from pathlib import Path

from wp_client import (
    get_post, list_all_posts, update_elementor, clear_elementor_cache,
    submit_indexnow, fetch_live_html
)
from elementor_tree import ElementorDoc
from research import fetch_transcripts, extract_video_ids_from_search, extract_post_text


RUNS_DIR = Path('/Users/meirbabaev/.dr-meir/runs')
BACKUPS_DIR = Path('/Users/meirbabaev/.dr-meir/backups')


def run_dir(post_id: int) -> Path:
    d = RUNS_DIR / str(post_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def phase_snapshot(post_id: int) -> dict:
    """Backup current post state. Always run BEFORE any changes."""
    rd = run_dir(post_id)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    post = get_post(post_id)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bk = BACKUPS_DIR / f'post_{post_id}_full_{ts}.json'
    bk.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding='utf-8')
    elem = post.get('meta', {}).get('_elementor_data', '')
    bk_elem = BACKUPS_DIR / f'post_{post_id}_elementor_{ts}.json'
    bk_elem.write_text(elem, encoding='utf-8')
    (rd / 'snapshot.json').write_text(json.dumps({
        'post_id': post_id,
        'timestamp': ts,
        'backup_full': str(bk),
        'backup_elementor': str(bk_elem),
        'title': post.get('title', {}).get('rendered', ''),
        'slug': post.get('slug', ''),
        'link': post.get('link', ''),
        'modified': post.get('modified', ''),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[{post_id}] snapshot OK -> {bk_elem}')
    return post


def phase_analyze(post_id: int, post: dict = None) -> dict:
    """Extract focus keyword candidates, current text, current section list."""
    rd = run_dir(post_id)
    if post is None:
        post = get_post(post_id)
    title = post.get('title', {}).get('rendered', '')
    slug = post.get('slug', '')
    elem_str = post.get('meta', {}).get('_elementor_data', '')
    doc = ElementorDoc.from_string(elem_str)
    current_text = extract_post_text(doc.tree)

    # Fetch live to get meta description (Rank Math doesn't expose it via REST)
    link = post.get('link', '')
    try:
        html = fetch_live_html(link, mobile=False)
        import re
        meta_desc = ''
        m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if m: meta_desc = m.group(1)
    except Exception:
        meta_desc = ''

    analysis = {
        'post_id': post_id,
        'title': title,
        'slug': slug,
        'meta_description': meta_desc,
        'link': link,
        'current_text_chars': len(current_text),
        'current_word_count': len(current_text.split()),
        'root_container_count': len(doc.tree),
        'root_ids': doc.root_ids(),
    }
    (rd / 'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
    (rd / 'current_text.txt').write_text(current_text, encoding='utf-8')
    print(f'[{post_id}] analyze OK - {len(current_text)} chars, {len(doc.tree)} containers')
    return analysis


def phase_research_yt(post_id: int, video_ids: list, language_pref: str = 'en') -> dict:
    """Fetch transcripts for the given list of YouTube video IDs."""
    rd = run_dir(post_id)
    out_dir = rd / 'transcripts'
    transcripts = fetch_transcripts(video_ids, language_pref=language_pref, out_dir=str(out_dir))
    summary = {
        'post_id': post_id,
        'attempted': len(video_ids),
        'succeeded': len(transcripts),
        'total_words': sum(t['word_count'] for t in transcripts.values()),
        'video_ids': list(transcripts.keys()),
    }
    (rd / 'transcripts_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (rd / 'transcripts_full.json').write_text(json.dumps(transcripts, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[{post_id}] research_yt OK - {len(transcripts)}/{len(video_ids)} videos, {summary["total_words"]} words')
    return summary


def phase_integrate(post_id: int, blocks: list) -> str:
    """Apply a list of block operations to the Elementor tree.

    Each block is a dict like:
      {'op': 'append', 'target_id': 'qrf00004', 'html': '...'}
      {'op': 'replace', 'target_id': 'qrf00021', 'html': '...'}
      {'op': 'insert_after', 'after_id': 'qrf0001e',
       'container_id': 'qrfn0006a', 'widget_id': 'qrfn0006w', 'html': '...'}
      {'op': 'append_root', 'container_id': 'qrfn9999a', 'widget_id': 'qrfn9999w',
       'html': '...', 'widget_type': 'html'}

    Tables in HTML are auto-wrapped with overflow-x:auto for mobile.
    """
    rd = run_dir(post_id)
    post = get_post(post_id)
    elem_str = post['meta']['_elementor_data']
    doc = ElementorDoc.from_string(elem_str)

    applied = []
    for b in blocks:
        op = b.get('op')
        html = b.get('html', '')
        if html and '<table' in html.lower():
            html = ElementorDoc.wrap_table_for_mobile(html)
        if op == 'append':
            ok = doc.append_to_widget(b['target_id'], html)
            applied.append({'op': op, 'target': b['target_id'], 'ok': ok})
        elif op == 'replace':
            ok = doc.replace_widget_content(b['target_id'], html)
            applied.append({'op': op, 'target': b['target_id'], 'ok': ok})
        elif op == 'insert_after':
            wt = b.get('widget_type', 'text-editor')
            if wt == 'text-editor':
                container = ElementorDoc.text_section(b['container_id'], b['widget_id'], html)
            else:
                container = ElementorDoc.html_section(b['container_id'], b['widget_id'], html)
            ok = doc.insert_after_container(b['after_id'], container)
            applied.append({'op': op, 'after': b['after_id'], 'new_id': b['container_id'], 'ok': ok})
        elif op == 'append_root':
            wt = b.get('widget_type', 'text-editor')
            if wt == 'text-editor':
                container = ElementorDoc.text_section(b['container_id'], b['widget_id'], html)
            else:
                container = ElementorDoc.html_section(b['container_id'], b['widget_id'], html)
            doc.append_to_root(container)
            applied.append({'op': op, 'new_id': b['container_id'], 'ok': True})
        else:
            applied.append({'op': op, 'ok': False, 'reason': 'unknown op'})

    new_str = doc.to_string()
    (rd / 'integrate_log.json').write_text(json.dumps(applied, ensure_ascii=False, indent=2), encoding='utf-8')
    (rd / 'elementor_NEW.json').write_text(new_str, encoding='utf-8')
    print(f'[{post_id}] integrate OK - {len(applied)} ops, '
          f'{sum(1 for a in applied if a.get("ok"))} succeeded')
    return new_str


def phase_push_and_verify(post_id: int, expected_strings: list = None) -> dict:
    """Push the integrated Elementor JSON, clear cache, verify rendered output."""
    rd = run_dir(post_id)
    new_str = (rd / 'elementor_NEW.json').read_text(encoding='utf-8')
    update_elementor(post_id, new_str)
    print(f'[{post_id}] push OK')
    status = clear_elementor_cache()
    print(f'[{post_id}] elementor cache clear: HTTP {status}')

    post = get_post(post_id)
    link = post['link']
    submit = submit_indexnow(link)
    print(f'[{post_id}] indexnow: {submit.get("message", submit)}')

    time.sleep(3)
    html = fetch_live_html(link, mobile=True)
    verification = {}
    if expected_strings:
        for s in expected_strings:
            verification[s] = (s in html)
        all_ok = all(verification.values())
    else:
        all_ok = True
    report = {
        'post_id': post_id,
        'link': link,
        'modified': post.get('modified', ''),
        'pushed_chars': len(new_str),
        'live_html_chars': len(html),
        'verification': verification,
        'all_verified': all_ok,
        'indexnow': submit,
    }
    (rd / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[{post_id}] report saved. verification: {"OK" if all_ok else "PARTIAL — review"}')
    return report
