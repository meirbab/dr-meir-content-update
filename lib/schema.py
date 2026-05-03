"""
Schema JSON-LD generators for Hebrew medical/aesthetic blog posts.

Generates MedicalProcedure + FAQPage schema as a single <script type="application/ld+json">
block to be injected via Elementor html widget at end of post.
"""
import json


def medical_procedure_faq_schema(
    canonical_url: str,
    procedure_name: str,
    procedure_description: str,
    body_locations: list = None,
    alternate_names: list = None,
    how_performed: str = None,
    preparation: str = None,
    followup: str = None,
    faq: list = None,
    procedure_type: str = 'https://schema.org/SurgicalProcedure',
) -> str:
    """Build the JSON-LD <script> tag content (Schema.org @graph with two nodes).

    faq: list of {'q': str, 'a': str}
    """
    graph = []

    proc = {
        '@type': 'MedicalProcedure',
        '@id': f'{canonical_url}#procedure',
        'name': procedure_name,
        'description': procedure_description,
        'procedureType': procedure_type,
        'url': canonical_url,
    }
    if alternate_names:
        proc['alternateName'] = alternate_names
    if body_locations:
        proc['bodyLocation'] = body_locations
    if how_performed:
        proc['howPerformed'] = how_performed
    if preparation:
        proc['preparation'] = preparation
    if followup:
        proc['followup'] = followup
    graph.append(proc)

    if faq:
        graph.append({
            '@type': 'FAQPage',
            '@id': f'{canonical_url}#faq',
            'mainEntity': [
                {
                    '@type': 'Question',
                    'name': item['q'],
                    'acceptedAnswer': {'@type': 'Answer', 'text': item['a']},
                }
                for item in faq
            ]
        })

    schema = {'@context': 'https://schema.org', '@graph': graph}
    return ('<script type="application/ld+json">'
            + json.dumps(schema, ensure_ascii=False)
            + '</script>')


def faq_from_html_h3_pairs(faq_html: str) -> list:
    """Convert FAQ HTML (h3 question + p answer pairs) into list of {q,a} dicts.

    Useful when you have human-written FAQ in a text-editor widget and want to
    auto-generate matching FAQPage schema.
    """
    import re
    pairs = []
    # Match alternating h3 then p (allow whitespace between)
    pattern = re.compile(
        r'<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>',
        re.S | re.I,
    )
    for m in pattern.finditer(faq_html):
        q = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        a = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if q and a:
            pairs.append({'q': q, 'a': a})
    return pairs
