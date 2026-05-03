---
name: dr-meir-content-update
description: SEO content optimization for dr-meir.com WordPress posts (Elementor + Rank Math + WP Rocket). Bilingual SERP research (Hebrew + English top 5), YouTube transcript fact extraction (top 5 by primary keyword), original Hebrew content synthesis, MedicalProcedure + FAQPage schema injection, mobile-safe edits. Use when user says "optimize dr-meir post", "run dr-meir pipeline", "update post 52166", "batch optimize dr-meir.com", "expand quantum rf post", or wants to run the SEO pipeline on any dr-meir.com post.
---

# dr-meir.com Content Update Skill

End-to-end pipeline for optimizing existing posts on dr-meir.com (Dr. Meir Babaev's dermatology + aesthetic medicine clinic, RTL Hebrew). Validated on post 52166 (Quantum RF) on 2026-05-03 — added 3,000+ words, 5 new sections, MedicalProcedure + FAQPage schema, kept mobile responsiveness intact.

## When to invoke this skill

- "תפעיל את ה-pipeline על פוסט X" / "Run dr-meir pipeline on post X"
- "תרחיב את הפוסט הזה" with a dr-meir.com URL
- "Run the batch on all 271 posts"
- "Optimize this post for Google + AI Overviews" with a dr-meir.com link
- Any request mentioning dr-meir.com that involves content editing or SEO

## When NOT to invoke

- Generic "improve my SEO" without specific dr-meir.com posts
- New post creation (this skill is for expanding existing posts)
- Theme/site-wide changes (use a different approach)
- Anything outside dr-meir.com

---

## Site profile (memorize)

- **WordPress** self-hosted on nginx, RTL Hebrew
- **Stack:** Hello Elementor theme, Elementor + Elementor Pro, Rank Math SEO, WP Rocket, WP-2FA
- **Login user:** `2ofnu4` (NOT `admin` — public author slug is `admin` due to Rank Math obfuscation; the actual user_login is `2ofnu4`. ID=1, email meirbab@gmail.com)
- **Credentials:** `~/.dr-meir/credentials.env` (mode 600). Format:
  ```
  WP_SITE="https://dr-meir.com"
  WP_USERNAME="2ofnu4"
  WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"
  ```
- **Current scale:** ~271 published posts (2026-05-03)
- **Clinic:** הרוקמים 26, חולון, מתחם עזריאלי בניין B קומה 4. Phone 052-445-3107
- **Existing schema:** Rank Math auto-generates Article + WebPage + Person + Organization + BreadcrumbList + Place + ImageObject. We ADD MedicalProcedure + FAQPage.

## CRITICAL: surface-specific schema injection rules (validated 2026-05-03)

These are NOT interchangeable — putting schema in the wrong place either does nothing OR breaks the page visibly:

| Surface | Where it lives | Schema injection method | Notes |
|---|---|---|---|
| **Posts** | `meta._elementor_data` | Add `<script type="application/ld+json">` inside an Elementor `html` widget at end of post | `<script>` is preserved and rendered as raw HTML by Elementor html widgets — Google reads it. |
| **Pages** | `meta._elementor_data` | Same as posts | Same — Elementor html widget rendering preserves `<script>`. |
| **Categories** | `description` field (text only, NOT Elementor) | **DO NOT inject `<script>` here** — WordPress renders the description as visible text on the category archive page, so `<script>` literally appears as raw JSON to readers. | Use Rank Math admin (SEO → Titles & Meta → Categories → Schema Type) OR a `wp_head` filter. NOT REST. |

**The category bug** I made on 2026-05-03: I appended `<!-- claude-schema-injected --><script type="application/ld+json">{...}</script>` to category description, thinking it would be rendered as schema. Instead, the JSON appeared as visible text covering the page (CollectionPage/ItemList JSON dumped inline), broke the layout, hid the menu, and tanked the look on `/dermatology/`, `/liposuction/` etc. Took the user pointing out the visible JSON to identify it. Recovery: strip everything after the marker comment, push back via PATCH on `/wp/v2/categories/{id}` with `description` field. Always test with a single category in dry-run before batching.

## Repo + tools location

```
~/.dr-meir/
├── credentials.env            # WP_SITE / WP_USERNAME / WP_APP_PASSWORD (mode 600)
├── seo_pipeline.py            # CLI: list, analyze, yt, push, verify
├── lib/
│   ├── wp_client.py           # REST: get_post, update_elementor, clear_elementor_cache, submit_indexnow
│   ├── elementor_tree.py      # ElementorDoc — find_widget, append_to_widget, insert_after_container, text_section, wrap_table_for_mobile
│   ├── research.py            # fetch_transcripts (youtube-transcript-api), extract_post_text
│   ├── schema.py              # medical_procedure_faq_schema, faq_from_html_h3_pairs
│   └── pipeline.py            # phase_snapshot, phase_analyze, phase_research_yt, phase_integrate, phase_push_and_verify
├── runs/<post_id>/            # Per-post working dir
└── backups/                   # Auto-created before every push
```

## Required Python package

```bash
pip3 install --user youtube-transcript-api
# Already installed at /Users/meirbabaev/Library/Python/3.9/site-packages
# On a fresh install: pip3 install --user youtube-transcript-api
```

---

## The pipeline (per post)

The pipeline is split between **agent layer** (research, content writing — needs WebSearch + WebFetch + LLM) and **deterministic CLI** (snapshot, push, cache clear, IndexNow, verification). Always run them in order.

### Phase 1 — Snapshot + Analyze (CLI)

```bash
python3 ~/.dr-meir/seo_pipeline.py analyze --post-id <ID>
```

What it does:
- Backs up current `_elementor_data` to `~/.dr-meir/backups/post_<id>_elementor_<timestamp>.json` (rollback safety)
- Saves analysis to `~/.dr-meir/runs/<id>/analysis.json` (title, slug, link, current word count, container count, root IDs)
- Saves cleaned current text to `runs/<id>/current_text.txt` (used in gap analysis)

Read the output before continuing. If word count is already > 3000 and the post has FAQPage + MedicalProcedure schema, it may already be optimized — skip or just refresh.

### Phase 2 — Bilingual SERP analysis (Agent)

For each post, extract the **focus keyword** from:
1. Post title (top priority)
2. Meta description (read from `analysis.json` → `meta_description`)
3. URL slug
4. Manual override if obvious (rare)

Then run THREE WebSearch calls **in parallel**:
1. `<focus keyword in Hebrew>` (e.g., "שאיבת שומן Quantum RF")
2. `<focus keyword in English>` (e.g., "Quantum RF liposuction")
3. One of these auxiliary queries to capture comparative content:
   - `<keyword> vs <known competitor technology>` for procedure topics
   - `<keyword> cost / מחיר` for procedure topics with cost intent
   - `<keyword> reviews / חוות דעת` for evaluative intent

For each language, **WebFetch the top 3-5 organic results** in parallel. Extract CONCRETE FACTS only (numbers, percentages, mechanism details, named technology comparisons, side effects, contraindications, FDA/regulatory status, recovery timelines). Reject any marketing fluff.

**Hebrew SERP gotcha:** for many medical/aesthetic procedure terms, the Hebrew top 5 will be sparse on the actual topic (e.g., "Quantum RF" Hebrew SERP is dominated by BodyTite/Renuvion content). **This is itself useful intel** — it means the Hebrew SERP is uncovered for that exact keyword and the post can own it. Tell the user.

### Phase 3 — YouTube transcript pass (Agent + CLI)

This step adds facts that doctor-on-camera explanations contain but written articles omit (especially mechanism details and comparative numbers).

**Agent step:** WebSearch with `site:youtube.com` filter:
1. `<focus keyword in English> site:youtube.com`
2. `<focus keyword in Hebrew> site:youtube.com`
3. `<brand-name + keyword> site:youtube.com` (e.g., "InMode Quantum RF body contouring site:youtube.com")

Pick the **top 5 most relevant videos in English + 2-5 Hebrew videos** (Hebrew often has fewer relevant results — that's fine). Ranking signal:
- Doctor / clinic channels > generic
- Educational explainers > marketing demos
- Recency (last 12-18 months for procedure/tech topics)
- Look for "explained", "demo", "comparison", "before/after" in titles

Extract video IDs from URLs (the 11-char ID after `?v=` or `/shorts/`).

**CLI step:**
```bash
python3 ~/.dr-meir/seo_pipeline.py yt --post-id <ID> --video-ids ID1 ID2 ID3 ID4 ID5 [HEB_ID1 HEB_ID2] --lang en
```

This uses `youtube-transcript-api` which:
- Fetches captions (manual or auto-generated) directly from YouTube
- No video download, no Whisper, ~3s per video
- Handles Hebrew + English transparently

**Expected hit rate:** 50-70% of videos return transcripts. The rest have captions disabled (especially Hebrew clinic channels — they often disable captions). Don't fail; work with what you get. Output is in `runs/<id>/transcripts_full.json` (per-video text) and `transcripts_summary.json` (counts).

### Phase 4 — Gap analysis + content writing (Agent)

Read:
- `runs/<id>/current_text.txt` (what the post already covers)
- `runs/<id>/transcripts_full.json` (video facts)
- Your in-memory SERP fact extracts from Phase 2

Build a **gap report** (mental, not a file): facts present in SERP/transcripts but NOT in current_text.txt. Specifically hunt for:
- **Mechanism details** that doctors explain on camera but written articles skip
- **Specific quantitative outcomes** (e.g., "up to 40% skin contraction", "25% fat reduction in single session")
- **Named technology comparisons** (e.g., Quantum RF vs BodyTite vs Renuvion vs FaceTite vs CoolSculpting vs SculpSure)
- **Patient case profiles** (33yo female, mother, submental fullness)
- **Combination protocols** (X + Y in same visit)
- **Realistic-expectation tiers** by severity
- **Recovery specifics** (specific times for return to office work / exercise / full activity)
- **Safety / contraindications / side effects** (CRITICAL for medical YMYL E-E-A-T)
- **Cost factors** (NOT specific prices — factors that influence pricing)
- **Pre-treatment preparation** + **post-treatment care**

Now WRITE the new content blocks **in original Hebrew** (not paraphrased copy — original synthesis). Aim for:
- 5-8 new H2 sections OR substantial expansions
- Total post target: ~3,000+ words (up from typical 1,000-1,500)
- Each section answers a specific user question / search intent
- Liberal use of `<ul>`, `<ol>`, `<table>` for AI-Overview citation friendliness
- Bold key facts with `<strong>`
- Always include a safety/risks/contraindications section for medical posts
- Always end with a comparison-vs-named-competitors section (captures secondary keyword traffic)

**Required: also write FAQ schema input.** From the FAQ section of the post, extract Q&A pairs. We'll feed them to `schema.faq_from_html_h3_pairs()` to auto-generate FAQPage schema.

### Phase 5 — Generate `blocks.json` + `expected_strings.json` (Agent)

Output two JSON files in `runs/<id>/`:

**blocks.json** — array of operations on the Elementor tree:
```json
[
  {"op": "append", "target_id": "qrf00004", "html": "<h3>...</h3>"},
  {"op": "replace", "target_id": "qrf00021", "html": "<h2>שאלות נפוצות</h2>..."},
  {"op": "insert_after",
   "after_id": "qrf0001e",
   "container_id": "qrfn0006a",
   "widget_id": "qrfn0006w",
   "widget_type": "text-editor",
   "html": "<h2>...</h2>"},
  {"op": "append_root",
   "container_id": "qrfn9999a",
   "widget_id": "qrfn9999w",
   "widget_type": "html",
   "html": "<script type=\"application/ld+json\">...</script>"}
]
```

Operation types:
- `append` — append HTML to existing widget's editor field (idempotent)
- `replace` — replace widget content entirely
- `insert_after` — insert a new top-level container after target (creates new container + widget)
- `append_root` — append a new top-level container at very end (used for schema)

**Container/widget IDs:** use `qrfn` prefix (or other site-relevant prefix) + sequential — e.g., `qrfn0001a` (container) and `qrfn0001w` (widget). NEVER reuse IDs that already exist on the post.

**widget_type:**
- `text-editor` for HTML content (default)
- `html` for raw HTML, used for JSON-LD schema injection

**Tables auto-wrap:** if HTML contains `<table>`, the integrator wraps each table in `<div style="overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch;margin:1em 0;">…</div>` automatically — DON'T pre-wrap.

**expected_strings.json** — array of strings to grep for in the live HTML after push:
```json
[
  "InMode IgniteRF",
  "QuantumRF 10",
  "25% הפחתת שומן",
  "MedicalProcedure",
  "FAQPage"
]
```
Pick markers that uniquely identify each new block. The verifier checks each is present in the rendered page; if any are missing, the run is flagged.

### Phase 6 — Integrate + push + cache + IndexNow + verify (CLI)

```bash
# Preview only (writes runs/<id>/elementor_NEW.json but doesn't push)
python3 ~/.dr-meir/seo_pipeline.py push --post-id <ID> --dry-run

# Execute
python3 ~/.dr-meir/seo_pipeline.py push --post-id <ID>
```

What it does (in order):
1. Loads `runs/<id>/blocks.json`
2. Builds new `_elementor_data` JSON (auto-wraps tables for mobile)
3. `POST /wp-json/wp/v2/posts/<id>` with `meta._elementor_data` + `_elementor_css=""` (clears the per-post CSS cache to force regen)
4. **`DELETE /wp-json/elementor/v1/cache`** — REQUIRED. Without this Elementor keeps serving the cached render and the new widgets won't appear.
5. `POST /wp-json/rankmath/v1/in/submitUrls` with `{"urls": "https://..."}` — Rank Math IndexNow ping (pushes to Bing/Yandex)
6. Sleep 3s, fetch live HTML with mobile UA + cache-busting query param
7. Check each `expected_strings.json` marker is in the live HTML
8. Save `runs/<id>/report.json` with verification results

If verification fails (some markers missing): re-run cache clear + verify, OR investigate why content isn't rendering.

---

## Internal linking (validated 2026-05-03 — 232/271 posts linked safely)

Internal linking distributes PageRank, builds topical authority, and reduces bounce rate. Rules:

### Build the keyword corpus

Loaded once at start of batch:

```python
from internal_linker import build_corpus
corpus = build_corpus(posts, categories)  # returns sorted by keyword length DESC
```

Sources:
- **Each post's title** → links to that post's URL
- **Each category name** → links to the category archive URL
- Skip categories with <5 posts (not enough authority to be worth linking)
- **Generic blocklist:** "טיפול", "עור", "פנים", "גוף", "בטן", "אסתטיקה", "דר מאיר" (too short/generic — would pollute every post)
- HTML-decode entities in titles (`&quot;`, `&#039;`, `&#8211;` etc) before adding to corpus

### Replacement rules — what NOT to touch

`internal_linker.insert_links()` enforces these. Don't bypass them:

1. **Inside HTML tags** (`<tag attr="..">`) — never replace text inside an attribute value
2. **Inside existing `<a>...</a>`** — never wrap a second link around an existing one (= nested anchors, breaks HTML)
3. **Inside `<h1>...<h6>`** — anchors in headings look spammy and hurt UX
4. **Self-links** — never link a post to itself (`current_url` and `current_id` checks)
5. **Repeat anchors on same page** — `used_anchors` set per page, only first occurrence of each keyword gets linked
6. **Density limit:** `max_links=5` per page is the validated default. More than 5 → looks spammy
7. **Idempotency:** the linker isn't fully idempotent (no marker tag) — re-running on the same post can ADD MORE links. Filter out already-processed post IDs from your queue when resuming.

### Longest-match-first strategy

Corpus is sorted by keyword length DESC so specific terms win:
- "שאיבת שומן Quantum RF" (long) → links to specific post
- "שאיבת שומן" (short) → links to category archive

This means specific posts get the focused anchor traffic while generic terms route to category pages. Without DESC sort, "שאיבת שומן" would win every time and specific posts never get internal links.

### Where the linker writes

The linker scans **only `text-editor` widgets** inside Elementor data. It modifies `widget.settings.editor` HTML. It does NOT touch:
- `heading` widgets (don't link inside H1/H2)
- `html` widgets (might be schema, custom HTML, or templates)
- `posts` / `gallery` / `accordion` / `nav-menu` / `button` widgets (structured widgets where modifying HTML breaks the widget)

### Pre-flight checks before batch

1. **Dry-run on 1 post first** — `update_post_links(post_id, corpus, dry_run=True)` returns count without writing. Confirms keyword matches are sane.
2. **Audit live HTML on first batch result:**
   - `re.search(r'<a[^>]*>[^<]*<a ', html)` should return None (nested anchors)
   - `re.search(r'<[a-z]+ [^>]*<a ', html)` should return None (links inside attributes)
   - `'&lt;a href' in html` should be False (escaped link tags rendered as text)
3. **Spot-check 5 random linker outputs after each batch of 30-50** — the audit script in `lib/` does this. If any post shows broken HTML, stop and investigate.

### When NOT to add internal links

- Posts shorter than ~500 words (linker may add too high a density)
- Pages with form submissions / contact CTAs (anchor competition with primary CTA)
- The `posts` Elementor widget already cross-links via `modified` date — if a post's whole job is to be a "related" entry, no body links needed

### Posts widget side effect (NOT a bug)

Many Elementor pages have a `widgetType=posts` widget showing 4 most-recently-modified posts site-wide. **Editing posts updates their `modified` date, which changes which posts appear in this widget across the entire site.** When you push edits to a few flagship posts, those start appearing as "Leading treatments" everywhere. Don't be alarmed when the user asks "why is this post showing up everywhere now" — explain that it's the posts widget behaving correctly with the new modification timestamps.

---

## HARD RULES — Mobile responsiveness (validated on post 52166 — these caused real bugs)

The dr-meir.com site has a global footer + contact form template included via Elementor's `data-elementor-type="footer"` location. **Even one structural divergence in the post's body can break the footer's margins on that one page.** These rules are not optional.

### 1. NEVER add extra root-level Elementor containers beyond what content needs

A common mistake: injecting CSS via a separate `<style>` block in an Elementor html widget. This adds an empty/style-only container. Even though the widget is invisible, the CONTAINER itself takes Elementor padding/margin and shifts the post's layout calculation, which leaks into the footer. Symptom: form fields and footer nav touching the right edge of viewport, while other pages render normally.

**Don't do this.** The `qrfnstyle` container experiment broke the footer on post 52166. We had to remove it.

### 2. NEVER wrap widget content in extra outer `<div class="...">` wrappers

Even with scoped CSS classes, the extra DOM level diverges from the structural pattern of other posts. Just add the content directly as semantic HTML inside the text-editor widget.

### 3. Wide tables: wrap INLINE only, no class

Tables with 5+ columns push the page wide on mobile. The fix is exactly:

```html
<div style="overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch;margin:1em 0;">
  <table>...</table>
</div>
```

No CSS class. No external stylesheet. Inline only. The integrator does this automatically — DON'T pre-wrap. The scroll lives INSIDE the table; the page never goes wide.

### 4. Match the structural pattern of other posts

Before deploying any new container/widget pattern, ask: do other posts on this site use this same structure? If not, find a way to do the change inline within an existing text-editor widget. After deploying, mobile-UA fetch the edited page AND a known-working sibling page, then diff for structural differences.

### 5. NEVER inject CSS via Elementor html widget at the root

Site-wide CSS belongs in the theme/customizer. Per-post CSS belongs in Elementor's "Custom CSS" panel (Pro feature, accessed via Elementor's own save flow, not via raw `_elementor_data` writes — and even that we don't need given the inline approach).

### 6. NEVER paste competitor or transcript text verbatim

Same content quality rule. Extract facts → write original Hebrew prose. Verbatim paste = duplicate content penalty + copyright risk.

---

## Elementor REST API — required gotchas

### Updating `_elementor_data`

```python
# pseudo
POST /wp-json/wp/v2/posts/<id>
{
  "meta": {
    "_elementor_data": "<JSON-encoded STRING — NOT an object>",
    "_elementor_css": ""
  }
}
```

- `_elementor_data` MUST be a JSON-encoded string inside the meta object (string serialization of the array).
- `_elementor_css` cleared to force per-post CSS regen. Skip and the old CSS keeps serving.
- Only admin users (capability `manage_options`) can write this meta key via REST.

### Cache clearing — REQUIRED

```python
DELETE /wp-json/elementor/v1/cache
```

Without this, Elementor keeps rendering from its cached HTML/CSS and your new widgets won't appear on the live page even though the database has them. The `phase_push_and_verify` function in `pipeline.py` runs this automatically, but if you ever push manually, do this DELETE.

WP Rocket auto-purges page cache on post update for that URL. No public REST endpoint exists for manual WP Rocket purge — don't bother trying. The WP Rocket flow:
1. WP fires `save_post` action when REST POST persists
2. WP Rocket hooks that action, purges that URL's cached page
3. Next visitor regenerates the page from PHP, picks up new Elementor render

### IndexNow via Rank Math

```python
POST /wp-json/rankmath/v1/in/submitUrls
Body: {"urls": "https://dr-meir.com/full/path/"}
```

Critical: `urls` is a STRING (newline-separated for multiple). Sending an array returns 400.

Rank Math also auto-pings IndexNow when a post is saved — so after our REST update, IndexNow gets hit automatically. The manual call is double-insurance, no harm.

IndexNow goes to Bing + Yandex. **Google does NOT accept IndexNow.** For Google re-indexing, the user manually submits via Search Console → URL Inspection → Request Indexing. The skill doesn't have GSC API access (no OAuth set up). Tell the user to submit manually for high-priority posts.

### Sitemap

Rank Math auto-updates `<lastmod>` in `/post-sitemap*.xml` when `modified` timestamp changes (which our POST triggers). No manual ping required.

---

## Schema.org — what to add and what NOT to

### What to add (we generate)

- **MedicalProcedure** — name, description, alternateName, bodyLocation, howPerformed, preparation, followup, procedureType
- **FAQPage** — mainEntity array of Question/Answer pairs

Both go into a single `<script type="application/ld+json">` block in a `widget_type: html` Elementor widget at the END of the post (after CTA). Rank Math's existing schema doesn't conflict — Google merges multiple JSON-LD blocks on the same page.

Use `schema.medical_procedure_faq_schema()` builder. For FAQPage input, use `schema.faq_from_html_h3_pairs(faq_html)` to auto-extract Q&A from the FAQ section's H3+P structure.

### What NOT to add

- **Article** / **BlogPosting** — Rank Math already generates these with proper hierarchy. Adding our own creates conflicting `@id` references.
- **Person/Organization/Place/MedicalClinic** — Rank Math handles these from site-wide settings.
- **BreadcrumbList** — Rank Math auto-generates from URL hierarchy.
- **Review/AggregateRating** — fake reviews are a Google manual-action target. Only add when real review data is available.

### Validation

After push, the user manually checks:
- `https://search.google.com/test/rich-results?url=<post-url>` — Google Rich Results Test
- Should show Article (Rank Math) + FAQPage + MedicalProcedure

---

## Rank Math — what it handles vs what we add

Rank Math handles automatically:
- Title tag and meta description (from post settings)
- OG tags (og:title, og:description, og:image, article:modified_time)
- Twitter Card
- Canonical URL
- Robots directives
- Article schema, breadcrumb schema, organization schema
- IndexNow auto-ping on save
- Sitemap generation + lastmod update

We layer on top:
- MedicalProcedure schema (Rank Math doesn't generate)
- FAQPage schema (Rank Math has a FAQ block but only triggers schema if you use Elementor's specific FAQ widget — easier to inject our own)
- Manual IndexNow ping (insurance)

**Don't fight Rank Math.** Read its existing meta/schema first, only ADD what's missing. Don't try to override its title/description (those come from post settings, edit there if needed).

---

## Batch mode — running across many posts

The user explicitly asked for batch on all 271 posts in a single run, ordered by post date desc (newest first — the natural REST API order).

### Approach for batch

```python
# Pseudocode for batch — agent layer wraps the pipeline
import sys, time
sys.path.insert(0, '/Users/meirbabaev/.dr-meir/lib')
from wp_client import list_all_posts
from pipeline import phase_snapshot, phase_analyze, phase_research_yt, phase_integrate, phase_push_and_verify

posts = list_all_posts()  # 271 posts, newest first
errors = []
for p in posts:
    pid = p['id']
    try:
        # Phase 1
        post_data = phase_snapshot(pid)
        analysis = phase_analyze(pid, post_data)

        # Phase 2 (Agent)
        # WebSearch HE + EN, top 5 each, extract facts -> save to runs/<pid>/serp_facts.md

        # Phase 3 (Agent)
        # WebSearch youtube top 5, get video_ids
        # CLI: phase_research_yt(pid, video_ids)

        # Phase 4 (Agent)
        # Gap analysis from current_text.txt + transcripts_full.json + serp_facts.md
        # Write Hebrew blocks
        # Save runs/<pid>/blocks.json + expected_strings.json

        # Phase 5 (CLI)
        phase_integrate(pid, blocks)
        report = phase_push_and_verify(pid, expected_strings)

        # Sleep 30-60s between posts to avoid rate limits + give time for caches
        time.sleep(30)
    except Exception as e:
        errors.append({'post_id': pid, 'error': str(e)})
        # Continue with next post
        continue
```

### Sequence + budgeting

Per post: ~3-5 minutes total
- CLI phases: ~30 seconds total per post
- Agent phases: ~2-4 minutes (research + writing)

**For 271 posts: budget 15-20 hours of agent work.** Strongly recommend running in batches of 10-20 with checkpoints, so the user can review the first batch and confirm before going further.

### Failure mode handling

Each post has its own `runs/<id>/` dir. A failure on one post doesn't affect others. Common failure modes:
- **Post is already optimized** — analysis shows >3000 words and existing schema. Skip.
- **Focus keyword unclear** — title is too generic. Use the first H1 or fall back to slug.
- **No relevant YouTube videos** — proceed with text-SERP only.
- **All YouTube transcripts disabled** — same.
- **Post has unusual Elementor structure** — diff against another post; if it's a landing page or category page, skip (this skill is for blog posts only).
- **REST returns 401** — credentials need rotation or username is wrong (it should be `2ofnu4`).

### Resume after interruption

Each phase saves intermediate state to `runs/<id>/`. To resume:
- `analyze` → can re-run; overwrites
- `yt` → can re-run; overwrites if same video IDs
- `push` → check `runs/<id>/report.json`; if exists, post is done

A simple "skip if already done" check:
```python
if (Path(f'runs/{pid}/report.json')).exists():
    continue  # already pushed
```

---

## Quick reference: API endpoints we use

| Endpoint | Method | Purpose |
|---|---|---|
| `/wp-json/wp/v2/posts?per_page=100&page=N` | GET | List posts (paginated, X-WP-Total + X-WP-TotalPages headers) |
| `/wp-json/wp/v2/posts/<id>?context=edit` | GET | Fetch single post with `meta._elementor_data` (admin only) |
| `/wp-json/wp/v2/posts/<id>` | POST | Update post including `meta._elementor_data` |
| `/wp-json/wp/v2/users/me?context=edit` | GET | Verify auth + capabilities |
| `/wp-json/elementor/v1/cache` | DELETE | **REQUIRED** after Elementor data update |
| `/wp-json/rankmath/v1/in/submitUrls` | POST | IndexNow submission (urls as STRING, newline-separated for multiple) |
| `/wp-json/rankmath/v1/in/getLog` | POST | IndexNow log (POST with empty body `{}`) |
| `/sitemap_index.xml` | GET | Rank Math sitemap index |
| `/post-sitemap1.xml` | GET | Posts page 1 of sitemap |

---

## Recovery procedure (rollback a broken push)

```bash
# 1. Find the latest backup for the post
ls -t ~/.dr-meir/backups/post_<id>_elementor_*.json | head -1

# 2. Restore via REST
python3 -c "
import sys
sys.path.insert(0, '/Users/meirbabaev/.dr-meir/lib')
from wp_client import update_elementor, clear_elementor_cache
elem = open('/Users/meirbabaev/.dr-meir/backups/post_<id>_elementor_<TIMESTAMP>.json').read()
update_elementor(<id>, elem)
clear_elementor_cache()
print('Restored.')
"

# 3. Verify
curl -sL 'https://dr-meir.com/<post-slug>/?cb=$(date +%s)' \
  -H 'User-Agent: Mozilla/5.0' | grep -i '<h2'
```

---

## Hebrew search opportunity insight

For most procedure-specific keywords on dr-meir.com (Quantum RF, BodyTite, FaceTite, Renuvion, etc), the **Hebrew SERP and Hebrew YouTube results are sparse**. English content dominates these niches globally, but Israeli search has very few authoritative Hebrew pages on the specific brand-named technologies.

This means: well-optimized Hebrew posts on these terms can rank position 1-3 with relatively modest authority signals. The pipeline's bilingual research (English for facts, Hebrew for SERP intel) is specifically designed to capture this opportunity.

When you see "no Hebrew videos on this keyword exist" — surface that to the user as an upsell signal: **a Hebrew clinic video on that keyword would own the YouTube SERP without competition.**

---

## What to tell the user at end of each post

After each post optimization completes, surface:
1. **Word count delta** (e.g., "expanded from 1,000 → 3,000 words")
2. **New sections added** (count + brief titles)
3. **New schema added** (MedicalProcedure / FAQPage)
4. **Mobile verified** (Yes/No — based on rendered HTML check)
5. **IndexNow status** (200 OK)
6. **Manual GSC step** (URL Inspection → Request Indexing on `<post-url>`)
7. **Backup location** (`~/.dr-meir/backups/post_<id>_elementor_<timestamp>.json`)

For batch runs: aggregate stats at end (total posts processed, total new words added, total errors, list of posts needing manual GSC submission).

---

## Common pitfalls — refer to memory files

- `~/.claude/projects/-Users-meirbabaev/memory/elementor-rest-edit-workflow.md` — the cache-clear gotcha
- `~/.claude/projects/-Users-meirbabaev/memory/elementor-mobile-edits-rules.md` — the footer-broken story
- `~/.claude/projects/-Users-meirbabaev/memory/seo-content-expansion-approach.md` — the original-synthesis principle
- `~/.claude/projects/-Users-meirbabaev/memory/wp-rest-api-gotchas.md` — username-vs-slug, IndexNow payload format
- `~/.claude/projects/-Users-meirbabaev/memory/youtube-transcript-content-step.md` — the YouTube step

If any of those memory files contain conflicting info with this SKILL.md, **trust the memory files** — they are kept up-to-date independently. This SKILL.md is a stable reference; the memory files capture corrections.
