"""Turn the PR description from Markdown into HTML, for the Preview tab."""

from __future__ import annotations

from markdown_it import MarkdownIt

# Like GitHub: tables and ~~strikethrough~~, with line breaks kept as written. Raw HTML in the
# text is escaped, not passed through, and links that run code (javascript:) are not links.
# Images are off, so previewing a description never loads anything from the network.
_parser = (
    MarkdownIt("commonmark", {"html": False, "breaks": True, "linkify": False})
    .enable(["table", "strikethrough"])
    .disable("image")
)


def render(text: str) -> str:
    return _parser.render(text)
