# -*- coding: utf-8 -*-
# F1 remaining item 3 of 3: name the eight emoji-only controls via an inline SVG <symbol> sprite.
# See docs/design-audit/2026-09-13-b85c222/f1-remaining-scope.md section 4 for rationale.
#
# REWRITTEN 2026-09-13 after Codex's frontend split landed on main at 5f667a1 ("refactor:
# decompose static frontend into modules"). The 8 button sites are byte-identical to before, just
# relocated: sourceDrawer's group() helper (5 of the 8 sites: reserve/suggested/approved
# branches) and the job cancel/dismiss buttons both ended up in neurosearch/web/js/research.js;
# discStatus's dismiss button ended up in neurosearch/web/js/sources.js. The sprite markup and
# .ic/.icon-sprite CSS still go in index.html / styles.css respectively.
#
# Distinct-glyph split (re-confirmed fresh against 5f667a1 by exact grep of `>✕</button>`,
# `>✓</button>`, `>📌</button>` across neurosearch/web/): ✕ = 5 sites (discStatus, group()'s
# suggested branch, group()'s approved branch, cancelJob, dismissJob), ✓ = 2 sites (group()'s
# reserve + suggested branches), 📌 = 1 site (group()'s reserve branch). 5+2+1 = 8, matching
# MAX_EMOJI_ONLY_CONTROLS = 8 exactly.
#
# DO NOT RUN without first re-confirming `git log --oneline -1 main` and a fresh grep of the
# three emoji-only button patterns across neurosearch/web/ still returns 5/2/1 — if anyone has
# touched these files again since, re-verify before trusting this script.

def use(name):
    return f'<svg class="ic"><use href="#{name}"></use></svg>'

# 1) insert the sprite right after <body> in index.html. Three original, simple stroke-based
#    glyphs — not copied from any icon set: an X (dismiss), a checkmark (approve), a flag (send
#    to suggested, replacing the pushpin emoji with the same "set this aside to revisit" meaning).
html_path = 'neurosearch/web/index.html'
s = open(html_path, encoding='utf-8').read()
old_body = "<body>\n\n<!-- ============ HOME ============ -->"
new_body = """<body>
<svg class="icon-sprite" width="0" height="0" aria-hidden="true">
  <symbol id="ic-dismiss" viewBox="0 0 24 24"><path d="M6 6 L18 18 M18 6 L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></symbol>
  <symbol id="ic-approve" viewBox="0 0 24 24"><path d="M5 12.5 L10 17.5 L19 6.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></symbol>
  <symbol id="ic-flag" viewBox="0 0 24 24"><path d="M6 3 L6 21 M6 4.5 L18 8 L6 11.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></symbol>
</svg>

<!-- ============ HOME ============ -->"""
assert s.count(old_body) == 1, ("body anchor", s.count(old_body))
s = s.replace(old_body, new_body)
open(html_path, 'w', encoding='utf-8').write(s)

# 2) add the .icon-sprite (hides the symbol-only host svg) and .ic (per-icon sizing + stroke
#    color) utility classes to styles.css. Using a class instead of style="position:absolute" on
#    the sprite host keeps this item net-negative on the MAX_INLINE_STYLE_ATTRS ratchet.
css_path = 'neurosearch/web/styles.css'
css = open(css_path, encoding='utf-8').read()
old_css = """  .grow{flex:1}
  .push-right{margin-left:auto}
  .min-w-0{min-width:0}"""
new_css = """  .grow{flex:1}
  .push-right{margin-left:auto}
  .min-w-0{min-width:0}
  .icon-sprite{position:absolute}
  .ic{width:14px;height:14px;vertical-align:-2px;color:currentColor}"""
assert css.count(old_css) == 1, ("css block", css.count(old_css))
css = css.replace(old_css, new_css)
open(css_path, 'w', encoding='utf-8').write(css)

# 3) discStatus dismiss button (Research candidates) — now in js/sources.js
sources_path = 'neurosearch/web/js/sources.js'
src = open(sources_path, encoding='utf-8').read()
old1 = """${d.status !== 'added' ? `<button class="small ghost" onclick="discStatus(${d.id},'dismissed')">✕</button>` : ''}"""
new1 = f"""${{d.status !== 'added' ? `<button class="small ghost" title="Dismiss" aria-label="Dismiss" onclick="discStatus(${{d.id}},'dismissed')">{use('ic-dismiss')}</button>` : ''}}"""
assert src.count(old1) == 1, ("discStatus dismiss", src.count(old1))
src = src.replace(old1, new1)
open(sources_path, 'w', encoding='utf-8').write(src)

# 4) sourceDrawer's group() helper (5 sites) + job cancel/dismiss (2 sites) — now in js/research.js
research_path = 'neurosearch/web/js/research.js'
r = open(research_path, encoding='utf-8').read()

old2 = """<div class="act">${key === 'reserve' ? `<button class="small primary" title="Approve" onclick="drawerNote(${f.id},'approved','${sid}')">✓</button><button class="small" title="Send to Suggested" onclick="drawerNote(${f.id},'suggested','${sid}')">📌</button>`
          : key === 'suggested' ? `<button class="small primary" onclick="drawerNote(${f.id},'approved','${sid}')">✓</button><button class="small ghost" onclick="drawerNote(${f.id},'dismissed','${sid}')">✕</button>`
          : key === 'approved' ? `<button class="small ghost" title="dismiss" onclick="drawerNote(${f.id},'dismissed','${sid}')">✕</button>` : ''}</div></div>`).join('');"""
new2 = f"""<div class="act">${{key === 'reserve' ? `<button class="small primary" title="Approve" aria-label="Approve" onclick="drawerNote(${{f.id}},'approved','${{sid}}')">{use('ic-approve')}</button><button class="small" title="Send to Suggested" aria-label="Send to Suggested" onclick="drawerNote(${{f.id}},'suggested','${{sid}}')">{use('ic-flag')}</button>`
          : key === 'suggested' ? `<button class="small primary" title="Approve" aria-label="Approve" onclick="drawerNote(${{f.id}},'approved','${{sid}}')">{use('ic-approve')}</button><button class="small ghost" title="Dismiss" aria-label="Dismiss" onclick="drawerNote(${{f.id}},'dismissed','${{sid}}')">{use('ic-dismiss')}</button>`
          : key === 'approved' ? `<button class="small ghost" title="Dismiss" aria-label="Dismiss" onclick="drawerNote(${{f.id}},'dismissed','${{sid}}')">{use('ic-dismiss')}</button>` : ''}}</div></div>`).join('');"""
assert r.count(old2) == 1, ("group() helper", r.count(old2))
r = r.replace(old2, new2)

old3 = """${(j.status === 'queued' || j.status === 'running' || j.status === 'external_pending') && j.id && !j.cancel_requested_at ? `<button class="small ghost" title="${j.status === 'queued' ? 'Remove from the queue' : 'Stop at the next safe point'}" onclick="cancelJob('${j.id}')">✕</button>` : ''}${j.status === 'failed' && j.id ? `<button class="small" title="Try again" onclick="retryJob('${j.id}')">↻ Retry</button><button class="small ghost" title="Hide this error" onclick="dismissJob('${j.id}')">✕</button>` : ''}"""
new3 = f"""${{(j.status === 'queued' || j.status === 'running' || j.status === 'external_pending') && j.id && !j.cancel_requested_at ? `<button class="small ghost" title="${{j.status === 'queued' ? 'Remove from the queue' : 'Stop at the next safe point'}}" aria-label="Cancel job" onclick="cancelJob('${{j.id}}')">{use('ic-dismiss')}</button>` : ''}}${{j.status === 'failed' && j.id ? `<button class="small" title="Try again" onclick="retryJob('${{j.id}}')">↻ Retry</button><button class="small ghost" title="Hide this error" aria-label="Hide this error" onclick="dismissJob('${{j.id}}')">{use('ic-dismiss')}</button>` : ''}}"""
assert r.count(old3) == 1, ("job cancel/dismiss", r.count(old3))
r = r.replace(old3, new3)

open(research_path, 'w', encoding='utf-8').write(r)

# sanity: no bare emoji-only buttons should remain among the three glyphs we just converted
for path in (html_path, sources_path, research_path):
    content = open(path, encoding='utf-8').read()
    for glyph in ('>✕</button>', '>✓</button>', '>📌</button>'):
        assert glyph not in content, ("leftover emoji-only button", path, glyph)

print("f1_step2o_icon_sprite ok — 8 sites converted (js/sources.js + js/research.js), sprite + CSS added")
