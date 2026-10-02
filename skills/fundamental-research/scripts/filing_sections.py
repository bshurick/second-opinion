"""SEC filing reader: convert a 10-K / 10-Q document (HTML or text) to text,
split it into Items (skipping the table of contents), return one Item,
search for passages, or diff an Item against the prior filing.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python filing_sections.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "action": "split" | "item" | "search" | "diff",
      "document": "<html or plain text of the filing>",   # required
      "previous": "<prior filing>",                       # diff only
      "item": "1A",                                       # item / diff
      "query": "margin", "context": 200, "max_hits": 20,  # search
      "max_chars": 20000                                  # item
    }

Output JSON contract (stdout)::

    split  -> {form_type_guess, total_words, preview,
               items: [{item, title, words, chars, start}]}       # document order
    item   -> {item, title, text, chars, words, truncated}
    search -> {query, count, by_item: {item: n}, hits: [{item, position, snippet}]}
    diff   -> {item, previous_words, current_words, word_delta, similarity,
               added_sentences, removed_sentences, added_count, removed_count}

Method: HTML is reduced to text with the standard-library parser (script,
style and the inline-XBRL hidden header dropped, block elements become lines,
table cells joined with
spaces, entities decoded, curly quotes straightened). Item headings are
lines starting "Item <number><letter>" ("Part I, Item 1A" also counts).
Filings list every Item in a table of contents, so for each Item the
occurrence with the most text before the next heading is taken as the
real section. The form type is guessed from "10-K"/"10-Q" in the text or
from the Item layout (10-Qs put Financial Statements in Item 1 and the
MD&A in Item 2). Diff splits the Item into sentences, reports sentences
present in one filing but not the other, and a sequence similarity ratio
(1.0 = identical). Word counts are whitespace tokens.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
from difflib import SequenceMatcher
from html.parser import HTMLParser

_ACTIONS = ("diff", "item", "search", "split")
_BLOCK = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "section",
    "article",
    "header",
    "footer",
    "ul",
    "ol",
    "hr",
    "blockquote",
    "pre",
    "title",
}
_CELL = {"td", "th"}
_SKIP = {"script", "style", "head", "noscript", "ix:header", "ix:hidden"}
_HEADING = re.compile(
    r"^\s*(?:part\s+[ivx]+\s*[,.\-–—:]?\s*)?item\s*(\d{1,2}[a-c]?)\s*[.:\-–—]?\s*(.*)$",
    re.IGNORECASE,
)
_PAGE_TAIL = re.compile(r"[\s.…]*\d{1,3}\s*$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_SHORT_BODY = 50
_TOC_MIN_HEADINGS = 4
_TOC_MAX_BODY = 200
_QUOTES = {"’": "'", "‘": "'", "“": '"', "”": '"', "\xa0": " ", " ": " ", "​": ""}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        elif tag in _CELL:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        elif tag in _CELL:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def to_text(document: str) -> str:
    """Filing text: HTML reduced to lines, or the input normalized when it is already text."""
    if re.search(r"<\s*(html|body|div|p|table|span)\b", document, re.IGNORECASE):
        parser = _Text()
        parser.feed(document)
        raw = "".join(parser.parts)
    else:
        raw = html_lib.unescape(document)
    for a, b in _QUOTES.items():
        raw = raw.replace(a, b)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in raw.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _clean_title(title: str) -> str:
    t = _PAGE_TAIL.sub("", title).strip(" .:-–—")
    if t and t == t.upper() and any(c.isalpha() for c in t):
        t = t.title()
    return t


def split_items(text: str) -> list[dict]:
    """Real Item sections in document order: [{item, title, start, end, text}]."""
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    heads = []
    for i, ln in enumerate(lines):
        m = _HEADING.match(ln)
        if m and len(ln) < 200:
            heads.append({"item": m.group(1).upper(), "title": _clean_title(m.group(2)), "line": i})
    for k, h in enumerate(heads):
        nxt = heads[k + 1]["line"] if k + 1 < len(heads) else len(lines)
        h["body"] = "\n".join(lines[h["line"] + 1 : nxt]).strip()
    # The table of contents is the run of leading headings before the first heading
    # with a substantial body (the first real section). Occurrences inside it lose to
    # any occurrence outside it; among the rest the longest body wins and ties go to
    # the later one.
    toc: set[int] = set()
    first_real = next((k for k, h in enumerate(heads) if len(h["body"]) >= _TOC_MAX_BODY), None)
    if first_real is not None and first_real >= _TOC_MIN_HEADINGS:
        toc = set(range(first_real))
    best: dict[str, dict] = {}
    for k, h in enumerate(heads):
        cur = best.get(h["item"])
        rank = (k not in toc, len(h["body"]) if len(h["body"]) >= _SHORT_BODY else 0, h["line"])
        if cur is None or rank > cur["_rank"]:
            best[h["item"]] = {**h, "_rank": rank}
    ordered = sorted(best.values(), key=lambda h: h["line"])
    return [
        {"item": h["item"], "title": h["title"], "start": offsets[h["line"]], "text": h["body"]}
        for h in ordered
    ]


def _guess_form(text: str, items: list[dict]) -> str | None:
    head = text[:5000].upper()
    for form in ("10-Q", "10-K", "20-F", "40-F", "8-K"):
        if f"FORM {form}" in head or f"FORM {form.replace('-', ' ')}" in head:
            return form
    for form in ("10-Q", "10-K"):
        if form in head:
            return form
    order = [i["item"] for i in items]
    titles = {i["item"]: i["title"].lower() for i in items}
    # a 10-Q repeats Item 1A (Risk Factors) in Part II, after Part I's Items 1-4
    if "1A" in order and any(
        x in order and order.index("1A") > order.index(x) for x in ("2", "3", "4")
    ):
        return "10-Q"
    if "management" in titles.get("2", "") or "financial statements" in titles.get("1", ""):
        return "10-Q"
    return "10-K" if items else None


def _words(s: str) -> int:
    return len(s.split())


def _sentences(s: str) -> list[str]:
    return [x.strip() for x in _SENTENCE.split(s.replace("\n", " ")) if x.strip()]


def _unique(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _find(items: list[dict], item: str) -> dict:
    key = str(item).strip().upper()
    for i in items:
        if i["item"] == key:
            return i
    raise ValueError(
        f"item {key} not found; available: {', '.join(i['item'] for i in items) or 'none'}"
    )


def run_filing_sections(params: dict) -> dict:
    """Dispatch on ``params['action']``; raises ValueError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    action = params.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(_ACTIONS)}")
    document = params.get("document")
    if not isinstance(document, str) or not document.strip():
        raise ValueError("document is required (the filing's HTML or text)")
    text = to_text(document)
    items = split_items(text)

    if action == "split":
        return {
            "form_type_guess": _guess_form(text, items),
            "total_words": _words(text),
            "preview": text[:300],
            "items": [
                {
                    "item": i["item"],
                    "title": i["title"],
                    "words": _words(i["text"]),
                    "chars": len(i["text"]),
                    "start": i["start"],
                }
                for i in items
            ],
        }
    if action == "item":
        if not params.get("item"):
            raise ValueError("item is required (for example 1A or 7)")
        sec = _find(items, params["item"])
        max_chars = int(params.get("max_chars") or 20000)
        body = sec["text"]
        return {
            "item": sec["item"],
            "title": sec["title"],
            "text": body[:max_chars],
            "chars": len(body),
            "words": _words(body),
            "truncated": len(body) > max_chars,
        }
    if action == "search":
        query = str(params.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        context = int(params.get("context") or 200)
        max_hits = int(params.get("max_hits") or 20)
        hits, by_item, count = [], {}, 0
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        for sec in items or [{"item": None, "title": "", "text": text}]:
            body = sec["text"]
            for m in pattern.finditer(body):
                count += 1
                by_item[sec["item"]] = by_item.get(sec["item"], 0) + 1
                if len(hits) < max_hits:
                    a, b = max(0, m.start() - context), min(len(body), m.end() + context)
                    hits.append(
                        {
                            "item": sec["item"],
                            "position": m.start(),
                            "snippet": body[a:b].replace("\n", " "),
                        }
                    )
        return {"query": query, "count": count, "by_item": by_item, "hits": hits}
    # diff
    if not params.get("item"):
        raise ValueError("item is required for a diff")
    previous = params.get("previous")
    if not isinstance(previous, str) or not previous.strip():
        raise ValueError("previous is required (the prior filing's HTML or text)")
    cur = _find(items, params["item"])
    prev = _find(split_items(to_text(previous)), params["item"])
    max_chars = int(params.get("max_chars") or 20000)
    cur_s, prev_s = _sentences(cur["text"]), _sentences(prev["text"])
    added = _unique([s for s in cur_s if s not in set(prev_s)])
    removed = _unique([s for s in prev_s if s not in set(cur_s)])
    return {
        "item": cur["item"],
        "title": cur["title"],
        "text": cur["text"][:max_chars],
        "truncated": len(cur["text"]) > max_chars,
        "previous_words": _words(prev["text"]),
        "current_words": _words(cur["text"]),
        "word_delta": _words(cur["text"]) - _words(prev["text"]),
        "similarity": round(SequenceMatcher(None, prev_s, cur_s).ratio(), 4),
        "added_sentences": added[:50],
        "removed_sentences": removed[:50],
        "added_count": len(added),
        "removed_count": len(removed),
    }


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_filing_sections(json.loads(raw))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
