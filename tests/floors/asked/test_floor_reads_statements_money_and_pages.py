"""The floor's second look (mibo/mcp_tools.py, mibo/review.py, mibo/web/gate.py). A statement that deletes is a
floor in a field that holds statements or questions alike (a database's `query`), while the words of a search are
not; money is a payment only with whom it goes to; a call too large to read whole is asked about; a token that
pages through a list or names a coin is not a secret, a credential is; and the words only a tool's name says (sell,
deposit, rm, an email changed, a queue cleared) do not card a page's menu, a price in ringgit or a program's name.
(2026-11-21: a review ran each of these against the rebuilt floor and found them wrong.)"""
from __future__ import annotations

import json

import pytest

from mibo import mcp_tools as mt
from mibo import review
from mibo.web import gate


def tool(name: str, description: str = "", fields: tuple = (), read_only: bool | None = None) -> dict:
    raw = {"name": name, "description": description,
           "inputSchema": {"type": "object", "properties": {f: {"type": "string"} for f in fields}}}
    if read_only is not None:
        raw["annotations"] = {"readOnlyHint": read_only}
    return mt.clean_tool(raw)


@pytest.mark.parametrize("name, field, value", [
    ("query", "query", "DROP TABLE users"),
    ("read_query", "query", "DELETE FROM users WHERE id = 3"),
    ("read_query", "query", "SELECT 1; drop table if exists logs;"),
    ("search", "expression", "TRUNCATE TABLE t"),
])
def test_a_statement_that_deletes_is_a_floor_in_a_query_field_of_a_tool_hinted_read_only(name, field, value):
    assert mt.hard(tool(name, "Execute a SELECT query", (field,), True), {field: value}) == "delete"


@pytest.mark.parametrize("asked", [
    "how to delete from a list in python", "Museo del Prado opening hours", "css truncate text with ellipsis",
    "rm -rf node_modules safe?", "drop table sql syntax explained"])
def test_the_words_of_a_search_are_not_a_statement(asked):
    searching = tool("web_search", "Search the web", ("query",), True)
    assert mt.hard(searching, {"query": asked}) == "" and mt.group_of(searching) == "read"


@pytest.mark.parametrize("name, arguments", [
    ("search_flights", {"destination": "NYC", "max_price": 500}),
    ("list_transactions", {"currency": "USD", "min_amount": 5}),
    ("get_directions", {"from": "a", "to": "b", "costing": "auto"}),
    ("search_products", {"query": "mouse", "price": 20}),
])
def test_a_price_a_currency_or_a_destination_in_a_search_pays_nobody(name, arguments):
    assert mt.hard(tool(name, "", tuple(arguments), True), arguments) == ""


@pytest.mark.parametrize("name, arguments", [
    ("do_it", {"recipient": "DE89", "amount": 10}), ("move", {"to": "acct-2", "amount": 10})])
def test_an_amount_with_whom_it_goes_to_is_a_payment_whatever_the_tool_is_called(name, arguments):
    assert mt.hard(tool(name, "", tuple(arguments)), arguments) == "order"


def test_arguments_too_large_to_read_whole_are_asked_about():
    padded = {**{f"k{n}": n for n in range(70)}, "action": "delete"}
    assert mt.cut(padded) and mt.cut({"rows": [{"a": n} for n in range(40)]})
    assert not mt.cut({"ids": list(range(200)), "filter": {"a": 1}})


@pytest.mark.parametrize("plain", [
    {"pagination_token": "eyJwYWdlIjoyfQabcdefgh"}, {"skipToken": "abcdefghijklmnop"}, {"token": "USDC"},
    {"input_token": "ETH", "output_token": "USDC"}, {"continueToken": "abcdefghijklmnopqrstu"},
    {"StartingToken": "abcdefghijklmnopqrstu"}])
def test_a_token_that_pages_or_names_a_coin_is_not_a_secret(plain):
    assert not review.carries_secret(json.dumps(plain))


@pytest.mark.parametrize("secret", [
    {"token": "abcdEFGH12345678xyzQ"}, {"access_token": "abcdEFGH12345678xyzQ"}, {"pin": "4321"},
    {"refresh_token": "abcdEFGH12345678xyzQ"}, {"password": "hunter2"}])
def test_a_credential_under_a_token_a_pin_or_a_password_field_is_a_secret(secret):
    assert review.carries_secret(json.dumps(secret))


def page(name: str) -> str:
    return gate.classify("click", name, "button", {}, "https://example.com/")[0]


@pytest.mark.parametrize("name", [
    "Logitech M331 Silent Mouse RM 59.90 1.2k sold", "Price: RM 12.00", "Sell", "Deposit", "Withdraw", "Add email",
    "Edit phone", "Edit email signature", "Start plan", "Total Commander", "Clear queue", "Suspend", "Kick",
    "Add card", "Reserve"])
def test_a_page_control_named_with_a_tools_word_is_no_floor(name):
    assert page(name) not in ("order", "delete", "account", "grant")


@pytest.mark.parametrize("name, kind", [
    ("Pay now", "order"), ("Delete", "delete"), ("Commander", "order"), ("Payer", "order"),
    ("Change password", "account"), ("Ban user", "account"), ("Terminate instance", "delete"),
    ("Disable two-factor", "account"), ("Empty trash", "delete"), ("Cancel subscription", "delete"),
    ("Make public", "grant"), ("Place order", "order"), ("删除", "delete"), ("送金", "order")])
def test_a_page_control_that_pays_deletes_or_changes_an_account_is_a_floor(name, kind):
    assert page(name) == kind


@pytest.mark.parametrize("name, kind", [
    ("create_payout", "order"), ("sell_shares", "order"), ("withdraw_funds", "order"), ("update_user_email", "account"),
    ("clear_queue", "delete"), ("kick_member", "account"), ("rm", "delete"), ("renew_subscription", "order"),
    ("link_bank_account", "order"), ("disable_two_factor", "account"), ("terminate_instances", "delete"),
    ("place_bid", "order"), ("tip_creator", "order"), ("upgrade_plan", "order"), ("enable_mfa", "account")])
def test_a_tool_named_with_those_words_is_a_floor(name, kind):
    assert mt.hard(tool(name)) == kind
