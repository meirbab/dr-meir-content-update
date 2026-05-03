# dr-meir.com SEO Pipeline

Reusable pipeline for the SEO content optimization run. Built and validated on
post 52166 (Quantum RF) on 2026-05-03.

## What's here

```
~/.dr-meir/
├── credentials.env        # WP_SITE / WP_USERNAME / WP_APP_PASSWORD (mode 600)
├── seo_pipeline.py        # CLI entry point: list, analyze, yt, push, verify
├── lib/
│   ├── wp_client.py       # WP REST API: get_post, update_elementor, cache, IndexNow
│   ├── elementor_tree.py  # Elementor JSON tree manipulation (find/insert/append)
│   ├── research.py        # YouTube transcript extraction, post-text analysis
│   ├── schema.py          # JSON-LD MedicalProcedure + FAQPage generators
│   └── pipeline.py        # Phase orchestrator (snapshot, analyze, integrate, push)
├── runs/<post_id>/        # Per-post working dir (one per post)
│   ├── snapshot.json
│   ├── analysis.json
│   ├── current_text.txt
│   ├── transcripts/       # Per-video .txt files
│   ├── transcripts_summary.json
│   ├── transcripts_full.json
│   ├── blocks.json        # AGENT-GENERATED — content additions to apply
│   ├── expected_strings.json   # markers to verify on live page
│   ├── elementor_NEW.json # Integrated JSON before push
│   ├── integrate_log.json
│   └── report.json        # Final push + verification report
├── data/                  # Ad-hoc working files from manual runs
└── backups/               # Auto-created BEFORE each push (post_<id>_elementor_<ts>.json)
```

## The pipeline (per post)

The full pipeline is split between **agent layer** (research, content writing —
needs WebSearch + WebFetch + LLM) and **deterministic CLI** (snapshot, push,
cache clear, IndexNow, verification).

```
Agent steps                           CLI steps
─────────────                         ─────────
                                      analyze     ← snapshot + extract focus keyword
text SERP analysis (Hebrew + English)
                                      yt          ← fetch YouTube transcripts
fact extraction from transcripts
content gap report
write Hebrew content blocks
generate blocks.json + expected_strings.json
                                      push        ← integrate + WP update + cache
                                                    clear + IndexNow + verify
```

## Per-post execution

```bash
# Phase 1 (CLI): snapshot + analyze
python3 seo_pipeline.py analyze --post-id 22866

# Phase 2 (Agent): WebSearch SERP in Hebrew + English, extract competitor facts
# Phase 3 (Agent): WebSearch site:youtube.com for keyword, collect video IDs

# Phase 4 (CLI): fetch transcripts
python3 seo_pipeline.py yt --post-id 22866 --video-ids VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3 VIDEO_ID_4 VIDEO_ID_5 --lang en

# Phase 5 (Agent): combine SERP + transcript facts, find gaps vs current post text,
#                  write Hebrew content blocks. Save to runs/22866/blocks.json
#                  Save markers to runs/22866/expected_strings.json

# Phase 6 (CLI): integrate + push + verify
python3 seo_pipeline.py push --post-id 22866 --dry-run   # preview only
python3 seo_pipeline.py push --post-id 22866             # execute
```

## blocks.json format

Each entry is one operation on the Elementor tree:

```json
[
  {"op": "append",       "target_id": "qrf00004", "html": "<h3>...</h3>"},
  {"op": "replace",      "target_id": "qrf00021", "html": "<h2>...</h2>"},
  {"op": "insert_after", "after_id": "qrf0001e",
                         "container_id": "qrfn0006a", "widget_id": "qrfn0006w",
                         "widget_type": "text-editor",
                         "html": "<h2>...</h2>"},
  {"op": "append_root",  "container_id": "qrfn9999a", "widget_id": "qrfn9999w",
                         "widget_type": "html",
                         "html": "<script type=\"application/ld+json\">...</script>"}
]
```

**Auto-applied by the integrator:** any `<table>` in `html` is wrapped in an
inline `<div style="overflow-x:auto;...">` for mobile. Don't pre-wrap.

## Hard rules (validated on post 52166 — see `~/.claude/projects/.../memory/`)

1. **Always run `clear_elementor_cache()` after pushing.** The DB persists but the
   rendered page won't update. Already wired into `phase_push_and_verify`.
2. **No extra root-level Elementor containers** beyond what the new content needs
   (no style-only, no wrapper-only). It breaks the footer/form on that one page.
3. **No CSS class wrappers around content.** Inline styles only, scoped to specific
   elements (e.g. table overflow).
4. **Never paste competitor text or transcript text verbatim.** Extract facts,
   write original Hebrew with citations.
5. **Match the structural pattern of working posts.** When in doubt, diff the
   target post's HTML against another working post's HTML.

## Batch run

When ready to run on many posts:

```python
# batch_run.py (write this when planning a batch)
from seo_pipeline import cmd_analyze, cmd_yt, cmd_push
# Loop with appropriate sleep between posts to avoid rate limits.
# Save errors to runs/_batch_errors.log; continue on failure.
```

The pipeline is designed so that each post's `runs/<id>/` is isolated — a failure
on one post doesn't affect others, and any post can be resumed by re-running the
relevant phase.

## Recovering a broken post

```bash
# Find the latest backup
ls -t backups/post_<id>_elementor_*.json | head -1

# Restore (one-liner)
python3 -c "
import sys; sys.path.insert(0,'lib')
from wp_client import update_elementor, clear_elementor_cache
update_elementor(<id>, open('backups/post_<id>_elementor_<ts>.json').read())
clear_elementor_cache()
"
```

## Credentials rotation

`credentials.env` was exposed in chat during the initial setup on 2026-05-03 —
**rotate before running any further posts.** The Application Password was bound
to user `2ofnu4`. To create a new one: `wp-admin → Users → Profile → Application
Passwords`. Then update `WP_APP_PASSWORD` in `~/.dr-meir/credentials.env` and
restart any pipeline runs.
