"""Static gates for the current single-file UI conventions; dynamic browser tests remain necessary."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re

HTML = (Path(__file__).resolve().parents[1] / 'neurosearch/web/index.html').read_text()
JS_DIR = Path(__file__).resolve().parents[1] / 'neurosearch/web/js'
JS = '\n'.join(p.read_text() for p in sorted(JS_DIR.glob('*.js')))

class Controls(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = []; self.handlers = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'): self.ids.append(attrs['id'])
        self.handlers.extend(v for k,v in attrs.items() if k.startswith('on') and v)


def duplicate_global_functions(js):
    # Global declarations in this repo begin at column zero. Nested scopes are deliberately excluded.
    names = re.findall(r'^(?:async\s+)?function\s+(\w+)\s*\(', js, re.M)
    return sorted(name for name, n in Counter(names).items() if n > 1)


def test_no_duplicate_global_handler_declarations():
    assert not duplicate_global_functions(JS)


def test_duplicate_gate_catches_the_previous_failure_class():
    assert duplicate_global_functions('function promoteReserve() {}\nasync function promoteReserve() {}') == ['promoteReserve']
    assert not duplicate_global_functions('function outer() {\n  function nested() {}\n}\nfunction other() {\n  function nested() {}\n}')


def test_static_dom_ids_are_unique():
    parser = Controls(); parser.feed(HTML)
    assert not [name for name,n in Counter(parser.ids).items() if n > 1]


def test_static_inline_handlers_reference_declared_functions():
    parser = Controls(); parser.feed(HTML)
    declared = set(re.findall(r'\b(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)', JS))
    builtins = {'Set', 'if', 'confirm', 'alert', 'setTimeout', 'Number', 'String', 'parseInt', 'parseFloat'}
    calls = {name for handler in parser.handlers for name in re.findall(r'(?<![\w.])([A-Za-z_$][\w$]*)\s*\(', handler)}
    assert not (calls - declared - builtins)


def test_all_first_party_fetches_use_version_boundary():
    assert len(re.findall(r'\bfetch\(', JS)) == 1, 'raw fetch bypasses stale-client refusal (uploads/streams included)'
    assert 'setInterval(() => { if (!document.hidden) checkVersion(); }, 30000)' in JS
    assert "window.addEventListener('focus', checkVersion)" in JS


def test_external_stylesheet_is_linked_and_served(client):
    assert '<style>' not in HTML
    assert '<link rel="stylesheet" href="/styles.css">' in HTML
    css = (Path(__file__).resolve().parents[1] / 'neurosearch/web/styles.css').read_text()
    response = client.get('/styles.css')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/css')
    assert response.headers['cache-control'] == 'no-cache'
    assert response.text == css
    module = client.get('/js/app.js')
    assert module.status_code == 200
    assert module.headers['content-type'].startswith('text/javascript')
