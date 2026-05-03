#!/usr/bin/env python3
"""
Master CLI for the dr-meir.com SEO optimization pipeline.

Usage:
  # List all posts (helps decide what to optimize)
  python3 seo_pipeline.py list

  # Snapshot + analyze one post (no writes — read-only)
  python3 seo_pipeline.py analyze --post-id 52166

  # Fetch YouTube transcripts for one post (provide video IDs)
  python3 seo_pipeline.py yt --post-id 52166 --video-ids 7yV_cKdRpaI Skb7cX2GCjA Orprrjk3A30

  # Apply pre-written blocks (loaded from runs/<id>/blocks.py) and push
  python3 seo_pipeline.py push --post-id 52166

  # Verify a post is OK in production
  python3 seo_pipeline.py verify --post-id 52166

The script does NOT do agent-side work (text SERP, content writing, fact extraction
from transcripts) — those steps happen at the agent layer where WebSearch, WebFetch,
and content generation live. This CLI exposes the deterministic parts: snapshot,
list, transcripts, integrate, push, verify.
"""
import argparse
import json
import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent / 'lib'
sys.path.insert(0, str(LIB_DIR))

from wp_client import list_all_posts, get_post, submit_indexnow, get_indexnow_log
from pipeline import (
    phase_snapshot, phase_analyze, phase_research_yt,
    phase_integrate, phase_push_and_verify, run_dir
)


def cmd_list(args):
    posts = list_all_posts(status=args.status)
    print(f'Total {args.status} posts: {len(posts)}')
    print()
    print(f'{"ID":<7} {"Date":<12} {"Status":<10} Title  /  URL')
    print('-' * 100)
    for p in posts:
        print(f'{p["id"]:<7} {p.get("date","")[:10]:<12} {p.get("status",""):<10} '
              f'{p.get("title",{}).get("rendered","")[:60]}')
        print(f'        {p.get("link","")}')


def cmd_analyze(args):
    p = phase_snapshot(args.post_id)
    a = phase_analyze(args.post_id, p)
    rd = run_dir(args.post_id)
    print(f'\nAnalysis saved to: {rd}/analysis.json')
    print(f'  title: {a["title"]}')
    print(f'  slug: {a["slug"]}')
    print(f'  current word count: {a["current_word_count"]}')
    print(f'  containers: {a["root_container_count"]}')
    if a['meta_description']:
        print(f'  meta description: {a["meta_description"][:100]}')


def cmd_yt(args):
    summary = phase_research_yt(args.post_id, args.video_ids, language_pref=args.lang)
    print(f'\nTranscripts saved to: {run_dir(args.post_id)}/transcripts/')
    print(f'  Got {summary["succeeded"]}/{summary["attempted"]} videos')
    print(f'  Total words: {summary["total_words"]:,}')


def cmd_push(args):
    rd = run_dir(args.post_id)
    blocks_file = rd / 'blocks.json'
    if not blocks_file.exists():
        print(f'ERROR: {blocks_file} missing.', file=sys.stderr)
        print(f'Create it with a JSON array of block ops; see lib/pipeline.py:phase_integrate doc.', file=sys.stderr)
        sys.exit(1)
    blocks = json.loads(blocks_file.read_text(encoding='utf-8'))

    expected = []
    expected_file = rd / 'expected_strings.json'
    if expected_file.exists():
        expected = json.loads(expected_file.read_text(encoding='utf-8'))

    phase_integrate(args.post_id, blocks)
    if args.dry_run:
        print(f'\nDry run — integrated JSON saved to {rd}/elementor_NEW.json but NOT pushed.')
        return
    report = phase_push_and_verify(args.post_id, expected_strings=expected)
    if not report.get('all_verified', True):
        print('\nWARNING: not all expected strings verified in live HTML.')
        sys.exit(2)


def cmd_verify(args):
    post = get_post(args.post_id)
    link = post.get('link', '')
    print(f'Post {args.post_id}: {post["title"]["rendered"]}')
    print(f'  link: {link}')
    print(f'  modified: {post.get("modified","")}')
    print(f'  status: {post.get("status","")}')
    log = get_indexnow_log()
    matches = [e for e in log if link.replace('https://','').replace('http://','') in e.get('url','')]
    if matches:
        last = matches[0]
        print(f'  last IndexNow: {last.get("timeFormatted","")} status={last.get("status","")}')


def main():
    ap = argparse.ArgumentParser(description='dr-meir.com SEO pipeline CLI')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('list', help='List posts')
    p.add_argument('--status', default='publish')
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('analyze', help='Snapshot + analyze one post (read-only)')
    p.add_argument('--post-id', type=int, required=True)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser('yt', help='Fetch YouTube transcripts for a post')
    p.add_argument('--post-id', type=int, required=True)
    p.add_argument('--video-ids', nargs='+', required=True)
    p.add_argument('--lang', default='en', help='preferred language (he or en)')
    p.set_defaults(func=cmd_yt)

    p = sub.add_parser('push', help='Apply blocks.json and push to live')
    p.add_argument('--post-id', type=int, required=True)
    p.add_argument('--dry-run', action='store_true')
    p.set_defaults(func=cmd_push)

    p = sub.add_parser('verify', help='Show post status + last IndexNow result')
    p.add_argument('--post-id', type=int, required=True)
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
