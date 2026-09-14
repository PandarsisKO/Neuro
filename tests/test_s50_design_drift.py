"""S50 — the design-drift ratchet. (Sorts after test_s49.)

`DESIGN.md` names six font sizes, four radii, one token set and no inline styling. The implemented UI does not
match that, and saying so in prose has never moved the numbers. This gate measures the gap and holds it: a count
may fall, never rise.

Baseline measured 2026-09-12 at commit `19d858b`, before any design rung. It is a ceiling, never a target — the
right way to pass this file is to leave a surface cleaner than you found it, then lower the number here in the
same commit. Raising a number requires a recorded decision in HARDENING.md, not a quiet edit.

Why each measure exists:

- **inline styles** — at the baseline, 432 `style="` attributes against 259 lines of CSS. Most of this UI's visual
  language is not in the stylesheet, which is why a correct token and an inconsistent screen coexist.
- **colour literals outside the token blocks** — a literal cannot follow the theme, so every one is a dark-mode
  defect waiting to be seen.
- **font sizes / radii** — 16 sizes and 11 radii against scales of six and four.
- **emoji-only controls** — `DESIGN.md` §6 allows emoji in content, never as a control glyph.
- **single-theme colour tokens** — a colour defined only in `:root` renders wrong in dark.
- **emoji-prefixed buttons** — CL-6 (declutter audit): an emoji beside a text label the button already
  states ("Rebuild in the background") is decoration, not the emoji-only glyphs `MAX_EMOJI_ONLY_CONTROLS`
  already catches. Measured 2026-09-14 at 0, after that rung's sweep -- unlike the other measures here, this
  one starts at its floor rather than a pre-existing baseline.
"""
from pathlib import Path
import re

HTML = (Path(__file__).resolve().parents[1] / 'neurosearch/web/index.html').read_text(encoding='utf-8')
CSS = (Path(__file__).resolve().parents[1] / 'neurosearch/web/styles.css').read_text(encoding='utf-8')
JS_DIR = Path(__file__).resolve().parents[1] / 'neurosearch/web/js'
JS = '\n'.join(p.read_text(encoding='utf-8') for p in sorted(JS_DIR.glob('*.js')))
ROOT = re.search(r':root\{(.*?)\}', CSS, re.S).group(1)
DARK = re.search(r'\[data-theme=dark\]\{(.*?)\}', CSS, re.S).group(1)
CSS_BODY = re.sub(r'\[data-theme=dark\]\{.*?\}', '', re.sub(r':root\{.*?\}', '', CSS, flags=re.S), flags=re.S)

# ---- baseline at 19d858b. Lower these when you clean a surface; never raise without a HARDENING entry.
MAX_INLINE_STYLE_ATTRS = 287
MAX_CSS_COLOUR_LITERALS = 28
MAX_JS_COLOUR_LITERALS = 3
MAX_DISTINCT_FONT_SIZES = 16
MAX_DISTINCT_RADII = 11
MAX_EMOJI_ONLY_CONTROLS = 8
MAX_EMOJI_PREFIXED_BUTTONS = 0

COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(')
EMOJI = re.compile(r'[\U0001F300-\U0001FAFF☀-➿️]')


def inline_style_attrs():
    return len(re.findall(r'\sstyle="', HTML))


def colour_literals(text):
    return COLOUR.findall(text)


def distinct_font_sizes():
    return {m for m in re.findall(r'font-size:\s*([\d.]+)px', HTML + CSS)}


def distinct_radii():
    return {m for m in re.findall(r'border-radius:\s*([\d.]+(?:px|%))', HTML + CSS)}


def emoji_only_controls():
    return re.findall(r'<button[^>]*>\s*(' + EMOJI.pattern + r'+)\s*<', HTML)


def emoji_prefixed_buttons():
    # CL-6: a button whose label is an emoji FOLLOWED BY text it already states in words -- the emoji adds
    # nothing a sighted, English-reading user did not already get from the word. Nav items and chip-row
    # legends (a single letter/word beside a glyph, distinguishing siblings at a glance -- DESIGN.md's named
    # exception) are not <button> elements and so are not counted here.
    return re.findall(r'>(' + EMOJI.pattern + r')(\s?)([A-Za-z][^<]{0,80}?)</button>', HTML + JS)


def tokens(block):
    return {name: value.strip() for name, value in re.findall(r'(--[a-z0-9-]+)\s*:\s*([^;}]+)', block)}


def test_inline_styles_do_not_grow():
    n = inline_style_attrs()
    assert n <= MAX_INLINE_STYLE_ATTRS, (
        f'{n} inline style attributes, ceiling {MAX_INLINE_STYLE_ATTRS}. New UI adds none; retire them on the '
        'surface you touched and lower the ceiling in the same commit.')


def test_colour_literals_stay_in_the_token_blocks():
    css = colour_literals(CSS_BODY)
    js = colour_literals(JS)
    assert len(css) <= MAX_CSS_COLOUR_LITERALS, f'{len(css)} colour literals in CSS rules, ceiling {MAX_CSS_COLOUR_LITERALS}: {css}'
    assert len(js) <= MAX_JS_COLOUR_LITERALS, f'{len(js)} colour literals in JS, ceiling {MAX_JS_COLOUR_LITERALS}: {js}'


def test_type_scale_does_not_sprawl():
    sizes = distinct_font_sizes()
    assert len(sizes) <= MAX_DISTINCT_FONT_SIZES, (
        f'{len(sizes)} distinct font sizes, ceiling {MAX_DISTINCT_FONT_SIZES}: {sorted(sizes, key=float)}. '
        'DESIGN.md names six.')


def test_radius_scale_does_not_sprawl():
    radii = distinct_radii()
    assert len(radii) <= MAX_DISTINCT_RADII, (
        f'{len(radii)} distinct radii, ceiling {MAX_DISTINCT_RADII}: {sorted(radii)}. DESIGN.md names four plus 50%.')


def test_emoji_are_content_not_control_glyphs():
    found = emoji_only_controls()
    assert len(found) <= MAX_EMOJI_ONLY_CONTROLS, (
        f'{len(found)} buttons whose only glyph is an emoji, ceiling {MAX_EMOJI_ONLY_CONTROLS}: {found}. '
        'Use the SVG sprite and give the control a name.')


def test_emoji_beside_a_label_the_button_already_states_is_removed():
    found = emoji_prefixed_buttons()
    assert len(found) <= MAX_EMOJI_PREFIXED_BUTTONS, (
        f'{len(found)} buttons prefix an emoji onto a text label that already says the same thing, ceiling '
        f'{MAX_EMOJI_PREFIXED_BUTTONS}: {found}. CL-6 (declutter audit): remove the emoji, keep the word.')


def test_every_colour_token_exists_in_both_themes():
    """A colour defined only in :root renders wrong in dark. Layout tokens (--side) legitimately live in one block."""
    light, dark = tokens(ROOT), tokens(DARK)
    light_colours = {k for k, v in light.items() if COLOUR.search(v) or v in ('none', 'transparent')}
    missing = sorted(light_colours - set(dark))
    assert not missing, f'colour tokens with no dark value: {missing}'


def _hex_to_rgb(value):
    h = value.strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(rgb):
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(fg_hex, bg_hex):
    l1 = _relative_luminance(_hex_to_rgb(fg_hex))
    l2 = _relative_luminance(_hex_to_rgb(bg_hex))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_status_text_colours_meet_aa_on_panel():
    """DESIGN.md's frozen palette treats --ok/--warn/--bad as text-first status colour on --panel. WCAG 2.1 AA for
    normal text requires >= 4.5:1. This is the deterministic half of ladder.md rung F1's H-7 fix; the F0 baseline
    measured --ok and --warn failing this in the light theme before the frozen tokens landed."""
    for theme_name, block in (('light', ROOT), ('dark', DARK)):
        t = tokens(block)
        panel = t['--panel']
        for name in ('--ok', '--warn', '--bad'):
            ratio = _contrast_ratio(t[name], panel)
            assert ratio >= 4.5, f'{theme_name} {name} ({t[name]}) on --panel ({panel}) is {ratio:.2f}:1, needs >= 4.5:1'


def test_the_ratchet_would_catch_a_regression():
    """The gate must fail on the thing it exists to prevent, not merely pass today."""
    assert COLOUR.search('color:#ff0000'), 'literal detector is broken'
    assert COLOUR.search('background:rgba(0,0,0,.2)'), 'rgba detector is broken'
    assert EMOJI.search('🔄'), 'emoji detector is broken'
    assert not COLOUR.search('border:1px solid var(--line)'), 'token reference must not count as a literal'
    assert re.findall(r'>(' + EMOJI.pattern + r')(\s?)([A-Za-z][^<]{0,80}?)</button>', '<button>🔄 Retry</button>'), \
        'emoji-prefixed-button detector is broken'
