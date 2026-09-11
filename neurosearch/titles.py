"""Name a chat the way a person would ($0, deterministic, no model call).

Kyle: *"can you find a better way for the chats to name themselves? the names are too wordy."* They were his first
question, truncated: `title=question[:80]`. Measured across his 40 most recent conversations — mean **54
characters**, with a hard cluster at exactly 60, cut mid-word:

    [60] how would I tell claude to design the web app as if Apple, T
    [60] what are some unique ways I can free up some funds for purchas
    [60] ELI5 - how do we pay ourselves? how do use SMB acquisition t

And the *good* titles in that same list are the ones he had renamed by hand — **"CPA Fees"** (8), **"Emails with
Josh"** (16), **"CPA Cim Stanislaus"** (18), **"Fax Machine to Modern Tools"** (27). So the target shape was not a
matter of taste to be guessed at: it was already in his data. A short noun phrase, two to four words, no question
scaffolding, never cut mid-word.

Three rules do almost all the work, and each was added because a measured output was bad without it:

* **Strip the asking, keep the subject.** `LEAD` removes the question frame from the front ("how would I", "what
  are some", "can you", "I need you to", "ELI5 -"), and `DROP` removes pronouns, auxiliaries and the verbs of
  asking *wherever* they appear — the first version kept them and produced `Deal I Need You`, `Questions That We
  Did`, `Unique I Can Free`. A title is a subject, so "I", "need" and "you" can never be in one.
* **A clause that already names its subject can stand alone**, so a title stops at the first comma or colon — but
  only after the scaffolding has been removed and only if three content words survive. Applying that split first
  turned "describe a modern, beautiful website" into `Describe a Modern`, losing the website.
* **Never end on a connector**, before or after the length cap. `Claude to Effectively Audit the` and `Invest in
  Service or` both came from trimming in the wrong order.

Caps are 4 content words and 34 characters, chosen by comparison rather than by feel: 5 words / 38 characters was
tried on the same 23 real questions and produced `Claude to Design the Web App as If`, `Gotchas Red Flags Warnings
to Out`, `Claude to Effectively Audit the Web`. The tighter cap is not a compromise — it is the better title.

**No model call.** A one-line title is the last thing worth paying for, it would add latency to the first message
of every chat, and the measured result here is good enough that a paid version would be hard to tell apart.
Anything this gets wrong, the user can rename in one click — which is where the good titles in his list came from
in the first place.
"""
from __future__ import annotations

import re

MAX_WORDS = 4
MAX_CHARS = 34

# Kept lowercase inside a title, and never allowed to end one.
SMALL = {"a", "an", "the", "of", "to", "with", "for", "and", "or", "nor", "but", "in", "on", "at", "by", "from",
         "as", "vs", "into", "about", "per", "via"}

# The question frame, removed from the FRONT only: everything here is how a request opens, not what it is about.
LEAD = re.compile(r"""^(?:\s*(?:
 please|ok|okay|so|hi|hey|
 i\s+(?:have|had|need|want|wanted|am|was|would|will|think|feel|noticed|wonder|wondered|
       am\s+curious|was\s+curious|would\s+like|need\s+you\s+to|want\s+you\s+to)|
 we\s+(?:have|had|need|want|wanted|are|were|would)|
 my\s+\w+\s+(?:had|has|have|is|was)|
 can\s+you|could\s+you|would\s+you|will\s+you|
 what(?:'s| is| are| were| was)?(?:\s+some)?(?:\s+the)?|
 how(?:\s+(?:do|does|would|will|can|could|should|much|many))?(?:\s+i|\s+we|\s+you)?|
 why(?:\s+(?:do|does|is|are|would))?|when(?:\s+(?:do|does|is|are))?|where(?:\s+(?:do|does|is|are))?|
 which|who|
 eli5\s*[-:—]?|
 tell\s+me(?:\s+about)?|give\s+me|show\s+me|help\s+me|
 for\s+the|in\s+the|on\s+the|about\s+the|regarding|
 one\s+idea\s+i\s+have\s+is\s+to|
 the\s+\w+\s+i\s+want\s+to\s+\w+(?:\s+and\s+\w+\s+\w+\s+\w+)?\s+is|
 if\s+i\s+(?:am|was|were)\s+\w+|
 is|are|do|does|should|could
)\b[\s,:;-]*)+""", re.I | re.X)

# Dropped anywhere: filler adjectives, and the pronouns/auxiliaries/verbs-of-asking that made the first version
# produce "Deal I Need You" instead of "Deal to Evaluate".
DROP = {"some", "good", "best", "better", "kind", "kinds", "sort", "sorts", "type", "types", "thing", "things",
        "stuff", "way", "ways", "really", "just", "actually", "basically", "etc", "also", "very", "much", "many",
        "potential", "new", "unique",
        "i", "we", "you", "he", "she", "they", "it", "me", "us", "them", "my", "our", "your", "his", "her",
        "their", "its",
        "am", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "doing", "have", "has", "had",
        "can", "could", "would", "should", "will", "shall", "may", "might", "must",
        "need", "needs", "want", "wants", "wanted", "like", "think", "thinks", "tell", "give", "show", "help",
        "get", "gets", "got", "make", "makes", "let", "know", "knows", "say", "says", "said", "ask", "asks",
        "asked", "use", "uses", "used", "take", "takes", "look", "looks",
        "that", "this", "these", "those", "there", "here", "not"}


def for_question(q: str, max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS) -> str:
    """A short noun-phrase title for a chat, from its first message."""
    s = (q or "").strip()
    if not s:
        return ""
    s = re.split(r"(?<=[.!?])\s|\n", s)[0][:260]                  # the lead sentence only
    s = LEAD.sub("", s).strip(" ,;:-—")
    head = re.split(r"[,:;]\s", s)[0]
    if len([w for w in re.findall(r"[A-Za-z0-9']+", head)
            if w.lower() not in SMALL and w.lower() not in DROP]) >= 3:
        s = head                                                  # a clause that names its subject can stand alone
    toks = [t for t in re.findall(r"[A-Za-z0-9$%&/'’\-\.]+", s) if t]
    out: list[str] = []
    content = 0
    for t in toks:
        low = t.lower().strip(".,")
        if low in DROP:
            continue
        if content == 0 and low in SMALL:
            continue                                              # never open on a connector
        out.append(t)
        if low not in SMALL:
            content += 1
        if content >= max_words:
            break
    words: list[str] = []
    for i, t in enumerate(out):
        clean = t.strip(".,")
        if not clean:
            continue
        if clean.isupper() and len(clean) > 1:
            words.append(clean)                                   # CPA, SBA, CIM, B2B, SDE stay as written
        elif clean.lower() in SMALL and i > 0:
            words.append(clean.lower())
        else:
            w = clean[:1].upper() + clean[1:]
            words.append(re.sub(r"([/\-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), w))
    if len(" ".join(words)) > max_chars:
        keep: list[str] = []
        for w in words:
            if len(" ".join(keep + [w])) > max_chars:
                break
            keep.append(w)
        words = keep or [words[0][:max_chars]]
    while len(words) > 1 and words[-1].lower() in SMALL:
        words.pop()                                               # never end on a connector, cap or no cap
    return " ".join(words) or s[:max_chars].strip() or (q or "").strip()[:max_chars]


def looks_autogenerated(title: str, first_question: str) -> bool:
    """Was this title made by the old rule (the question, truncated) rather than typed by the user?

    Only such titles may be replaced by a backfill. A title the user wrote is the best one in the list — "CPA Fees",
    "Emails with Josh" — and overwriting it would be worse than leaving every old title alone."""
    t, q = (title or "").strip(), (first_question or "").strip()
    if not t or not q:
        return False
    if t == q or q.startswith(t):
        return True                                               # a literal prefix of the question
    return t.rstrip(" .…") == q[:len(t.rstrip(' .…'))].rstrip(" .…")
