"""A small tolerant HTML/XHTML tree over the standard library's HTMLParser (0.32.2 → its own module in 0.34.0).

Used wherever Neuro Search must read markup it does not control without a third-party dependency: old.reddit pages
(`reddit_html`), EPUB content documents (`epub`). Unclosed tags pop to the nearest matching ancestor; void elements
never nest; `Node.text()` renders block elements as line breaks.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Callable, Iterator

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCKS = {"p", "div", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "table"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None") -> None:
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def walk(self) -> Iterator["Node"]:
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()

    def find(self, pred: Callable[["Node"], bool], *, stop: Callable[["Node"], bool] | None = None) -> Iterator["Node"]:
        """Descendants matching `pred`; `stop` prunes a subtree (used to keep a comment's own body apart from its replies)."""
        for c in self.children:
            if isinstance(c, Node):
                if pred(c):
                    yield c
                if stop is None or not stop(c):
                    yield from c.find(pred, stop=stop)

    def first(self, pred: Callable[["Node"], bool], *, stop: Callable[["Node"], bool] | None = None) -> "Node | None":
        return next(self.find(pred, stop=stop), None)

    def text(self) -> str:
        parts: list[str] = []
        for c in self.children:
            if isinstance(c, Node):
                if c.tag in BLOCKS:
                    parts.append("\n")
                if c.tag != "script" and c.tag != "style":
                    parts.append(c.text())
                if c.tag in BLOCKS:
                    parts.append("\n")
            else:
                parts.append(c)
        return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", "".join(parts))).strip()


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        n = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag: str) -> None:
        n: Node | None = self.cur
        while n is not None and n.tag != tag:      # tolerate unclosed tags: pop to the nearest matching ancestor
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data: str) -> None:
        if data:
            self.cur.children.append(data)




def parse(html: str) -> Node:
    t = _Tree()
    t.feed(html)
    t.close()
    return t.root
