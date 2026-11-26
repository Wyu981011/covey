"""How relevant and how useful a memory entry is (docs/butler.md 记忆): absolute similarity, the scope weights and one ranking.

Similarity is absolute, never relative to the best hit of the query: ``sim = score(q, d) / max(score(q, q), EPS)``,
the query scored as a document of its own being the most it can reach. Duplicate checks (a new entry against the old,
a question against the answered ones) take the smaller of the two directions (``mutual``). A hit also needs enough
words in common (``covered``): two different meaningful tokens, or one rare proper word or English symbol.

The ranking keeps only strong signals: ``hits`` (``covey memory show``, a question_dedup hit, the owner confirming, a
checkpoint's ``memory_used`` at half weight) against ``carried`` (the times its whole text went into a turn):
``u = min(1, (h + 1) / (e + 4))``, ``S = sim · (0.85 + 0.3·u) · freshness + 0.1·[e == 0 and sim ≥ 0.5]``, a fact
older than 60 days at freshness 0.8. Pure functions: core/memory_search.py ranks with them; HIGH_IDF and the
weights were checked on the private blind set (scripts/memory_eval.py).
"""
from __future__ import annotations

EPS = 1e-9
SCOPE_WEIGHTS = {"topic": 1.2, "project": 1.1, "global": 1.0, "other_project": 0.85, "done": 0.6}
MIN_TOKENS = 2  # Different meaningful tokens a hit shares with the query, unless one of them is rare (HIGH_IDF).
HIGH_IDF = 3.0
STALE_DAYS = 60
STALE_FRESHNESS = 0.8
NEW_BONUS = 0.1
NEW_BONUS_SIM = 0.5
SIGNAL_WEIGHTS = {"show": 1.0, "dedup": 1.0, "confirm": 1.0, "memory_used": 0.5}


def similarity(score_qd: float, score_qq: float) -> float:
    """``score(q, d)`` against the query's own score: 0 to 1 whatever else the corpus holds."""
    return max(0.0, min(1.0, float(score_qd) / max(float(score_qq), EPS)))


def mutual(score_ab: float, score_aa: float, score_ba: float, score_bb: float) -> float:
    """The smaller of a→b and b→a: two texts are duplicates only when each covers the other."""
    return min(similarity(score_ab, score_aa), similarity(score_ba, score_bb))


def covered(shared, idf: dict) -> bool:
    """Whether the tokens a hit shares with the query are enough: ``MIN_TOKENS`` different ones or one with idf ≥ ``HIGH_IDF``."""
    shared = set(shared)
    return len(shared) >= MIN_TOKENS or any(idf.get(token, 0.0) >= HIGH_IDF for token in shared)


def usefulness(hits: float, carried: int) -> float:
    return min(1.0, (float(hits) + 1.0) / (max(int(carried), 0) + 4.0))


def freshness(kind: str, verified_at: float, now: float) -> float:
    """1, or ``STALE_FRESHNESS`` for a fact (a note with a verification time) not verified for ``STALE_DAYS``."""
    if kind == "note" and verified_at and now - verified_at > STALE_DAYS * 86400:
        return STALE_FRESHNESS
    return 1.0


def rank(sim: float, hits: float, carried: int, fresh: float = 1.0) -> float:
    bonus = NEW_BONUS if carried == 0 and sim >= NEW_BONUS_SIM else 0.0
    return sim * (0.85 + 0.3 * usefulness(hits, carried)) * fresh + bonus
