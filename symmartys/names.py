"""Name matching shared by sanctions screening and LEI search.

Names are compared as sets of words: case, accents and punctuation folded, word order
ignored ("DOE, John" is "John Doe"), legal-form words dropped ("Deutsche Bank AG" is
"Deutsche Bank Aktiengesellschaft" is "Deutsche Bank"), and a long word may differ by a
typo. The score is in [0, 1]: 1.0 the same normalised string, 0.98 the same words in
another order, at most 0.97 otherwise — words that agree (a typo counts 0.9) over the
words in both, raised when every asked word is in a longer name.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

#: Articles and legal forms: they distinguish nothing a buyer means by a name.
STOPWORDS = frozenset({
    "the", "of", "and", "de", "der", "die", "das", "la", "le", "les", "el", "del",
    "ltd", "llc", "inc", "co", "corp", "corporation", "company", "limited", "plc", "llp",
    "lp", "jsc", "ojsc", "pjsc", "cjsc", "ooo", "oao", "zao", "sa", "sas", "sarl", "spa",
    "srl", "ag", "gmbh", "kg", "se", "nv", "bv", "ab", "as", "asa", "oy", "oyj", "fze",
    "fzco", "pte", "pty", "bhd", "sdn", "aktiengesellschaft", "gesellschaft", "mbh",
})


def norm_name(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text)).casefold()
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^\w]+", " ", t).replace("_", " ").split())


def tokens(text: str) -> frozenset[str]:
    # "S.p.A." normalises to "s p a": single letters are dropped with the stopwords.
    return frozenset(t for t in norm_name(text).split() if len(t) > 1 and t not in STOPWORDS)


def token_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.88


def score(query_tokens: frozenset[str], query_norm: str, name_tokens: frozenset[str],
          name_norm: str) -> float:
    if query_norm == name_norm:
        return 1.0
    if query_tokens and query_tokens == name_tokens:
        return 0.98
    # An exact word counts 1, a word within a typo of one counts 0.9 — so "Puttin" for
    # "Putin" can reach a hit, but never reads as the same name.
    weights = []
    for q in query_tokens:
        if q in name_tokens:
            weights.append(1.0)
        elif any(token_match(q, n) for n in name_tokens):
            weights.append(0.9)
    matched = len(weights)
    if matched == 0:
        return 0.0
    agreement = sum(weights) / matched
    union = len(query_tokens) + len(name_tokens) - matched
    s = sum(weights) / union
    if matched == len(query_tokens) and len(query_tokens) >= 2:
        # Every word asked for is in the name, which has more (a patronymic, a middle
        # name): "Vladimir Putin" against "Vladimir Vladimirovich Putin" is a real hit.
        s = max(s, 0.95 * agreement * (matched / len(name_tokens)) ** 0.2)
    return round(min(s, 0.97), 4)


def similarity(query: str, name: str) -> float:
    return score(tokens(query), norm_name(query), tokens(name), norm_name(name))


__all__ = ["STOPWORDS", "norm_name", "score", "similarity", "token_match", "tokens"]
