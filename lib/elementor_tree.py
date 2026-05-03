"""
Elementor JSON tree helpers for editing post content.

The _elementor_data field is a JSON-encoded array of root containers, each with
nested .elements (children). This module hides the JSON-string round-trip and
gives high-level operations: find, insert at index, append after target, expand
existing widget.

Usage:
    from elementor_tree import ElementorDoc

    doc = ElementorDoc.from_string(elementor_data_str)
    intro_widget = doc.find_widget('qrf00001')
    doc.append_to_widget('qrf00004', '<p>extra paragraph</p>')
    doc.insert_after_container('qrf0001e', doc.text_section('myid', 'mywid', '<h2>...</h2>'))
    new_str = doc.to_string()
"""
import json
import copy


class ElementorDoc:
    """Mutable wrapper around the parsed _elementor_data JSON array."""

    def __init__(self, tree: list):
        if not isinstance(tree, list):
            raise TypeError('Elementor tree must be a list of root containers')
        self.tree = tree

    @classmethod
    def from_string(cls, elementor_data_str: str) -> 'ElementorDoc':
        return cls(json.loads(elementor_data_str))

    def to_string(self) -> str:
        return json.dumps(self.tree, ensure_ascii=False, separators=(',', ':'))

    def clone(self) -> 'ElementorDoc':
        return ElementorDoc(copy.deepcopy(self.tree))

    # ---------------- finders

    def find_widget(self, target_id: str):
        """Recursive find by id. Returns the dict or None."""
        return _find(self.tree, target_id)

    def index_of_root(self, target_id: str) -> int:
        """Index of a top-level container, or -1."""
        for i, n in enumerate(self.tree):
            if n.get('id') == target_id:
                return i
        return -1

    def root_ids(self) -> list:
        return [n.get('id') for n in self.tree]

    # ---------------- mutators

    def append_to_widget(self, target_id: str, html_to_append: str) -> bool:
        """Append HTML to a text-editor widget's editor field (or html field).
        Idempotent if the appended content already exists. Returns True on change."""
        w = _find(self.tree, target_id)
        if not w:
            return False
        s = w.setdefault('settings', {})
        for key in ('editor', 'html'):
            if key in s and isinstance(s[key], str):
                if html_to_append.strip() in s[key]:
                    return False
                s[key] = s[key] + '\n' + html_to_append
                return True
        # Widget had no text/html field — set 'editor' if it's a text-editor
        if w.get('widgetType') == 'text-editor':
            s['editor'] = html_to_append
            return True
        return False

    def replace_widget_content(self, target_id: str, new_html: str) -> bool:
        """Replace the editor/html field entirely."""
        w = _find(self.tree, target_id)
        if not w:
            return False
        s = w.setdefault('settings', {})
        for key in ('editor', 'html'):
            if key in s:
                s[key] = new_html
                return True
        if w.get('widgetType') == 'text-editor':
            s['editor'] = new_html
            return True
        return False

    def insert_at_root(self, container: dict, index: int):
        self.tree.insert(index, container)

    def insert_after_container(self, target_id: str, container: dict) -> bool:
        i = self.index_of_root(target_id)
        if i < 0:
            return False
        self.tree.insert(i + 1, container)
        return True

    def append_to_root(self, container: dict):
        self.tree.append(container)

    # ---------------- factory: container builders

    @staticmethod
    def text_section(container_id: str, widget_id: str, html: str) -> dict:
        """Build a top-level container with a single text-editor widget.

        IMPORTANT for Elementor edits: keep the structure minimal — same shape as
        the existing post's other text sections. Adding extra wrappers, classes,
        or inline styles outside text-editor content can break mobile layout
        on the entire page (including footer). See memory: elementor-mobile-edits-rules.
        """
        return {
            'id': container_id,
            'elType': 'container',
            'settings': {'flex_direction': 'column', 'content_width': 'boxed'},
            'elements': [{
                'id': widget_id,
                'elType': 'widget',
                'settings': {'editor': html},
                'elements': [],
                'widgetType': 'text-editor'
            }],
            'isInner': False
        }

    @staticmethod
    def html_section(container_id: str, widget_id: str, html: str) -> dict:
        """Container with raw HTML widget. Used for JSON-LD schema injection."""
        return {
            'id': container_id,
            'elType': 'container',
            'settings': {'flex_direction': 'column'},
            'elements': [{
                'id': widget_id,
                'elType': 'widget',
                'settings': {'html': html},
                'elements': [],
                'widgetType': 'html'
            }],
            'isInner': False
        }

    # ---------------- table-overflow utility

    @staticmethod
    def wrap_table_for_mobile(html: str) -> str:
        """Wrap each <table>...</table> in an inline overflow-x:auto div so wide
        tables scroll INSIDE the table on mobile, not pushing the whole page wide.
        Inline only — no CSS classes, no extra Elementor containers."""
        import re
        wrap_open = ('<div style="overflow-x:auto;max-width:100%;'
                     '-webkit-overflow-scrolling:touch;margin:1em 0;">')
        wrap_close = '</div>'
        def _wrap(m):
            return wrap_open + m.group(0) + wrap_close
        return re.sub(r'<table[\s\S]*?</table>', _wrap, html, flags=re.IGNORECASE)


# Internal recursive search

def _find(nodes, target_id):
    if isinstance(nodes, dict):
        nodes = [nodes]
    for n in nodes:
        if n.get('id') == target_id:
            return n
        children = n.get('elements', [])
        if children:
            r = _find(children, target_id)
            if r is not None:
                return r
    return None
