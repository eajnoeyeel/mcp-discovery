"""Description GEO Scorer — 6-dimension quality assessment.

Dimensions (equal weight 1/6 each):
  clarity            — first sentence specificity (GEO: Fluency Optimization)
  disambiguation     — NOT/AVOID keywords + vs/unlike comparisons
  parameter_coverage — parameter/input/accepts mentions
  boundary           — what the tool does NOT do
  stats              — numeric coverage/performance info (GEO: Statistics Addition)
  precision          — technical terms / standards / protocols (GEO: Technical Terms)
"""

from __future__ import annotations

import re

from pydantic import BaseModel


class GEOScore(BaseModel):
    """Six-dimension description quality score, each in [0, 1]."""

    clarity: float
    disambiguation: float
    parameter_coverage: float
    boundary: float
    stats: float
    precision: float
    total: float


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

_DISAMBIG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bNOT\b"),
    re.compile(r"\bAVOID\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:support|handle|perform|access|include)\b", re.IGNORECASE),
    re.compile(r"\b(?:unlike|vs\.?|versus|compared\s+to|in\s+contrast)\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\b", re.IGNORECASE),
    re.compile(r"\bcannot\b", re.IGNORECASE),
]

_BOUNDARY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bdoes\s+not\b", re.IGNORECASE),
    re.compile(r"\bNOT\b"),
    re.compile(r"\bcannot\b", re.IGNORECASE),
    re.compile(r"\bwon'?t\b", re.IGNORECASE),
    re.compile(r"\bunable\s+to\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\b", re.IGNORECASE),
    re.compile(r"\bexclud(?:e|es|ing)\b", re.IGNORECASE),
]

_PARAM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bparameters?\b", re.IGNORECASE),
    re.compile(r"\binputs?\b", re.IGNORECASE),
    re.compile(r"\baccepts?\b", re.IGNORECASE),
    re.compile(r"\barguments?\b", re.IGNORECASE),
    re.compile(r"\b\w+\s*\(\s*(?:string|int|bool|float|list|dict)", re.IGNORECASE),
    re.compile(r"\brequired\b", re.IGNORECASE),
    re.compile(r"\boptional\b", re.IGNORECASE),
]

_STATS_PATTERN = re.compile(
    r"\d+[\d,]*(?:\.\d+)?(?:\s*[%+MKBmkb]|\s*(?:million|billion|thousand))\b"
    r"|\b\d+(?:\.\d+)?%"
    r"|\bup\s+to\s+\d+"
    r"|\b\d+\s*\+\b",
    re.IGNORECASE,
)

_TECH_TERMS: set[str] = {
    "api",
    "rest",
    "graphql",
    "grpc",
    "http",
    "https",
    "websocket",
    "oauth",
    "jwt",
    "json",
    "xml",
    "yaml",
    "csv",
    "sql",
    "nosql",
    "postgresql",
    "mysql",
    "sqlite",
    "mongodb",
    "redis",
    "kafka",
    "docker",
    "kubernetes",
    "aws",
    "gcp",
    "azure",
    "tcp",
    "udp",
    "ssh",
    "ftp",
    "smtp",
    "dns",
    "ssl",
    "tls",
    "sha",
    "md5",
    "aes",
    "rsa",
    "doi",
    "isbn",
    "issn",
    "orcid",
    "arxiv",
    "html",
    "css",
    "dom",
    "svg",
    "pdf",
    "utf-8",
    "ascii",
    "unicode",
    "base64",
    "json-ld",
    "openapi",
    "swagger",
    "protobuf",
    "ci/cd",
    "sla",
    "slo",
    "rpc",
}

_VAGUE_WORDS: set[str] = {
    "things",
    "stuff",
    "data",
    "something",
    "everything",
    "various",
    "some",
    "general",
    "misc",
    "other",
}


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class DescriptionGEOScorer:
    """Score a tool description across 6 GEO-inspired dimensions."""

    def score(self, description: str | None) -> GEOScore:
        if not description or not description.strip():
            return GEOScore(
                clarity=0.0,
                disambiguation=0.0,
                parameter_coverage=0.0,
                boundary=0.0,
                stats=0.0,
                precision=0.0,
                total=0.0,
            )

        clarity = self._score_clarity(description)
        disambiguation = self._score_disambiguation(description)
        parameter_coverage = self._score_parameter_coverage(description)
        boundary = self._score_boundary(description)
        stats = self._score_stats(description)
        precision = self._score_precision(description)
        total = (clarity + disambiguation + parameter_coverage + boundary + stats + precision) / 6

        return GEOScore(
            clarity=clarity,
            disambiguation=disambiguation,
            parameter_coverage=parameter_coverage,
            boundary=boundary,
            stats=stats,
            precision=precision,
            total=total,
        )

    # -- dimension scorers --

    @staticmethod
    def _score_clarity(desc: str) -> float:
        """First-sentence specificity + word count + vagueness penalty."""
        first_sentence = desc.split(".")[0].strip()
        words = first_sentence.split()
        word_count = len(words)

        # Very short → low clarity
        if word_count <= 3:
            return 0.1

        # Length component: scales up to ~15 words
        length_score = min(word_count / 15, 1.0)

        # Vagueness penalty
        lower_words = {w.lower().strip(".,;:!?") for w in words}
        vague_overlap = lower_words & _VAGUE_WORDS
        vague_penalty = len(vague_overlap) * 0.2

        # Specificity: presence of nouns-like patterns (capitalized, hyphenated)
        specific_words = [w for w in words if len(w) > 3 and (w[0].isupper() or "-" in w)]
        specificity_bonus = min(len(specific_words) * 0.15, 0.4)

        return max(0.0, min(1.0, length_score - vague_penalty + specificity_bonus))

    @staticmethod
    def _score_disambiguation(desc: str) -> float:
        """Count disambiguation signals: NOT, AVOID, unlike, vs."""
        hits = sum(1 for p in _DISAMBIG_PATTERNS if p.search(desc))
        # 0 hits → 0.0, 1 → 0.4, 2 → 0.65, 3+ → 0.85+
        if hits == 0:
            return 0.0
        return min(0.3 + hits * 0.25, 1.0)

    @staticmethod
    def _score_parameter_coverage(desc: str) -> float:
        """Detect parameter/input/accepts mentions."""
        hits = sum(1 for p in _PARAM_PATTERNS if p.search(desc))
        if hits == 0:
            return 0.0
        return min(0.3 + hits * 0.2, 1.0)

    @staticmethod
    def _score_boundary(desc: str) -> float:
        """Detect negative-capability statements."""
        hits = sum(1 for p in _BOUNDARY_PATTERNS if p.search(desc))
        if hits == 0:
            return 0.0
        return min(0.3 + hits * 0.25, 1.0)

    @staticmethod
    def _score_stats(desc: str) -> float:
        """Count numeric / statistical mentions."""
        matches = _STATS_PATTERN.findall(desc)
        if not matches:
            return 0.0
        return min(0.3 + len(matches) * 0.2, 1.0)

    @staticmethod
    def _score_precision(desc: str) -> float:
        """Count recognized technical terms / standards / protocols."""
        words = set(re.findall(r"[\w./-]+", desc.lower()))
        hits = words & _TECH_TERMS
        if not hits:
            return 0.0
        return min(0.2 + len(hits) * 0.15, 1.0)
