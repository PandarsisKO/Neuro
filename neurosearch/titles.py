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

# A relative or coordinating clause after a comma is never part of a title, however short the part before it is.
# Measured: "the tool I want to revisit and have claude redesign is Neuro Search, which is a research tool" gave
# `Neuro Search Which a Research`, because "Neuro Search" is only two content words and the comma split needed
# three. The words below make the split unconditional.
RELATIVE = {"which", "who", "whose", "whom", "where", "when", "while", "because", "so", "and", "but", "although",
            "though", "since", "unless", "whereas"}

# An instruction verb at the FRONT of a title, dropped only when the length cap would otherwise eat the subject.
# Measured: "how do I describe a modern, beautiful website that focuses on…" gave `Describe a Modern Beautiful` —
# 35 characters trimmed to 34 by removing `Website`, the one word the title was about. Dropping the verb instead
# gives `Modern Beautiful Website`. Restricted to these words because the first word is usually the subject
# ("Stanislaus CPA Deal"), and dropping a subject to save a character would be the same mistake in reverse.
VERB_LEAD = {"describe", "explain", "design", "create", "build", "compare", "audit", "analyze", "analyse",
             "summarize", "summarise", "write", "list", "find", "identify", "review", "expand", "improve",
             "fix", "understand", "communicate", "research", "outline", "draft", "choose", "pick", "handle"}

# The words of FRAMING a request rather than of its subject. Measured on his 42 real chats: they produced
# `Wife Gio and Taking Ben`, `Mostly Interested in Laundromats`, `Supply with Data Regarding Current`,
# `Attached a Conversation with Josh`, `Dream Big for a Moment` — in each case the subject was sitting just past
# them. Dropped anywhere, like DROP, because framing can open a sentence or sit in the middle of one.
FRAMING = {"talk", "talks", "talked", "talking", "supply", "regarding", "curious", "moment", "dream",
           "attached", "attach", "mostly", "interested", "wanting", "taking", "essentially",
           "wife", "husband", "yet", "without", "knowing", "once", "both", "lot", "bit",
           "come", "idea", "ideas"}

# Cannot OPEN a title: once the framing is gone these are left stranded at the front (`What of Business
# Acquisition`, `If Start an LLC`). They may still appear inside one.
LEADING_JUNK = {"what", "which", "if", "whether", "how", "up"}

# A title that ends on one of these ends mid-phrase — the noun being qualified is the word that did not fit.
# Only ever applied when the cap actually cut something, so a title that legitimately ends here keeps its word.
WEAK_TAIL = {"what", "which", "out", "up", "set", "first", "current", "next", "more", "other", "such",
             "any", "every", "all", "own", "same", "one", "two", "type", "types", "kind",
             "private", "potential", "unique", "modern", "whole", "entire", "top", "main", "overall",
             "general", "specific", "certain", "various", "different", "several", "few"}


def _content(text: str) -> list[str]:
    """The words that could carry a subject — everything the title vocabularies do not throw away."""
    return [w for w in re.findall(r"[A-Za-z0-9']+", text)
            if w.lower() not in SMALL and w.lower() not in DROP and w.lower() not in FRAMING
            and w.lower() not in LEADING_JUNK]


def for_question(q: str, max_words: int = MAX_WORDS, max_chars: int = MAX_CHARS, _depth: int = 0) -> str:
    """A short noun-phrase title for a chat, from its first message."""
    s = (q or "").strip()
    if not s:
        return ""
    sentences = [x for x in re.split(r"(?<=[.!?])\s|\n+", s) if x.strip()]
    s = LEAD.sub("", sentences[0][:260]).strip(" ,;:-—")
    parts = re.split(r"[,:;]\s", s, maxsplit=1)
    head, tail = parts[0], (parts[1] if len(parts) > 1 else "")
    content_in_head = len(_content(head))
    next_word = (re.findall(r"[A-Za-z0-9']+", tail) or [""])[0].lower()
    if content_in_head >= 3 or (content_in_head >= 1 and next_word in RELATIVE):
        s = head                                                  # a clause that names its subject can stand alone
    # A lead sentence that names nothing is a preamble, and the subject is in the next one: "I want to dream big
    # for a moment. how can we have a private jet?" titled itself `Dream Big for a Moment` — everything except
    # what he asked about. Bounded to the two sentences after it so a long message cannot be walked.
    if len(_content(s)) < 2 and len(sentences) > 1 and _depth < 2:
        return for_question(" ".join(sentences[1:3]), max_words, max_chars, _depth + 1)
    toks = [t for t in re.findall(r"[A-Za-z0-9$%&/'’\-\.]+", s) if t]
    out: list[str] = []
    content = 0
    cut = False                                                   # did the cap leave words behind?
    for t in toks:
        low = t.lower().strip(".,")
        if low in DROP or low in FRAMING:
            continue
        if content == 0 and (low in SMALL or low in LEADING_JUNK):
            continue                                              # never open on a connector or a stranded "what"
        if content >= max_words:
            cut = True
            break
        out.append(t)
        if low not in SMALL:
            content += 1
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
    if len(" ".join(words)) > max_chars and words and words[0].lower() in VERB_LEAD:
        shorter = words[1:]
        while shorter and shorter[0].lower() in SMALL:
            shorter.pop(0)                                        # "a Modern Beautiful Website" → "Modern …"
        if shorter and len(" ".join(shorter)) <= max_chars:
            words = shorter                                       # lose the instruction, keep the subject
    if len(" ".join(words)) > max_chars:
        keep: list[str] = []
        for w in words:
            if len(" ".join(keep + [w])) > max_chars:
                break
            keep.append(w)
        words = keep or [words[0][:max_chars]]
        cut = True
    while len(words) > 1 and words[-1].lower() in SMALL:
        words.pop()                                               # never end on a connector, cap or no cap
    # Only when something was actually cut: a qualifier at the end qualified a word that did not fit, so the title
    # ends mid-phrase — `Questions to the Advisor on First`, `Attached a Conversation with Josh Private`.
    while cut and len(words) > 2 and words[-1].lower() in WEAK_TAIL:
        words.pop()
        while len(words) > 1 and words[-1].lower() in SMALL:
            words.pop()
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
