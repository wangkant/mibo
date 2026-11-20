"""Tests for hybrid retrieval: lexical, embedding, scope and recency.

The ranking math is checked on hand-built rows; the embedding path through a
real agent, against an /embeddings endpoint served by httpx.MockTransport with
hand-picked vectors. Nothing here reaches a network or needs a key.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from mibo import embeddings, ranking
from mibo.agent import Agent
from mibo.endpoints import embedding_endpoint, embeddings_url
from mibo.llm import _PooledHTTP
from mibo.textproc import _focus_tokens

from helpers import check, isolated_agent


# ---------------------------------------------------------------------------
# The ranking math, on hand-built rows
# ---------------------------------------------------------------------------

def test_the_lexical_signal_is_bm25_over_the_pool() -> None:
    docs = [("deploy x1", ""), ("chatter 1", ""), ("others z2", "")]
    lex = ranking.Lexicon({"deploy"}, docs)
    scores = [lex.score(d, (1.0, 0.3)) for d in docs]
    check("lexical: a row sharing a term beats one sharing none",
          scores[0] > 0 and scores[1] == scores[2] == 0.0, repr(scores))
    check("lexical: one term of average rarity in an average-length row counts "
          "1.0, what one substring hit counted before",
          abs(scores[0] - 1.0) < 1e-9, repr(scores))

    docs = [("rare aa", ""), ("common a", ""), ("common b", ""), ("common c", "")]
    lex = ranking.Lexicon({"rare", "common"}, docs)
    check("lexical: IDF - a rare term outweighs a common one",
          lex.score(docs[0], (1.0, 0.3)) > lex.score(docs[1], (1.0, 0.3)))
    check("lexical: a scenario hit outweighs the same hit in context",
          lex.score(("rare", ""), (1.0, 0.3)) > lex.score(("", "rare"), (1.0, 0.3)))
    check("lexical: no query terms, no signal",
          ranking.Lexicon(set(), docs).score(docs[0], (1.0, 0.3)) == 0.0)

    zh_docs = [("服务器又挂了",), ("今天吃什么",)]
    zh = ranking.Lexicon(_focus_tokens("服务器挂了怎么办", "zh"), zh_docs)
    check("lexical: Chinese still matches on _focus_tokens bigrams",
          zh.score(zh_docs[0], (1.0,)) > 0 == zh.score(zh_docs[1], (1.0,)))


def test_scope_orders_the_same_text_by_where_it_was_learned() -> None:
    rows = [{"_seed": True}, {}, {"scope": {"conv_id": "g1"}}, {"scope": {"conv_id": "g2"}}]
    tiers = [ranking.scope_tier(r, "g1") for r in rows]
    check("scope: seed, persona, this conversation, another conversation",
          tiers == [ranking.SEED, ranking.PERSONA, ranking.CONVERSATION, ranking.PERSONA],
          repr(tiers))
    w = ranking.EXAMPLE_WEIGHTS
    same = [ranking.score(w, lexical=1.0, tier=t)
            for t in (ranking.SEED, ranking.PERSONA, ranking.CONVERSATION)]
    check("scope: same text - this conversation > this persona > seed",
          same[2] > same[1] > same[0], repr(same))
    check("scope: a preference, not a filter - a matching seed beats an "
          "unrelated row from this conversation",
          ranking.score(w, lexical=1.0, tier=ranking.SEED)
          > ranking.score(w, lexical=0.0, tier=ranking.CONVERSATION))


def test_recency_decays_exponentially() -> None:
    day = 86400.0
    check("recency: 1.0 now, 0.5 at one half-life, 0.25 at two",
          (ranking.recency(0, 14), ranking.recency(14 * day, 14),
           ranking.recency(28 * day, 14)) == (1.0, 0.5, 0.25))
    check("recency: a future timestamp counts as now, never more",
          ranking.recency(-30 * day, 14) == 1.0)
    w = ranking.EXAMPLE_WEIGHTS
    check("recency: the newer of two otherwise equal rows ranks first",
          ranking.score(w, lexical=1.0, age_s=day) > ranking.score(w, lexical=1.0, age_s=30 * day))
    check("recency: a tiebreaker, capped under one lexical hit",
          ranking.score(w, lexical=1.0, age_s=400 * day)
          > ranking.score(w, lexical=0.0, age_s=-day))


def test_an_embedding_neighbour_with_no_shared_words_needs_embeddings() -> None:
    w = ranking.EXAMPLE_WEIGHTS
    query = [1.0, 0.0, 0.0]
    paraphrase = dict(lexical=0.0, vec=[0.6, 0.8, 0.0])  # unit length, cosine 0.6
    word_match = dict(lexical=0.3, vec=[0.0, 0.0, 1.0])

    def rank(q) -> list[str]:
        scored = {name: ranking.score(w, lexical=r["lexical"],
                                      similarity=ranking.cosine(q, r["vec"]))
                  for name, r in (("paraphrase", paraphrase), ("word_match", word_match))}
        return sorted(scored, key=scored.get, reverse=True)

    check("embedding: without a query vector the word match wins",
          rank(None) == ["word_match", "paraphrase"])
    check("embedding: with one the paraphrase wins",
          rank(query) == ["paraphrase", "word_match"])
    check("embedding: a missing row vector is no signal, not an error",
          ranking.cosine(query, None) is None)


# ---------------------------------------------------------------------------
# Through the real agent
# ---------------------------------------------------------------------------

def make_agent(tmp: Path, **settings) -> Agent:
    """The embedding cache sits beside memory.json, so it is in `tmp` too."""
    return isolated_agent(tmp, **{"persona_name": "B", **settings})


# ---------------------------------------------------------------------------
# Embeddings, against a stub endpoint
# ---------------------------------------------------------------------------

EMBEDDING = dict(embedding_model="stub-embed",
                 embedding_base_url="http://embed.test/v1")
FELINE = [1.0, 0.0, 0.0]
OTHER = [0.0, 0.0, 1.0]
QUERY = "my kitten threw up"


class StubEndpoint:
    """An OpenAI-style /embeddings endpoint: FELINE for any text naming a cat,
    OTHER for the rest. Records every request."""

    def __init__(self, *, status: int = 200, delay_s: float = 0.0):
        self.status, self.delay_s = status, delay_s
        self.requests: list[list[str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        self.requests.append(texts)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "unavailable"})
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": FELINE if ("feline" in t or "kitten" in t) else OTHER}
            for i, t in enumerate(texts)]})


def serve(agent: Agent, endpoint: StubEndpoint) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    agent._http = lambda **kw: _PooledHTTP(client)
    return client


async def prepared(a: Agent, focus: str = QUERY) -> None:
    """One turn's async half: the query now, what was read in the background."""
    await a._prepare_retrieval(focus, "g1")
    if a._embedding_backfill is not None:
        await a._embedding_backfill


async def test_vectors_are_cached_in_memory_and_on_disk(tmp: Path) -> None:
    a = make_agent(tmp, **EMBEDDING)
    endpoint = StubEndpoint()
    client = serve(a, endpoint)
    try:
        await prepared(a)
        check("first run: the query is embedded", endpoint.requests == [[QUERY]], repr(endpoint.requests))

        endpoint.requests.clear()
        await prepared(a)
        check("second run: no request at all", endpoint.requests == [], repr(endpoint.requests))

        restarted = make_agent(tmp, **EMBEDDING)
        restarted._http = a._http
        await prepared(restarted)
        check("after a restart: only the query, which is never written to disk",
              endpoint.requests == [[QUERY]], repr(endpoint.requests))
    finally:
        await client.aclose()


def test_the_cache_file_is_pruned_once_mostly_dead(tmp: Path) -> None:
    cache = embeddings.EmbeddingCache(tmp / "embeddings.jsonl")
    vec = embeddings.unit([1.0, 2.0])
    cache.put("m", {f"k{i}": vec for i in range(150)}, persist=True)
    cache.prune("m", {"k1", "k2"})
    lines = (tmp / "embeddings.jsonl").read_text(encoding="utf-8").splitlines()
    fresh = embeddings.EmbeddingCache(tmp / "embeddings.jsonl")
    check("prune: only the kept vectors remain", len(lines) == 2, str(len(lines)))
    check("prune: and they read back intact",
          list(fresh.get("m", "k1")) == list(vec) and fresh.get("m", "k3") is None)
    check("another model's vectors are not this one's",
          fresh.get("other-model", "k1") is None)


async def test_the_startup_probe_reports_an_unreachable_endpoint(tmp: Path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="agent")
    a = make_agent(tmp, **EMBEDDING)
    client = serve(a, StubEndpoint(status=404))
    try:
        await a._probe_embeddings()
    finally:
        await client.aclose()
    check("probe: a configured but unreachable endpoint is reported",
          any("embedding endpoint failed" in r.getMessage() and r.levelno == logging.WARNING
              for r in caplog.records))
    check("probe: and not retried on the next turn",
          a._embedding_retry_at > time.monotonic())


def test_the_embeddings_endpoint_is_spelled_like_the_chat_one() -> None:
    cases = {
        "https://api.openai.com": "https://api.openai.com/v1/embeddings",
        "https://api.siliconflow.cn/v1/": "https://api.siliconflow.cn/v1/embeddings",
        "https://open.bigmodel.cn/api/paas/v4": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        "https://x.example/v1/chat/completions": "https://x.example/v1/embeddings",
        "http://127.0.0.1:11434/v1/embeddings": "http://127.0.0.1:11434/v1/embeddings",
    }
    got = {base: embeddings_url(base) for base in cases}
    check("url: root, version base, chat endpoint and full endpoint", got == cases, repr(got))
    primary = dict(base_url="https://api.openai.com", api_key="sk-primary")
    check("endpoint: blank base URL is the primary's endpoint and key",
          embedding_endpoint(**primary, embedding_base_url="", embedding_api_key="")
          == ("https://api.openai.com/v1/embeddings", "sk-primary"))
    check("endpoint: a URL of its own is never sent the primary's key",
          embedding_endpoint(**primary, embedding_base_url="http://127.0.0.1:11434",
                             embedding_api_key="")
          == ("http://127.0.0.1:11434/v1/embeddings", ""))
