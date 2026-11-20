"""Deployment regressions; runnable on Windows and Linux without credentials."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
from mibo.endpoints import chat_completions_url


class DeploymentTests(unittest.TestCase):

    def test_endpoint_spellings(self):
        for base in ("https://example.org", "https://example.org/",
                     "https://example.org/v1", "https://example.org/v1/",
                     "https://example.org/v1/chat/completions"):
            self.assertEqual(chat_completions_url(base),
                             "https://example.org/v1/chat/completions")
        self.assertEqual(chat_completions_url("https://example.org/proxy/v1/"),
                         "https://example.org/proxy/v1/chat/completions")

    def test_a_vendor_version_root_gets_only_chat_completions(self):
        from mibo.endpoints import embeddings_url
        cases = {
            "https://open.bigmodel.cn/api/paas/v4":
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "https://ark.cn-beijing.volces.com/api/v3/":
                "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            "https://generativelanguage.googleapis.com/v1beta/openai/":
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            # A bare /openai is Groq's root, which still needs its /v1.
            "https://api.groq.com/openai":
                "https://api.groq.com/openai/v1/chat/completions",
            "https://proxy.corp/llm-proxy":
                "https://proxy.corp/llm-proxy/v1/chat/completions",
        }
        for base, want in cases.items():
            self.assertEqual(chat_completions_url(base), want)
            self.assertEqual(embeddings_url(base),
                             want[:-len("/chat/completions")] + "/embeddings")
