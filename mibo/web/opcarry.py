"""What a request the page makes, or an address, carries: its body and address every way they may say a thing
(form-decoded, JSON leaves, base64 runs), whether a text typed in the run is in it, whether it only reads, and how
the reviewer reads it. For operate.Hands, which holds what carries typed text, and for an address the model wrote,
which may not carry words read on a page."""
from __future__ import annotations

import base64
import contextlib
import html
import json
import re
from urllib.parse import parse_qsl, unquote_plus, urlsplit

# A GraphQL body that only asks (no mutation): a request a plain press may set off without a card.
ASKS_ONLY = re.compile(r"\s*(?:query\b|\{)")
# Words read in the run that an address to another site may not carry, characters running.
READ_RUN = 8
# A base64 run in a body long enough to be typed text, decoded and looked in too.
BASE64 = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
# A typed text this short must be a whole value of the request to count as carried by it.
CARRIED_MIN = 3


def shape(url: str) -> str:
    """An address's path with its ids made {id}, for matching a stored step to the page it was on."""
    path = urlsplit(url).path or "/"
    return re.sub(r"/(?:\d+|[0-9a-zA-Z_-]{16,})(?=/|$)", "/{id}", path)


def squeeze(s: str) -> str:
    return re.sub(r"\s+", "", html.unescape(s))


def texts_of(request: dict) -> list[str]:
    """What a paused request says, every way it may say it: its address and body as sent, form-decoded, its JSON
    leaves, and base64 runs decoded."""
    body, url, values = leaves_of(request)
    texts = [body, unquote_plus(body), unquote_plus(url), " ".join(values)]
    for run in BASE64.findall(body + " " + unquote_plus(url)):
        with contextlib.suppress(ValueError):
            texts.append(base64.b64decode(run.replace("-", "+").replace("_", "/") + "=" * (-len(run) % 4)).decode("utf-8"))
    return texts + values


def leaves_of(request: dict) -> tuple[str, str, list[str]]:
    """A paused request's body, its address, and the values in both."""
    body = str(request.get("postData") or "")
    # The entries are the same body in parts, read when the body itself was not given.
    for entry in [] if body else request.get("postDataEntries") or []:
        with contextlib.suppress(ValueError):
            body += base64.b64decode(entry.get("bytes") or "").decode("utf-8", "replace")
    url = str(request.get("url") or "")
    values = [v.strip() for v in values_of(body)] if body else []
    values += [v.strip() for _, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)]
    return body, url, values


def bears(texts: list[str], text: str) -> bool:
    """`text` is in what a request says, as typed, JSON-escaped, or with its spaces and HTML entities aside; one
    shorter than CARRIED_MIN only as a whole value."""
    t = text.strip()
    if len(t) < CARRIED_MIN:
        return bool(t) and t in texts
    if any(t in x or json.dumps(t)[1:-1] in x for x in texts):
        return True
    squeezed = squeeze(t)
    return len(squeezed) >= CARRIED_MIN and any(squeezed in squeeze(x) for x in texts)


def values_of(body: str) -> list[str]:
    """The leaf values of a JSON or form body, as text."""
    try:
        found: list[str] = []

        def leaves(v) -> None:
            if isinstance(v, dict):
                for x in v.values():
                    leaves(x)
            elif isinstance(v, list):
                for x in v:
                    leaves(x)
            elif v is not None:
                found.append(str(v))
        leaves(json.loads(body))
        return found
    except ValueError:
        return [v for _, v in parse_qsl(body, keep_blank_values=True)]


def asks_only(request: dict) -> bool:
    """A GraphQL request whose every operation is a query written out: it reads and changes nothing."""
    try:
        body = json.loads(str(request.get("postData") or ""))
    except ValueError:
        return False
    items = body if isinstance(body, list) else [body]
    return bool(items) and all(isinstance(i, dict) and isinstance(i.get("query"), str) and ASKS_ONLY.match(i["query"])
                               for i in items)


def summary_of(request: dict) -> dict:
    """A request as the reviewer reads it: its method, its address without the query, and the short values of its
    query and body (ids and long runs aside)."""
    body, url, values = leaves_of(request)
    parts = urlsplit(url)
    short = [v for v in dict.fromkeys(values) if v and len(v) <= 80][:16]
    return {"method": str(request.get("method") or "GET").upper(), "address": f"{parts.netloc}{parts.path}"[:200],
            "values": short, "body_chars": len(body)}


def only_reads(request: dict, carried: list[dict], ping: bool) -> bool:
    """What code is certain only reads, let through with no card and no reviewer: a beacon or ping, or a GraphQL
    query, that carries nothing typed in this run. Every other request a press sends is the reviewer's."""
    return not carried and (ping or asks_only(request))


def leaving(url: str) -> dict:
    """Going to another site as the reviewer reads it: the address, and its query and fragment as the text it
    carries (where an address or a number the person never gave would ride along)."""
    parts = urlsplit(url)
    return {"target": [url[:300]], "text": unquote_plus(" ".join(filter(None, [parts.query, parts.fragment])))}


def words_carried(url: str, read: str, own: str) -> str:
    """Words read in this run that an address carries past its host (READ_RUN characters running, spaces aside, as
    written, decoded or base64), and that the person's own words do not hold: the first such run, or "". As much of
    the address as the page itself shows from its host on (a link written out, or the start of one a page tells the
    model to fill in) is the page's own, not carried."""
    shown, mine = squeeze(read), squeeze(own)
    address = squeeze(unquote_plus(url.split("://", 1)[-1]))
    host = len(squeeze(urlsplit(url).netloc))
    # The longest start of it the page shows: a start shown means every shorter one is too.
    low, high = 0, len(address)
    while low < high:
        mid = (low + high + 1) // 2
        low, high = (mid, high) if address[:mid] in shown else (low, mid - 1)
    rest = address[max(low, host):]
    texts = [rest] + [squeeze(x) for x in texts_of({"url": rest})[4:]]
    for t in texts:
        for i in range(len(t) - READ_RUN + 1):
            if t[i:i + READ_RUN] in shown and t[i:i + READ_RUN] not in mine:
                return t[i:i + READ_RUN]
    return ""
