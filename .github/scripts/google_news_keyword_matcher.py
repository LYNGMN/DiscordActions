"""Safe keyword-expression matching for Google News RSS items."""

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


MATCH_MODES = {"title", "title_or_description"}
_DATE_FILTER = re.compile(
    r"(?i)(?<!\S)(?:when|after|before):[^\s()]+"
)
_ASCII_ALNUM = re.compile(r"[a-z0-9]")
_ASCII_WORD = re.compile(r"[a-z0-9]")

TERM = "TERM"
AND = "AND"
OR = "OR"
NOT = "NOT"
LPAREN = "LPAREN"
RPAREN = "RPAREN"


@dataclass(frozen=True)
class KeywordMatchResult:
    matched: bool
    matched_field: Optional[str]
    matched_terms: Tuple[str, ...]


@dataclass(frozen=True)
class CompiledKeywordMatch:
    expression: str
    ast: Any
    terms: Tuple[str, ...]

    def matches(self, text: str) -> bool:
        normalized = _normalize(text)
        return bool(normalized) and _evaluate(self.ast, normalized)

    def matching_terms(self, text: str) -> Tuple[str, ...]:
        normalized = _normalize(text)
        if not normalized or not _evaluate(self.ast, normalized):
            return ()
        return tuple(term for term in self.terms if _term_matches(term, normalized))


def extract_keyword_query(keyword: str = "", rss_url: str = "") -> str:
    if isinstance(keyword, str) and keyword.strip():
        return keyword.strip()
    if not isinstance(rss_url, str) or not rss_url.strip():
        raise ValueError("keyword query is required")
    try:
        values = parse_qs(urlsplit(rss_url).query, keep_blank_values=True).get("q", [])
    except ValueError:
        raise ValueError("keyword query is required") from None
    if not values or not values[0].strip():
        raise ValueError("keyword query is required")
    return values[0].strip()


def compile_keyword_match(
    base_query: str,
    aliases: str = "",
) -> CompiledKeywordMatch:
    base = _strip_date_filters(base_query)
    extra = aliases.strip() if isinstance(aliases, str) else ""
    if not base:
        raise ValueError("invalid keyword expression")
    expression = "({}) OR ({})".format(base, extra) if extra else base
    tokens = _insert_implicit_and(_tokenize(expression))
    ast = _Parser(tokens).parse()
    terms = tuple(dict.fromkeys(_collect_terms(ast)))
    return CompiledKeywordMatch(expression=expression, ast=ast, terms=terms)


def match_google_news_item(
    title: str,
    description_html: str,
    compiled: CompiledKeywordMatch,
    mode: str = "title",
) -> KeywordMatchResult:
    if mode not in MATCH_MODES:
        raise ValueError("invalid keyword match mode")

    article_title = _article_title_without_publisher(title)
    if compiled.matches(article_title):
        title_terms = compiled.matching_terms(article_title)
        return KeywordMatchResult(True, "title", title_terms)

    if mode == "title_or_description":
        for related_title in _description_article_titles(description_html):
            if compiled.matches(related_title):
                terms = compiled.matching_terms(related_title)
                return KeywordMatchResult(True, "description", terms)
    return KeywordMatchResult(False, None, ())


def keyword_filter_fingerprint(
    compiled: CompiledKeywordMatch,
    mode: str,
) -> str:
    if mode not in MATCH_MODES:
        raise ValueError("invalid keyword match mode")
    value = "{}\n{}".format(mode, compiled.expression)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _article_title_without_publisher(value: str) -> str:
    if not isinstance(value, str):
        return ""
    title, separator, _publisher = value.rpartition(" - ")
    return title if separator and title.strip() else value


def _description_article_titles(value: str) -> Tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        return ()
    soup = BeautifulSoup(value, "html.parser")
    titles = []
    for anchor in soup.find_all("a"):
        title = anchor.get_text(" ", strip=True)
        if title:
            titles.append(title)
    return tuple(titles)


def _strip_date_filters(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid keyword expression")
    return " ".join(_DATE_FILTER.sub(" ", value).split())


def _normalize(value: str) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    return " ".join(normalized.split())


def _term_matches(term: str, text: str) -> bool:
    needle = _normalize(term)
    if not needle:
        return False
    if not _ASCII_ALNUM.search(needle):
        return needle in text
    pattern = re.escape(needle).replace(r"\ ", r"\s+")
    if _ASCII_WORD.match(needle[0]):
        pattern = r"(?<![a-z0-9])" + pattern
    if _ASCII_WORD.match(needle[-1]):
        pattern += r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _tokenize(expression: str) -> List[Tuple[str, str]]:
    tokens = []
    index = 0
    length = len(expression)
    while index < length:
        character = expression[index]
        if character.isspace():
            index += 1
            continue
        if character == "(":
            tokens.append((LPAREN, character))
            index += 1
            continue
        if character == ")":
            tokens.append((RPAREN, character))
            index += 1
            continue
        if character in "|&!":
            tokens.append(({"|": OR, "&": AND, "!": NOT}[character], character))
            index += 1
            continue
        if character == "-" and (
            index == 0 or expression[index - 1].isspace() or expression[index - 1] == "("
        ):
            tokens.append((NOT, character))
            index += 1
            continue
        if character == '"':
            index += 1
            start = index
            escaped = False
            pieces = []
            while index < length:
                current = expression[index]
                if escaped:
                    pieces.append(current)
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    break
                else:
                    pieces.append(current)
                index += 1
            if index >= length or expression[index] != '"':
                raise ValueError("invalid keyword expression")
            value = "".join(pieces).strip()
            if not value or index == start:
                raise ValueError("invalid keyword expression")
            tokens.append((TERM, value))
            index += 1
            continue

        start = index
        while index < length:
            current = expression[index]
            if current.isspace() or current in "()|&!\"":
                break
            index += 1
        value = expression[start:index].strip()
        if not value:
            raise ValueError("invalid keyword expression")
        operator = value.upper()
        if operator in {AND, OR, NOT}:
            tokens.append((operator, value))
        else:
            tokens.append((TERM, value))
    if not tokens:
        raise ValueError("invalid keyword expression")
    return tokens


def _insert_implicit_and(
    tokens: Sequence[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    prepared = []
    for token in tokens:
        if prepared:
            previous = prepared[-1][0]
            current = token[0]
            if previous in {TERM, RPAREN} and current in {TERM, LPAREN, NOT}:
                prepared.append((AND, "AND"))
        prepared.append(token)
    return prepared


class _Parser:
    def __init__(self, tokens: Sequence[Tuple[str, str]]):
        self.tokens = list(tokens)
        self.index = 0

    def parse(self) -> Any:
        try:
            value = self._parse_or()
        except (IndexError, RecursionError):
            raise ValueError("invalid keyword expression") from None
        if self.index != len(self.tokens):
            raise ValueError("invalid keyword expression")
        return value

    def _parse_or(self) -> Any:
        value = self._parse_and()
        while self._accept(OR):
            value = (OR, value, self._parse_and())
        return value

    def _parse_and(self) -> Any:
        value = self._parse_unary()
        while self._accept(AND):
            value = (AND, value, self._parse_unary())
        return value

    def _parse_unary(self) -> Any:
        if self._accept(NOT):
            return (NOT, self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Any:
        if self._accept(LPAREN):
            value = self._parse_or()
            if not self._accept(RPAREN):
                raise ValueError("invalid keyword expression")
            return value
        if self.index >= len(self.tokens) or self.tokens[self.index][0] != TERM:
            raise ValueError("invalid keyword expression")
        token = self.tokens[self.index]
        self.index += 1
        return (TERM, token[1])

    def _accept(self, token_type: str) -> bool:
        if self.index < len(self.tokens) and self.tokens[self.index][0] == token_type:
            self.index += 1
            return True
        return False


def _evaluate(ast: Any, text: str) -> bool:
    operator = ast[0]
    if operator == TERM:
        return _term_matches(ast[1], text)
    if operator == NOT:
        return not _evaluate(ast[1], text)
    if operator == AND:
        return _evaluate(ast[1], text) and _evaluate(ast[2], text)
    if operator == OR:
        return _evaluate(ast[1], text) or _evaluate(ast[2], text)
    raise ValueError("invalid keyword expression")


def _collect_terms(ast: Any) -> List[str]:
    operator = ast[0]
    if operator == TERM:
        return [ast[1]]
    if operator == NOT:
        return _collect_terms(ast[1])
    return _collect_terms(ast[1]) + _collect_terms(ast[2])
