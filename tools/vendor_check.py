"""Check the model service presets: does each address answer, and with a key,
is the default model listed and does a one-token call work?

Without a key each preset gets one request with no key; an answer of 401 or
403 means the address is right. A key is read from the variable each vendor's
documentation names (panels/detect.py ENV_KEYS), or from --env-file, and never
printed.

    python tools/vendor_check.py                      every preset, no keys
    python tools/vendor_check.py deepseek moonshot    those presets
    python tools/vendor_check.py --env-file .env      keys from a file (KEY=value lines)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mibo import setup_wizard as sw
from mibo.endpoints import chat_completions_url, model_problem
from mibo.panels.detect import ENV_KEYS

# Presets without a variable of their own in ENV_KEYS.
EXTRA_KEYS = {"qianfan": "QIANFAN_API_KEY", "hunyuan": "TOKENHUB_API_KEY"}


def _keys(env_file: str) -> dict:
    found = {}
    if env_file:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if value.strip():
                found[name.strip()] = value.strip().strip("'\"")
    by_preset = {v: k for k, v in ENV_KEYS.items()} | EXTRA_KEYS
    return {key: found.get(var) or os.environ.get(var, "") for key, var in by_preset.items()}


def _get(url: str, key: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            return answer.status, answer.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError) as e:
        return 0, str(getattr(e, "reason", e))[:80]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("presets", nargs="*")
    parser.add_argument("--env-file", default="")
    args = parser.parse_args()
    keys = _keys(args.env_file)
    chosen = [sw.provider_named(k) for k in args.presets] or [p for p in sw.PROVIDERS if p.base_url]
    for p in chosen:
        url = chat_completions_url(p.base_url)
        key = keys.get(p.key, "")
        if not key:
            status, detail = sw._post(url, "none", {"model": p.model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}, 15)
            # Gemini and xAI answer a wrong key with a 400.
            verdict = ("address answers" if status in (401, 403) or model_problem(status, detail) == "key" else
                       "local server not running" if not p.needs_key and status == 0 else f"HTTP {status} {detail[:80]}")
            print(f"{p.key:12} {p.model:32} no key: {verdict}")
            continue
        status, body = _get(url.rsplit("/chat/completions", 1)[0] + "/models", key)
        try:
            listed = {row.get("id") for row in json.loads(body).get("data", [])}
        except (ValueError, AttributeError):
            listed = set()
        where = ("listed" if p.model in listed else "not in /models" if listed else f"/models HTTP {status}")
        probe = sw.probe_key(p.base_url, key, p.model, timeout=30)
        result = "call OK" if probe.ok else f"HTTP {probe.status} {model_problem(probe.status, probe.detail) or '?'}"
        print(f"{p.key:12} {p.model:32} {where}; {result}")


if __name__ == "__main__":
    main()
