#!/usr/bin/env python3
"""
Run schema enricher across ALL remaining posts in dr-meir.com inventory.
Reads existing log, processes only unfinished posts, appends to log.
Designed to be run unattended until completion.

Outputs:
  - batch/schema_enricher_log.json (cumulative)
  - stdout: progress per post
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, '/Users/meirbabaev/.dr-meir/lib')
from schema_enricher import enrich_post_with_schema

INVENTORY = Path('/Users/meirbabaev/.dr-meir/batch/_all_posts.json')
LOG = Path('/Users/meirbabaev/.dr-meir/batch/schema_enricher_log.json')
SLEEP_BETWEEN = 1.5  # seconds between posts
MAX_RETRIES = 1  # retry transient errors once

# Already-handled (full pipeline manual)
MANUAL_DONE = {52166, 22866, 51619, 51316}


def load_log():
    if LOG.exists():
        return json.load(LOG.open())
    return {'results': [], 'errors': []}


def save_log(log):
    with LOG.open('w') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def main():
    posts = json.load(INVENTORY.open())
    log = load_log()
    done_ids = MANUAL_DONE | {r['post_id'] for r in log.get('results', [])}
    # Exclude erred posts so they get retried
    erred_ids = {e['post_id'] for e in log.get('errors', [])}
    # Remove erred from log so they retry cleanly
    log['errors'] = []

    remaining = [p for p in posts if p['id'] not in done_ids or p['id'] in erred_ids]
    print(f'Total inventory: {len(posts)}')
    print(f'Already done: {len(done_ids)} ({len(MANUAL_DONE)} manual + '
          f'{len(done_ids) - len(MANUAL_DONE)} via enricher)')
    print(f'Erred (will retry): {len(erred_ids)}')
    print(f'To process: {len(remaining)}')
    print()
    print('Starting processing... (each post ~5-7 seconds)')
    print()

    for i, p in enumerate(remaining):
        pid = p['id']
        title = p['title']['rendered'][:50]
        try:
            r = enrich_post_with_schema(pid, dry_run=False)
            log['results'].append(r)
            status = r['status']
            marker = '+' if status == 'ok' else ('-' if status == 'skip' else '?')
            faq_n = r.get('faq_count', '-')
            print(f'  {marker} [{i+1:>3}/{len(remaining)}] {pid:>6} faqs={faq_n:>3} {status:<10} {title}',
                  flush=True)
        except Exception as e:
            log['errors'].append({
                'post_id': pid,
                'error': str(e)[:300],
                'type': type(e).__name__,
            })
            print(f'  X [{i+1:>3}/{len(remaining)}] {pid:>6} ERROR {type(e).__name__}: {str(e)[:80]}',
                  flush=True)
        # Save log periodically (every 10 posts) to checkpoint
        if (i + 1) % 10 == 0:
            save_log(log)
        time.sleep(SLEEP_BETWEEN)

    # Final save
    save_log(log)

    # Summary
    print()
    print('=== FINAL SUMMARY ===')
    ok = sum(1 for r in log['results'] if r.get('status') == 'ok')
    skip = sum(1 for r in log['results'] if r.get('status') == 'skip')
    partial = sum(1 for r in log['results'] if r.get('status') == 'partial')
    err = len(log['errors'])
    print(f'  OK:      {ok}')
    print(f'  Skip:    {skip} (no FAQs detected — may need manual review)')
    print(f'  Partial: {partial}')
    print(f'  Errors:  {err}')
    print(f'  Total in log: {len(log["results"]) + err}')
    print(f'  Manual full-pipeline: {len(MANUAL_DONE)}')
    print(f'  Grand total covered: {len(log["results"]) + err + len(MANUAL_DONE)}')


if __name__ == '__main__':
    main()
