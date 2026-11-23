"""A Bilibili link in a message: its title, uploader and description from the web view API, and the site's AI
summary of the video when it has one (WBI-signed). Mixed into ContentIngestion; third-party answers are untrusted."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("agent")

# The order WBI signing takes the two keys' characters in.
_WBI_MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def cap_cache(cache: dict, cap: int = 200, drop: int = 50) -> None:
    """Past `cap` entries, the `drop` oldest go."""
    if len(cache) > cap:
        for k in list(cache)[:drop]:
            cache.pop(k, None)


def wbi_sign(params: dict, img_key: str, sub_key: str) -> dict:
    """`params` with WBI signing applied: wts and w_rid appended."""
    orig = img_key + sub_key
    mixin = "".join(orig[i] for i in _WBI_MIXIN_KEY_ENC_TAB if i < len(orig))[:32]
    signed = dict(sorted({**params, "wts": int(time.time())}.items()))
    signed = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in signed.items()}
    signed["w_rid"] = hashlib.md5((urlencode(signed) + mixin).encode()).hexdigest()
    return signed


def format_line(info: dict, title_fallback: str = "") -> str:
    """The `[bilibili-video] "title" — by <up>, ...` line fed to the model."""
    title = info.get("title") or title_fallback
    up = info.get("up", "")
    summary = (info.get("summary", "") or "").strip().replace("\n", " ")
    desc = (info.get("desc", "") or "").strip().replace("\n", " ")[:80]
    line = f"[bilibili-video] \"{title}\""
    if up:
        line += f" — by {up}"
    if summary:
        line += f", AI summary: {summary[:200]}"
    elif desc:
        line += f", description: {desc}"
    return line


def _summary_line(result: dict) -> str:
    """The AI summary and up to five outline titles of a conclusion/get `model_result`, in 300 characters."""
    line = (result.get("summary") or "").strip()
    titles = [t[:30] for t in ((sec.get("title") or "").strip() for sec in (result.get("outline") or [])[:5]) if t]
    if titles:
        line += (" | outline:" if line else "outline:") + " / ".join(titles)
    return line[:300]


class BilibiliLinks:
    """Mixed into ContentIngestion, which gives `bili_info_cache`, `_wbi_keys`, `_wbi_keys_ts`, `_safe_get`,
    `_host_is_internal` and `_url_cache_key`."""

    async def _fetch_bili_info(self, url: str) -> dict:
        """Bilibili title/uploader/desc (and AI summary) for a share URL, via
        b23.tv and the web view API; {} on any failure. `_describe_url` has checked the URL's length."""
        cache_key = self._url_cache_key(url)
        if cache_key in self.bili_info_cache:
            return self.bili_info_cache[cache_key]
        real_url = url
        if "b23.tv" in url:
            # "contains b23.tv" is not "is a shortlink": never fetch internal hosts.
            if self._host_is_internal(url):
                logger.warning("[Agent] refusing internal-address b23 url: %s", url)
                self.bili_info_cache[cache_key] = {}
                return {}
            # _safe_get re-checks every redirect hop.
            r = await self._safe_get(url, timeout=5, headers=_HEADERS)
            if r is not None:
                real_url = str(r.url)
        m = re.search(r"BV[a-zA-Z0-9]{10}", real_url)
        if not m:
            self.bili_info_cache[cache_key] = {}
            return {}
        bvid = m.group(0)
        info, cid, up_mid = await self._bili_view(bvid)
        if info and cid and up_mid:
            summary = await self._fetch_bili_summary(bvid, cid, up_mid)
            if summary:
                info["summary"] = summary
        self.bili_info_cache[cache_key] = info
        cap_cache(self.bili_info_cache)
        logger.info("[Agent] bili view %s: %s", bvid, (info.get("title") or "(empty)")[:60])
        return info

    async def _bili_view(self, bvid: str) -> tuple[dict, int, int]:
        """(title, uploader and description, the video's cid, the uploader's mid) from the web view API;
        ({}, 0, 0) on failure."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("https://api.bilibili.com/x/web-interface/view",
                                     params={"bvid": bvid}, headers=_HEADERS)
                r.raise_for_status()
                data = r.json()
                if data.get("code") == 0:
                    d = data.get("data") or {}
                    # "owner" is Bilibili's field for the uploader.
                    owner = d.get("owner") or {}
                    info = {"title": (d.get("title") or "")[:80], "up": (owner.get("name") or "")[:30],
                            "desc": (d.get("desc") or "")[:200]}
                    return info, int(d.get("cid") or 0), int(owner.get("mid") or 0)
        except Exception as e:
            logger.debug("[Agent] Bili view API failed (%s): %s", bvid, e)
        return {}, 0, 0

    async def _fetch_wbi_keys(self) -> tuple[str, str]:
        """(img_key, sub_key) for WBI signing, cached 24h; ('', '') on failure."""
        now = time.time()
        if self._wbi_keys[0] and now - self._wbi_keys_ts < 86400:
            return self._wbi_keys
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("https://api.bilibili.com/x/web-interface/nav", headers=_HEADERS)
                wbi_img = (r.json().get("data") or {}).get("wbi_img") or {}
                img_key = (wbi_img.get("img_url", "") or "").rsplit("/", 1)[-1].split(".")[0]
                sub_key = (wbi_img.get("sub_url", "") or "").rsplit("/", 1)[-1].split(".")[0]
                if img_key and sub_key:
                    self._wbi_keys = (img_key, sub_key)
                    self._wbi_keys_ts = now
                    return self._wbi_keys
        except Exception as e:
            logger.debug("[Agent] WBI keys fetch failed: %s", e)
        return ("", "")

    async def _fetch_bili_summary(self, bvid: str, cid: int, up_mid: int) -> str:
        """Bilibili AI summary via view/conclusion/get, or ""."""
        img_key, sub_key = await self._fetch_wbi_keys()
        if not img_key or not sub_key:
            return ""
        params = wbi_sign({"bvid": bvid, "cid": cid, "up_mid": up_mid}, img_key, sub_key)
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get("https://api.bilibili.com/x/web-interface/view/conclusion/get", params=params,
                                     headers={**_HEADERS, "Referer": f"https://www.bilibili.com/video/{bvid}"})
                r.raise_for_status()
                data = r.json()
                if data.get("code") != 0:
                    logger.debug("[Agent] bili summary %s: code=%s msg=%s",
                                 bvid, data.get("code"), data.get("message"))
                    return ""
                result = (data.get("data") or {}).get("model_result") or {}
                if not result.get("result_type"):
                    return ""
                line = _summary_line(result)
                if line:
                    logger.info("[Agent] bili summary %s: %s", bvid, line[:80])
                return line
        except Exception as e:
            logger.debug("[Agent] bili summary failed (%s): %s", bvid, e)
        return ""
