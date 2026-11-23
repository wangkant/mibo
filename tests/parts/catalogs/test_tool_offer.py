"""Which tool definitions go up front (mibo/catalog.py): the modules in catalog order while the definitions stay within
a tenth of the model's window, from the first that does not fit the rest and the always deferred named in find_tools
and called through use_tool, and a tools block that does not change while the window and the tool set do not, even
when a server connects mid-run."""
from __future__ import annotations

import json

import pytest

from mibo import catalog, context, mcp_offer


def _size(tools: list) -> float:
    return context.text_tokens(json.dumps(tools, ensure_ascii=False)) if tools else 0.0


def _names(tools: list) -> list[str]:
    return [t["function"]["name"] for t in tools]


@pytest.fixture
def no_servers(monkeypatch):
    monkeypatch.setattr(mcp_offer, "offer_source", None)


@pytest.mark.parametrize("window", [16384, 32768])
def test_modules_go_up_front_in_catalog_order_while_they_fit_a_tenth_of_the_window(no_servers, window):
    offer = catalog.offered(context.budget(window))
    every = catalog.definitions()
    up = [t for t in offer.tools if not mcp_offer.owns(t["function"]["name"])]
    # The up-front tools keep the catalog's order, and the deferred ones are exactly the rest.
    assert up == [t for t in every if t not in offer.deferred]
    assert offer.deferred and _size(up) <= catalog.SHARE * window
    # The up-front modules are the catalog's first ones: the first module left out would not have fit beside them,
    # and every module after it is left out too, as are the always deferred.
    used, full = 0.0, False
    for module in catalog.MODULES[:-1]:
        mine = [t for t in every if module.owns(t["function"]["name"])]
        if module.deferred or full:
            assert all(t in offer.deferred for t in mine)
        elif all(t in up for t in mine):
            used += _size(mine)
        else:
            assert all(t in offer.deferred for t in mine)
            assert used + _size(mine) > catalog.SHARE * window
            full = True


def test_at_32k_the_tools_the_prompt_names_for_the_web_and_for_places_go_up_front(no_servers):
    # The tool guide's ways to the web and to places (prompts.OWNER_TOOL_GUIDE) and bring_find, which it names for
    # every recommendation, are sent with a 32k window's first request.
    names = _names(catalog.offered(context.budget(32768)).tools)
    for name in ("web_search", "read_page", "read_with_their_session", "find_on_site", "bring_find", "open", "look",
                 "act"):
        assert name in names


def test_every_deferred_tool_is_named_in_find_tools_and_callable_with_its_own_schema(no_servers):
    offer = catalog.offered(context.budget(16384))
    find = next(t for t in offer.tools if t["function"]["name"] == mcp_offer.FIND)
    assert mcp_offer.USE in _names(offer.tools)
    for tool in offer.deferred:
        name = tool["function"]["name"]
        assert f"- {name}:" in find["function"]["description"]
        assert offer.schemas[name] == tool["function"]["parameters"]
        assert catalog.module_of(name) is not None


def _always_deferred() -> list:
    return [t for module in catalog.MODULES[:-1] if module.deferred for t in module.definitions()]


@pytest.mark.parametrize("window", [65536, 131072, 1_048_576])
def test_at_64k_and_above_every_tool_but_the_always_deferred_goes_up_front(no_servers, window):
    offer = catalog.offered(context.budget(window))
    later = _always_deferred()
    assert later and offer.deferred == later
    assert [t for t in offer.tools if not mcp_offer.owns(t["function"]["name"])] == [
        t for t in catalog.definitions() if t not in later]


def test_the_tools_block_stays_the_same_while_a_server_connects_mid_run(monkeypatch):
    states = [
        {"names": ["notes"], "servers": [{"name": "notes", "about": "", "tools": 0, "state": "waiting"}]},
        {"names": ["notes"], "servers": [{"name": "notes", "about": "", "tools": 0, "state": "starting"}]},
        {"names": ["notes"], "servers": [{"name": "notes", "about": "Notes and lists", "tools": 40}]},
    ]
    for window in (16384, 1_048_576):
        blocks = []
        for state in states:
            monkeypatch.setattr(mcp_offer, "offer_source", lambda state=state: state)
            blocks.append(json.dumps(catalog.offered(context.budget(window)).tools, sort_keys=True))
        assert len(set(blocks)) == 1
        # The server's tools are reached through find_tools at every window, never sent up front.
        assert {mcp_offer.FIND, mcp_offer.USE} <= set(_names(json.loads(blocks[0])))


def test_the_always_deferred_are_found_through_the_loader_at_every_window(no_servers):
    offer = catalog.offered(context.budget(1_048_576))
    find = next(t for t in offer.tools if t["function"]["name"] == mcp_offer.FIND)
    assert "web_search" in _names(offer.tools)
    for tool in _always_deferred():
        assert tool["function"]["name"] not in _names(offer.tools)
        assert f"- {tool['function']['name']}:" in find["function"]["description"]
