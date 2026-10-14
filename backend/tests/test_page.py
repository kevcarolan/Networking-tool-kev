"""The page shell (static/index.html): every dialog closed and none inside another (a
dialog inside a closed one can never show), and no id used twice."""

from collections import Counter
from html.parser import HTMLParser

from app.main import STATIC_DIR


class _Dialogs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.open: list[str] = []
        self.nested: list[tuple[str, str]] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "dialog":
            if self.open:
                self.nested.append((a.get("id", "?"), self.open[-1]))
            self.open.append(a.get("id", "?"))

    def handle_endtag(self, tag):
        if tag == "dialog" and self.open:
            self.open.pop()


def test_dialogs_are_closed_and_ids_unique():
    p = _Dialogs()
    p.feed((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    assert p.nested == [] and p.open == []
    assert [i for i, n in Counter(p.ids).items() if n > 1] == []
