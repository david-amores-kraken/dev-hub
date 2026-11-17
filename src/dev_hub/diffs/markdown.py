"""Turn the PR description from Markdown into HTML, for the Preview tab.

GitHub renders more than plain Markdown: a few HTML tags (<details>, <summary>, <br>...) and
emoji shortcodes such as :rocket:. Both are handled here, nothing else from raw HTML is.

Comments are rendered the same way, plus GitHub's ```suggestion blocks: the lines the comment is
on, shown as removed, then the suggested lines, shown as added.
"""

from __future__ import annotations

import re
from typing import Any

import emoji
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markdown_it.utils import OptionsDict

# The tags GitHub lets through that make sense in a PR body. Only <details> may have an
# attribute (open). A tag with anything else on it is shown as text, not as a tag.
ALLOWED_TAGS = [
    "details",
    "summary",
    "br",
    "hr",
    "kbd",
    "sub",
    "sup",
    "b",
    "i",
    "em",
    "strong",
    "s",
    "del",
    "ins",
    "code",
    "p",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
]
_TAG = re.compile(r"<!--.*?-->|</?[A-Za-z][^<>]*>", re.DOTALL)
_ALLOWED = re.compile(
    rf"<(?P<close>/?)(?P<name>{'|'.join(ALLOWED_TAGS)})(?P<open>\s+open)?\s*/?>", re.IGNORECASE
)
_SHORTCODE = re.compile(r"(?<![\w:]):([\w+-]+):(?![\w:])")


def _escape(text: str) -> str:
    """Escape < and >, and any & that doesn't start an entity such as &amp;."""
    return re.sub(r"&(?!#?\w+;)", "&amp;", text).replace("<", "&lt;").replace(">", "&gt;")


def _safe_tag(tag: str) -> str:
    if tag.startswith("<!--"):
        return ""  # comments are hidden, as on GitHub
    found = _ALLOWED.fullmatch(tag)
    if not found or (found["open"] and (found["close"] or found["name"].lower() != "details")):
        return _escape(tag)
    # Rebuild the tag from its parts, so nothing else in the original can get through.
    return f"<{found['close']}{found['name'].lower()}{' open' if found['open'] else ''}>"


def clean_html(raw: str) -> str:
    out, position = [], 0
    for tag in _TAG.finditer(raw):
        out += [_escape(raw[position : tag.start()]), _safe_tag(tag.group())]
        position = tag.end()
    out.append(_escape(raw[position:]))
    return "".join(out)


def _render_html(
    self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: Any
) -> str:
    return clean_html(tokens[idx].content)


def _render_fence(
    self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: Any
) -> str:
    token = tokens[idx]
    if token.info.strip() != "suggestion":
        return self.fence(tokens, idx, options, env)
    quote = env.get("quote") if isinstance(env, dict) else None
    removed = quote.split("\n") if quote is not None else []
    added = token.content.removesuffix("\n").split("\n") if token.content else []
    rows = [_suggestion_line("del", line) for line in removed]
    rows += [_suggestion_line("add", line) for line in added]
    return (
        '<div class="suggestion"><div class="suggestion-head">Suggested change</div>'
        f'<div class="suggestion-lines">{"".join(rows)}</div></div>\n'
    )


def _suggestion_line(kind: str, line: str) -> str:
    return f'<div class="{kind}">{escapeHtml(line) or "&#8203;"}</div>'


def _shortcode(found: re.Match[str]) -> str:
    return emoji.emojize(found.group(), language="alias")


def _emojis(state: StateCore) -> None:
    """Swap :name: for the emoji in text. Code spans and code blocks aren't text, so stay as typed."""
    for block in state.tokens:
        for token in block.children or []:
            if token.type == "text":
                token.content = _SHORTCODE.sub(_shortcode, token.content)


# Like GitHub: tables and ~~strikethrough~~, with line breaks kept as written. Links that run
# code (javascript:) are not links. Images are off, so previewing a description never loads
# anything from the network.
_parser = (
    MarkdownIt("commonmark", {"html": True, "breaks": True, "linkify": False})
    .enable(["table", "strikethrough"])
    .disable("image")
)
_parser.add_render_rule("html_block", _render_html)
_parser.add_render_rule("html_inline", _render_html)
_parser.add_render_rule("fence", _render_fence)
_parser.core.ruler.push("emoji", _emojis)


def render(text: str, quote: str | None = None) -> str:
    """`quote` is the text of the lines a comment is on, which a suggestion replaces."""
    return _parser.render(text, {"quote": quote})
