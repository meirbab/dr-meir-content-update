"""
Research helpers: SERP analysis (text) and YouTube transcript extraction.

NOTE: Text-SERP search via Google is gated behind the WebSearch tool which is
NOT importable as a Python lib. The actual SERP fetch happens at the agent
layer; this module covers the parts that ARE pure code: YouTube transcript
extraction, fact extraction utilities, content gap reporting.
"""
import json
import re
from pathlib import Path

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
    )
    _YT_OK = True
except ImportError:
    _YT_OK = False


# ============================================================ YouTube

def fetch_transcripts(video_ids: list, language_pref: str = 'en',
                      out_dir: str = None) -> dict:
    """Fetch transcripts for a list of YouTube video IDs.

    Returns dict: { video_id: {language, is_generated, word_count, text} }
    Skips videos with no captions (TranscriptsDisabled / NoTranscriptFound).

    Tries language_pref manual -> language_pref auto -> English -> any.
    """
    if not _YT_OK:
        raise ImportError('Install youtube-transcript-api: pip3 install --user youtube-transcript-api')

    api = YouTubeTranscriptApi()
    out = {}
    for vid in video_ids:
        try:
            tl = api.list(vid)
            transcript = None
            # Preference order: manual in pref language, auto in pref, manual EN, auto EN, any
            for prefer_lang, prefer_manual in [
                (language_pref, True), (language_pref, False),
                ('en', True), ('en', False),
            ]:
                for t in tl:
                    matches_lang = t.language_code.startswith(prefer_lang)
                    matches_manual = (not t.is_generated) == prefer_manual
                    if matches_lang and matches_manual:
                        transcript = t
                        break
                if transcript:
                    break
            if not transcript:
                for t in tl:
                    transcript = t
                    break
            if not transcript:
                continue

            data = transcript.fetch()
            text = ' '.join(s.text for s in data)
            out[vid] = {
                'language': transcript.language_code,
                'is_generated': transcript.is_generated,
                'word_count': len(text.split()),
                'text': text,
            }
            if out_dir:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                Path(f'{out_dir}/{vid}.txt').write_text(text, encoding='utf-8')
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            continue
        except Exception as e:
            # Log but continue — don't fail the whole batch on one bad video
            print(f'[transcript] {vid} error: {type(e).__name__}: {e}')
            continue
    return out


def extract_video_ids_from_search(search_results_text: str) -> list:
    """Pull video IDs out of WebSearch results that contain youtube.com URLs."""
    ids = set()
    for m in re.finditer(r'youtube\.com/(?:watch\?v=|shorts/)([\w\-]{11})', search_results_text):
        ids.add(m.group(1))
    return list(ids)


# ============================================================ Existing post analysis

def extract_post_text(elementor_tree: list) -> str:
    """Walk Elementor tree, return all text-editor and html widget content (cleaned)."""
    chunks = []
    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            settings = node.get('settings', {})
            for key in ('editor', 'html', 'text', 'title'):
                v = settings.get(key)
                if isinstance(v, str) and v.strip():
                    chunks.append(v)
            for x in node.get('elements', []):
                walk(x)
    walk(elementor_tree)
    full = '\n'.join(chunks)
    # Strip HTML tags for fact-coverage analysis
    text_only = re.sub(r'<[^>]+>', ' ', full)
    text_only = re.sub(r'\s+', ' ', text_only).strip()
    return text_only


def find_facts_missing_from_post(post_text: str, candidate_facts: list,
                                 case_sensitive: bool = False) -> list:
    """Return the subset of candidate facts whose key strings are NOT in post_text.

    candidate_facts: list of dicts with at least {'fact': str, 'markers': list[str]}
    A fact is considered already covered if ANY of its markers appears in post_text.
    """
    pt = post_text if case_sensitive else post_text.lower()
    missing = []
    for c in candidate_facts:
        markers = c.get('markers', [])
        if not markers:
            missing.append(c)
            continue
        found = any((m.lower() if not case_sensitive else m) in pt for m in markers)
        if not found:
            missing.append(c)
    return missing
