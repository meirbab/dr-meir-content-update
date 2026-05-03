"""
Categories enricher: WordPress categories don't use Elementor — they have only
a `description` field (HTML, displayed on the category archive page) and a
`name`. The category's archive page lists all posts in that category, plus the
description text at top.

For SEO, the description field is the SEO-optimizable surface. Rank Math also
generates Article + WebPage schema for category pages from this content.

This module:
1. Reads existing description (most dr-meir.com categories already have 4-13K chars)
2. Adds CollectionPage + ItemList schema as injected JSON-LD at end of description
3. Optionally appends a "What you'll find in this category" section with FAQ
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wp_client import _request, fetch_live_html, submit_indexnow


def get_category(cat_id: int) -> dict:
    data, _, _ = _request('GET', f'wp/v2/categories/{cat_id}?context=edit')
    return data


def list_categories(per_page: int = 100, hide_empty: bool = False) -> list:
    qs = f'per_page={per_page}&hide_empty={"true" if hide_empty else "false"}'
    data, _, _ = _request('GET', f'wp/v2/categories?{qs}')
    return data


def get_posts_in_category(cat_id: int, per_page: int = 50) -> list:
    """Top N posts in this category, for ItemList schema."""
    qs = f'categories={cat_id}&per_page={per_page}&_fields=id,title,link,date'
    data, _, _ = _request('GET', f'wp/v2/posts?{qs}')
    return data


def update_category_description(cat_id: int, description: str) -> dict:
    """POST to update category description. Categories use the same auth as posts."""
    data, _, _ = _request('POST', f'wp/v2/categories/{cat_id}',
                          body={'description': description})
    return data


def build_collection_schema(category_url: str, category_name: str,
                            description: str, posts: list) -> str:
    """Build CollectionPage + ItemList JSON-LD for a category archive."""
    item_list = [
        {
            '@type': 'ListItem',
            'position': i + 1,
            'name': re.sub(r'<[^>]+>', '', p.get('title', {}).get('rendered', '')).strip(),
            'url': p.get('link', ''),
        }
        for i, p in enumerate(posts[:30])
    ]
    schema = {
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'CollectionPage',
                '@id': f'{category_url}#collectionpage',
                'name': category_name,
                'description': re.sub(r'<[^>]+>', '', description)[:600],
                'url': category_url,
                'mainEntity': {'@id': f'{category_url}#itemlist'},
            },
            {
                '@type': 'ItemList',
                '@id': f'{category_url}#itemlist',
                'numberOfItems': len(item_list),
                'itemListElement': item_list,
            },
        ],
    }
    return ('<script type="application/ld+json">'
            + json.dumps(schema, ensure_ascii=False)
            + '</script>')


SCHEMA_MARKER = '<!-- claude-schema-injected -->'


def has_schema_marker(description: str) -> bool:
    return SCHEMA_MARKER in description


def enrich_category_with_schema(cat_id: int, dry_run: bool = False) -> dict:
    """Append CollectionPage + ItemList JSON-LD to category description."""
    cat = get_category(cat_id)
    description = cat.get('description', '') or ''
    if has_schema_marker(description):
        return {'cat_id': cat_id, 'name': cat.get('name'), 'status': 'skip',
                'reason': 'already enriched'}

    posts = get_posts_in_category(cat_id, per_page=30)
    if not posts:
        return {'cat_id': cat_id, 'name': cat.get('name'), 'status': 'skip',
                'reason': 'no posts in category'}

    cat_url = cat.get('link') or f'https://dr-meir.com/category/{cat.get("slug","")}/'
    schema_html = build_collection_schema(
        category_url=cat_url,
        category_name=cat.get('name', ''),
        description=description,
        posts=posts,
    )
    new_description = description.rstrip() + '\n\n' + SCHEMA_MARKER + '\n' + schema_html

    if dry_run:
        return {
            'cat_id': cat_id,
            'name': cat.get('name'),
            'status': 'dry-run',
            'posts_in_list': len(posts[:30]),
            'old_chars': len(description),
            'new_chars': len(new_description),
        }

    update_category_description(cat_id, new_description)
    submit_indexnow(cat_url)

    # Verify (categories don't have Elementor cache to clear)
    import time
    time.sleep(2)
    try:
        html = fetch_live_html(cat_url, timeout=20)
        ok_collection = 'CollectionPage' in html
        ok_itemlist = 'ItemList' in html
    except Exception:
        ok_collection = ok_itemlist = None

    return {
        'cat_id': cat_id,
        'name': cat.get('name'),
        'status': 'ok' if (ok_collection and ok_itemlist) else 'partial',
        'posts_in_list': len(posts[:30]),
        'verify_collectionpage': ok_collection,
        'verify_itemlist': ok_itemlist,
    }
