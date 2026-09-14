# -*- coding: utf-8 -*-
# F1 remaining item 2 of 3: width:auto -> .w-auto utility class.
# See docs/design-audit/2026-09-13-b85c222/f1-remaining-scope.md section 2 for full rationale.
#
# REWRITTEN 2026-09-13 after Codex's frontend split landed on main at 5f667a1 ("refactor:
# decompose static frontend into modules"). The 14 target sites are byte-identical to before,
# just relocated: the <style> block moved to neurosearch/web/styles.css, and the markup is still
# in neurosearch/web/index.html (now a 302-line shell). Re-verified fresh against 5f667a1: still
# exactly 14 sites, still all bare on <select> elements.
#
# DO NOT RUN without first re-confirming `git log --oneline -1 main` and a fresh
# `grep -rn 'style="width:auto"' neurosearch/web/` still show 14 sites in index.html — if Codex
# or anyone else has touched these files again since, re-verify before trusting this script.

# 1) add the utility class to styles.css, alongside the other single-property utilities.
css_path = 'neurosearch/web/styles.css'
css = open(css_path, encoding='utf-8').read()
old_css = """  .grow{flex:1}
  .push-right{margin-left:auto}
  .min-w-0{min-width:0}"""
new_css = """  .grow{flex:1}
  .push-right{margin-left:auto}
  .min-w-0{min-width:0}
  .w-auto{width:auto}"""
assert css.count(old_css) == 1, ("css block", css.count(old_css))
css = css.replace(old_css, new_css)
open(css_path, 'w', encoding='utf-8').write(css)

# 2) swap all 14 bare style="width:auto" attributes in index.html for class="w-auto".
# Each of the 14 <select> elements is bare (no existing class attribute to merge into), so this
# is a straight attribute-name swap, not a merge. Confirmed sites (by id): #candState, #discMode,
# #fbStatus, #fbImp, #fbUsed, #fbStale, #fbArea, #fbSort, #cwStatus, #cwStrength, #cwFresh,
# #cwSort, #resTargetS, #factKind.
html_path = 'neurosearch/web/index.html'
s = open(html_path, encoding='utf-8').read()
target = 'style="width:auto"'
n = s.count(target)
assert n == 14, ("width:auto count drifted from 14", n)
s = s.replace(target, 'class="w-auto"')
open(html_path, 'w', encoding='utf-8').write(s)

print("f1_step2n_width_auto ok — 14 sites converted in index.html, .w-auto class added to styles.css")
