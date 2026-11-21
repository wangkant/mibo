"""How the base URL a person types becomes the chat and embeddings endpoints (mibo/endpoints.py), and
which key each endpoint is sent."""
from __future__ import annotations

from mibo.endpoints import chat_completions_url, embedding_endpoint, embeddings_url


def test_every_spelling_of_a_base_url_reaches_the_same_chat_endpoint() -> None:
    for base in ("https://example.org", "https://example.org/", "https://example.org/v1",
                 "https://example.org/v1/", "https://example.org/v1/chat/completions"):
        assert chat_completions_url(base) == "https://example.org/v1/chat/completions", base
    assert chat_completions_url("https://example.org/proxy/v1/") == "https://example.org/proxy/v1/chat/completions"


def test_a_vendor_version_root_gets_only_chat_completions() -> None:
    cases = {
        "https://open.bigmodel.cn/api/paas/v4": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "https://ark.cn-beijing.volces.com/api/v3/": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "https://generativelanguage.googleapis.com/v1beta/openai/":
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        # A bare /openai is Groq's root, which still needs its /v1.
        "https://api.groq.com/openai": "https://api.groq.com/openai/v1/chat/completions",
        "https://proxy.corp/llm-proxy": "https://proxy.corp/llm-proxy/v1/chat/completions",
    }
    for base, want in cases.items():
        assert chat_completions_url(base) == want
        assert embeddings_url(base) == want[:-len("/chat/completions")] + "/embeddings"


def test_the_embeddings_endpoint_is_spelled_like_the_chat_one() -> None:
    cases = {
        "https://api.openai.com": "https://api.openai.com/v1/embeddings",
        "https://api.siliconflow.cn/v1/": "https://api.siliconflow.cn/v1/embeddings",
        "https://open.bigmodel.cn/api/paas/v4": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        "https://x.example/v1/chat/completions": "https://x.example/v1/embeddings",
        "http://127.0.0.1:11434/v1/embeddings": "http://127.0.0.1:11434/v1/embeddings",
    }
    assert {base: embeddings_url(base) for base in cases} == cases


def test_a_separate_embeddings_address_is_never_sent_the_main_key() -> None:
    primary = dict(base_url="https://api.openai.com", api_key="sk-primary")
    assert embedding_endpoint(**primary, embedding_base_url="", embedding_api_key="") \
        == ("https://api.openai.com/v1/embeddings", "sk-primary")
    assert embedding_endpoint(**primary, embedding_base_url="http://127.0.0.1:11434", embedding_api_key="") \
        == ("http://127.0.0.1:11434/v1/embeddings", "")
