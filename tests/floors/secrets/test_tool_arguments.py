"""A password, a code, a key or a card number is never sent by the character, whatever spells its field: a bare
token, clientSecret, x-api-key, pwd, an Authorization header, at any depth and inside a string of JSON. A count, a
limit, a policy, an id, a timestamp or a plain number is not a secret, so a read sending one is never refused; a
digit run is a card number only when it passes Luhn and is written as one."""
from __future__ import annotations

import json

import pytest

from mibo.review import carries_secret

SECRETS = [
    {"token": "zq81mxkw03hd"},
    {"headers": {"Authorization": "Bearer zq81mxkw03hdlp5e"}},
    {"auth": {"clientSecret": "zq81mxkw03hd"}},
    {"x-api-key": "zq81mxkw03hd"},
    {"apiKey": "zq81mxkw03hd"},
    {"user": "li", "pass": "hunter2"},
    {"pwd": "hunter2!"},
    {"login": {"PASSWD": "hunter2!"}},
    {"otp": "482913"},
    {"card": {"cvv": "123"}},
    {"content": json.dumps({"api_key": "zq81mxkw03hd"})},
    {"items": [{"card_number": "4111111111111111"}]},
    {"note": "pay with 4111 1111 1111 1111"},
]
NOT_SECRETS = [
    {"since": 1732147200007},
    {"message_id": "1109876543210987655"},
    {"query": "carbon footprint 2024"},
    {"token_count": 1200, "max_tokens": 4096},
    {"password_policy": "strong"},
    {"id": 4111111111111111},
    {"when": "2026-11-21T10:00:00Z"},
    {"pageToken": "CAEQAA"},
]


@pytest.mark.parametrize("sent", SECRETS, ids=lambda sent: json.dumps(sent)[:40])
def test_a_secret_in_a_tools_arguments_is_caught_by_any_spelling_at_any_depth(sent):
    assert carries_secret(json.dumps(sent, ensure_ascii=False))


@pytest.mark.parametrize("sent", NOT_SECRETS, ids=lambda sent: json.dumps(sent)[:40])
def test_counts_ids_timestamps_and_numbers_are_not_secrets(sent):
    assert not carries_secret(json.dumps(sent, ensure_ascii=False))
