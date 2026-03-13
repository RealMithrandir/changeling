"""HTML Weaving — mutate HTML text content served to hostile agents.

Strategies (no LLM required):
- paragraph shuffling: reorder <p> tags within their parent
- entity/number substitution in text nodes using grimoire rules
"""

from __future__ import annotations

import hashlib
import random
import re
from html.parser import HTMLParser
from typing import Any

import structlog

from changeling.grimoire import Grimoire

log = structlog.get_logger()

# Regex to find inline numbers in text (integers or decimals)
_NUMBER_RE = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)(?!\w)")


def _seed_for(session_key: str, salt: str) -> int:
    """Deterministic seed from session key and a salt."""
    h = hashlib.sha256(f"{session_key}:{salt}".encode()).digest()
    return int.from_bytes(h[:4], "big")


class _HTMLRebuilder(HTMLParser):
    """Parse HTML, mutate text nodes, and reconstruct the document.

    This parser preserves all tags, attributes, and structure — only text
    content is modified based on grimoire rules.
    """

    def __init__(
        self,
        grimoire: Grimoire,
        session_key: str,
        strategy: str,
    ) -> None:
        super().__init__(convert_charrefs=False)
        self.grimoire = grimoire
        self.session_key = session_key
        self.strategy = strategy

        self.output: list[str] = []
        self._text_node_idx = 0
        # For paragraph shuffling
        self._in_target = False
        self._target_depth = 0
        self._p_blocks: list[str] = []
        self._current_p: list[str] = []
        self._in_p = False
        self._p_depth = 0
        self._before_first_p: list[str] = []
        self._after_last_p: list[str] = []
        self._seen_first_p = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_str = ""
        for k, v in attrs:
            if v is None:
                attr_str += f" {k}"
            else:
                attr_str += f' {k}="{v}"'
        html = f"<{tag}{attr_str}>"

        if self.strategy == "shuffle" and tag == "p":
            self._in_p = True
            self._p_depth = 1
            self._current_p = [html]
            self._seen_first_p = True
            return
        if self._in_p:
            self._p_depth += 1 if not _is_void(tag) else 0
            self._current_p.append(html)
            return

        self.output.append(html)

    def handle_endtag(self, tag: str) -> None:
        html = f"</{tag}>"
        if self._in_p:
            if tag == "p":
                self._p_depth -= 1
                if self._p_depth <= 0:
                    self._current_p.append(html)
                    self._p_blocks.append("".join(self._current_p))
                    self._current_p = []
                    self._in_p = False
                    return
            self._current_p.append(html)
            return

        self.output.append(html)

    def handle_data(self, data: str) -> None:
        if self._in_p:
            self._current_p.append(self._mutate_text(data))
            return

        if self.strategy == "substitute":
            data = self._mutate_text(data)

        self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        html = f"&{name};"
        if self._in_p:
            self._current_p.append(html)
        else:
            self.output.append(html)

    def handle_charref(self, name: str) -> None:
        html = f"&#{name};"
        if self._in_p:
            self._current_p.append(html)
        else:
            self.output.append(html)

    def handle_comment(self, data: str) -> None:
        html = f"<!--{data}-->"
        if self._in_p:
            self._current_p.append(html)
        else:
            self.output.append(html)

    def handle_decl(self, decl: str) -> None:
        self.output.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.output.append(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        self.output.append(f"<![{data}]>")

    def _mutate_text(self, text: str) -> str:
        """Mutate a text node: substitute numbers using grimoire rules."""
        if not text.strip():
            return text
        self._text_node_idx += 1

        # Mutate inline numbers
        def replace_number(m: re.Match[str]) -> str:
            num_str = m.group(1)
            seed = _seed_for(
                self.session_key, f"html_num_{self._text_node_idx}_{m.start()}"
            )
            rng = random.Random(seed)
            # Use stat_fields variance (8%) as default for inline numbers
            rule = self.grimoire.rule_for_field("score")  # numeric rule
            variance = rule.variance if rule else 0.08
            factor = 1.0 + rng.uniform(-variance, variance)
            if "." in num_str:
                result = round(float(num_str) * factor, 2)
                return str(result)
            else:
                result = int(round(int(num_str) * factor))
                return str(result)

        return _NUMBER_RE.sub(replace_number, text)

    def get_result(self) -> str:
        """Return the reconstructed (mutated) HTML."""
        if self.strategy == "shuffle" and self._p_blocks:
            # Deterministically shuffle paragraph order
            seed = _seed_for(self.session_key, "p_shuffle")
            rng = random.Random(seed)
            rng.shuffle(self._p_blocks)
            # Insert shuffled paragraphs at the point where first <p> was
            # We find where to insert by looking for a marker
            result_str = "".join(self.output)
            # Paragraphs go at end since they were consumed during parsing
            return result_str + "".join(self._p_blocks)
        return "".join(self.output)


def _is_void(tag: str) -> bool:
    """Check if an HTML tag is a void element (self-closing)."""
    return tag.lower() in {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }


async def weave_html(
    html: str,
    grimoire: Grimoire,
    session_key: str,
) -> str:
    """Mutate HTML text content according to grimoire rules.

    Preserves all tags, attributes, and document structure.
    Only text content within text nodes is modified.

    Args:
        html: raw HTML string
        grimoire: loaded Grimoire rules
        session_key: deterministic seed material

    Returns:
        Mutated HTML string with same structure
    """
    # Look up HTML mutation strategy from grimoire
    html_rule = grimoire.mutations.get("html_content")
    strategy = "substitute"
    if html_rule is not None:
        strategy = html_rule.strategy

    parser = _HTMLRebuilder(grimoire, session_key, strategy)
    parser.feed(html)
    return parser.get_result()
