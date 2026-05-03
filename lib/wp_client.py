"""
WordPress REST API client for dr-meir.com.

Loads credentials from ~/.dr-meir/credentials.env, exposes:
  - get_post(post_id) — fetch with edit context
  - list_posts(per_page=100, page=1, status='publish') — paginated list
  - update_elementor(post_id, elementor_data_str) — write _elementor_data + clear css cache
  - clear_elementor_cache() — DELETE /elementor/v1/cache (REQUIRED after every update)
  - submit_indexnow(url) — Rank Math IndexNow ping
  - fetch_live_html(url, mobile=False) — fetch rendered page with cache-busting
"""
import base64
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

CREDS_PATH = Path('/Users/meirbabaev/.dr-meir/credentials.env')


def _load_creds():
    creds = {}
    if not CREDS_PATH.exists():
        raise FileNotFoundError(f'Credentials file missing: {CREDS_PATH}')
    for line in CREDS_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        v = v.strip().strip('"').strip("'")
        creds[k.strip()] = v
    for required in ('WP_SITE', 'WP_USERNAME', 'WP_APP_PASSWORD'):
        if required not in creds or not creds[required]:
            raise ValueError(f'Missing {required} in {CREDS_PATH}')
    return creds


_CREDS = None


def _get_creds():
    global _CREDS
    if _CREDS is None:
        _CREDS = _load_creds()
    return _CREDS


def _auth_header():
    c = _get_creds()
    token = base64.b64encode(f"{c['WP_USERNAME']}:{c['WP_APP_PASSWORD']}".encode()).decode()
    return f'Basic {token}'


def _request(method: str, path: str, body=None, timeout: int = 60, raw_body: bool = False):
    """Authenticated request to /wp-json/<path>. Returns parsed JSON (or raises)."""
    site = _get_creds()['WP_SITE'].rstrip('/')
    url = f'{site}/wp-json/{path.lstrip("/")}'
    data = None
    if body is not None:
        data = body if raw_body else json.dumps(body).encode('utf-8')
    headers = {
        'Authorization': _auth_header(),
        'User-Agent': 'Mozilla/5.0 dr-meir-pipeline',
    }
    if body is not None and not raw_body:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode('utf-8')
            try:
                return json.loads(text), resp.status, dict(resp.headers)
            except json.JSONDecodeError:
                return text, resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        raise RuntimeError(f'HTTP {e.code} {method} {url}: {body[:500]}') from e


# ---------------------------------------------------------------- Posts API

def get_post(post_id: int, context: str = 'edit') -> dict:
    """Fetch a single post including meta._elementor_data."""
    data, _, _ = _request('GET', f'wp/v2/posts/{post_id}?context={context}')
    return data


def list_posts(per_page: int = 100, page: int = 1, status: str = 'publish',
               fields: str = 'id,date,modified,slug,status,title,link,categories,tags') -> tuple:
    """List posts with pagination. Returns (posts, total_count, total_pages)."""
    qs = urllib.parse.urlencode({
        'per_page': per_page,
        'page': page,
        'status': status,
        'orderby': 'date',
        'order': 'desc',
        '_fields': fields,
    })
    data, status_code, headers = _request('GET', f'wp/v2/posts?{qs}')
    total = int(headers.get('X-WP-Total') or headers.get('x-wp-total') or 0)
    pages = int(headers.get('X-WP-TotalPages') or headers.get('x-wp-totalpages') or 0)
    return data, total, pages


def list_all_posts(status: str = 'publish') -> list:
    """Iterate all pages and return all posts (lightweight fields)."""
    all_posts = []
    page = 1
    while True:
        posts, total, pages = list_posts(per_page=100, page=page, status=status)
        all_posts.extend(posts)
        if page >= pages or pages == 0:
            break
        page += 1
    return all_posts


def update_elementor(post_id: int, elementor_data_str: str, clear_css: bool = True) -> dict:
    """Write _elementor_data (as a JSON-encoded string in meta). Always clears _elementor_css
    to force CSS regen unless clear_css=False."""
    if not isinstance(elementor_data_str, str):
        raise TypeError('_elementor_data must be a JSON-encoded string')
    json.loads(elementor_data_str)  # validate
    meta = {'_elementor_data': elementor_data_str}
    if clear_css:
        meta['_elementor_css'] = ''
    data, _, _ = _request('POST', f'wp/v2/posts/{post_id}', body={'meta': meta})
    return data


# ---------------------------------------------------------------- Cache

def clear_elementor_cache() -> int:
    """REQUIRED after every Elementor update. Without this, the rendered page won't
    show new widgets even though the database has them."""
    _, status, _ = _request('DELETE', 'elementor/v1/cache')
    return status


# ---------------------------------------------------------------- IndexNow

def submit_indexnow(urls) -> dict:
    """Rank Math IndexNow submission. Accepts a single URL string or a list of URLs."""
    if isinstance(urls, list):
        urls_str = '\n'.join(urls)
    else:
        urls_str = urls
    data, _, _ = _request('POST', 'rankmath/v1/in/submitUrls', body={'urls': urls_str})
    return data


def get_indexnow_log() -> list:
    data, _, _ = _request('POST', 'rankmath/v1/in/getLog', body={})
    return data.get('data', []) if isinstance(data, dict) else []


# ---------------------------------------------------------------- Live page verification

def fetch_live_html(url: str, mobile: bool = False, timeout: int = 30) -> str:
    """Fetch rendered HTML with browser-like UA. Cache-busts with timestamp."""
    sep = '&' if '?' in url else '?'
    url_cb = f'{url}{sep}cb={int(time.time())}'
    if mobile:
        ua = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
              'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
    else:
        ua = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    req = urllib.request.Request(url_cb, headers={
        'User-Agent': ua,
        'Accept-Language': 'he-IL,he;q=0.9,en;q=0.8',
        'Cache-Control': 'no-cache',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def verify_post_meta(url: str, expected_strings: list, mobile: bool = True,
                     wait_seconds: int = 3) -> dict:
    """After update + cache clear, sleep briefly, fetch live HTML, and check each
    expected string is present. Returns a dict mapping expected -> bool."""
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    html = fetch_live_html(url, mobile=mobile)
    return {s: (s in html) for s in expected_strings}
