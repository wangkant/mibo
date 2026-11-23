"""The setup form's choice (/api/config): the model service, its key and model, the language, the character, its
name and picture, checked and the key tried before anything is written. Each refusal is a ValueError whose text is
the page's error code."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from . import langs
from . import setup_wizard as sw
from .endpoints import model_problem

# What a failed key probe means, as the page names it; anything else is model_unreachable.
PROBLEMS = {"key": "key_rejected", "limited": "model_limited", "no_balance": "model_no_balance",
            "not_found": "model_not_found"}


def endpoint(value) -> str:
    """An OpenAI-compatible base URL: https, or http only on this computer."""
    base = str(value or "").strip()
    parsed = urlsplit(base)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username
            or parsed.password):
        raise ValueError("invalid_url")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("https_required")
    return base


def _provider(payload: dict, old: dict) -> tuple[sw.Provider, str, bool]:
    """The service chosen, its base URL, and whether both are the ones saved before."""
    previous = sw.provider_for_base(old.get("LLM_BASE_URL", ""))
    try:
        provider = sw.provider_named(str(payload.get("provider") or (previous or sw.PROVIDERS[0]).key))
    except ValueError:
        raise ValueError("invalid_provider") from None
    same = ((previous is not None and previous.key == provider.key)
            or (previous is None and provider.key == "other" and bool(old.get("LLM_BASE_URL"))))
    base = str(payload.get("baseUrl") or provider.base_url).strip()
    return provider, base, same and base.rstrip("/") == old.get("LLM_BASE_URL", "").rstrip("/")


def _key(payload: dict, old: dict, provider: sw.Provider, base: str, same: bool) -> str:
    """The key typed, else one found in the environment for this service, else the one saved for it."""
    key = str(payload.get("apiKey") or "").strip()
    taken = str(payload.get("apiKeyFrom") or "")
    if not key and taken:
        # A key the page found in the environment and never saw.
        from .panels import detect
        # Only to that service's own address: a key must not follow a typed one.
        home_of_key = sw.provider_for_base(base)
        if (detect.ENV_KEYS.get(taken) == provider.key
                and home_of_key is not None and home_of_key.key == provider.key):
            key = detect.env_key(taken)
    if not key and same:
        key = old.get("LLM_API_KEY", "")
    if not provider.needs_key:
        key = key or "ollama"
    if not key and old.get("LLM_API_KEY"):
        # The saved key belongs to the service it was saved for.
        raise ValueError("key_again")
    if not key or len(key) > 4096:
        raise ValueError("key_required")
    if not key.isascii() or any(c.isspace() for c in key):
        # Pasted with other words around it: no service would take it.
        raise ValueError("key_malformed")
    return key


def _avatar(home: Path, payload: dict) -> str | None:
    """The picture the page names; None when it names none."""
    avatar = payload.get("avatar")
    if avatar is None:
        return None
    avatar = str(avatar)
    if not (avatar == "" or sw.portrait(avatar) or (avatar == sw.OWN_AVATAR and sw.own_avatar(home))):
        raise ValueError("invalid_character")
    return avatar


def _probe(base: str, key: str, model: str) -> None:
    try:
        probe = sw.probe_key(base, key, model, timeout=20)
    except Exception:
        raise ValueError("model_unreachable") from None
    if not probe.ok:
        # Never return an upstream response body: it may echo a key.
        problem = model_problem(probe.status, probe.detail) if probe.status else ""
        raise ValueError(PROBLEMS.get(problem, "model_unreachable"))


def chosen(home: Path, old: dict, payload: dict) -> tuple[dict, str]:
    """The settings to write for the choice in `payload` over the saved `old`, and the character chosen ("custom"
    for a persona of one's own); the key is tried against the model first."""
    provider, base, same = _provider(payload, old)
    key = _key(payload, old, provider, base, same)
    base = endpoint(base)
    model = str(payload.get("model") or provider.model).strip()
    if not model or len(model) > 256:
        raise ValueError("model_required")
    lang = langs.normalize(payload.get("lang")) or "en"
    character = str(payload.get("character") or sw.CHARACTERS[0].key)
    if character not in (*sw.PERSONA_KEYS, "custom"):
        raise ValueError("invalid_character")
    own = sw.character_for(character).name_in(lang) if character != "custom" else ""
    avatar = _avatar(home, payload)
    name = str(payload.get("name") or own or old.get("PERSONA_NAME") or sw.DEFAULT_NAMES[lang]).strip()
    if not name:
        raise ValueError("name_required")
    if len(name) > 64:
        raise ValueError("invalid_character")
    _probe(base, key, model)
    values = {"LLM_BASE_URL": base, "LLM_MODEL": model, "LLM_API_KEY": key, "PERSONA_NAME": name, "AGENT_LANG": lang}
    # The page names the picture; without it, a written character keeps its own.
    if avatar is not None:
        values["PERSONA_AVATAR"] = avatar
    elif character != "custom":
        values["PERSONA_AVATAR"] = sw.kept_avatar(home, old, character)
    return values, character
