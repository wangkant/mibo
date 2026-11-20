"""What each catalog in persona_agent/locales/ gets wrong against English's: a
missing or extra key, a slot ({name}, %s) lost or added, a plural form the
language needs, or text in the wrong script.

    python tools/locale_gaps.py
    python tools/locale_gaps.py ja    # that language's problems themselves
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from persona_agent import i18n  # noqa: E402
from persona_agent.chatlangs import CODES  # noqa: E402

PLURAL = re.compile(r"_(zero|one|two|few|many|other)$")
SLOT = re.compile(r"\{\w+\}|%\(\w+\)[sdr]|%[sdr]")
#: The plural forms each language's catalog must give, as Intl.PluralRules names them.
FORMS = {"zh": {"other"}, "zh-TW": {"other"}, "ja": {"other"}, "ko": {"other"},
         "ru": {"one", "few", "many", "other"}}
HAN = re.compile(r"[一-鿿]")
KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
#: Common characters written only in simplified Chinese, for text in zh-TW.
SIMPLIFIED = re.compile("[这个们设开关时对话记录选择显图发现为还进应网页电脑连账号码认证输务请删览动态视频读写间钟单击项备]")
#: Scripts a language's text must not hold unless English's has them too.
FOREIGN = {"zh": (KANA, HANGUL, CYRILLIC), "zh-TW": (KANA, HANGUL, CYRILLIC), "ja": (HANGUL, CYRILLIC), "ko": (KANA, CYRILLIC),
           "ru": (HAN, KANA, HANGUL)}
LATIN_FOREIGN = (HAN, KANA, HANGUL, CYRILLIC)


def leaves(tree, path=""):
    """(key path, value) for every string, list or null in a catalog."""
    if isinstance(tree, dict):
        for key, value in tree.items():
            yield from leaves(value, f"{path}.{key}" if path else key)
    else:
        yield path, tree


def base(key: str, keys) -> str:
    """A plural form's key without its form; any other key as it is."""
    stem = PLURAL.sub("", key)
    return stem if stem != key and f"{stem}_other" in keys else key


def forms_of(catalog: dict) -> dict:
    out = {}
    for key in catalog:
        stem = base(key, catalog)
        out.setdefault(stem, set()).add(key[len(stem) + 1:] if stem != key else "")
    return out


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def problems(code: str) -> list[str]:
    en = dict(leaves(i18n.catalog("en")))
    there = dict(leaves(i18n.catalog(code)))
    out = []
    families, english_families = forms_of(there), forms_of(en)
    for stem, forms in english_families.items():
        theirs = families.get(stem)
        if theirs is None:
            if en[stem if stem in en else f"{stem}_other"] is not None:
                out.append(f"missing: {stem}")
            continue
        if forms - {""}:
            need = FORMS.get(code, {"one", "other"}) | (forms & {"zero"})
            lacking = need - theirs
            if lacking:
                out.append(f"plural forms missing: {stem} ({', '.join(sorted(lacking))})")
    for stem in families.keys() - english_families.keys():
        out.append(f"not in English: {stem}")
    for key, value in there.items():
        stem = base(key, there)
        if stem not in english_families:
            continue
        model = en.get(key) if key in en else en.get(f"{stem}_other", en.get(stem))
        # English's null leaves it to the platform (Intl), which a language may write out instead.
        if model is None:
            continue
        if value is None or isinstance(model, list) != isinstance(value, list):
            out.append(f"shape differs: {key}")
            continue
        if isinstance(model, list) and len(model) != len(value):
            out.append(f"list length differs: {key}")
            continue
        for mine, theirs in zip(strings(model), strings(value)):
            want, have = set(SLOT.findall(mine)), set(SLOT.findall(theirs))
            if stem != key:
                # A plural form: English's "other" decides, and a form may leave the count out ("Read a page").
                want = set(SLOT.findall(en.get(f"{stem}_other", mine)))
                have |= want & {"{count}"}
            if want != have:
                out.append(f"slots differ: {key}: {sorted(have)} for {sorted(want)}")
            if theirs and not re.search(r"\w", mine) and mine.strip() == theirs.strip() and mine != theirs:
                out.append(f"spacing differs: {key}: {theirs!r} for {mine!r}")
            if re.search(r"\w", mine) and not theirs:
                out.append(f"empty: {key}")
            bare = SLOT.sub("", theirs)
            for script in FOREIGN.get(code, LATIN_FOREIGN):
                if script.search(bare) and not script.search(mine):
                    out.append(f"wrong script: {key}: {theirs[:60]}")
                    break
            if code == "zh-TW" and SIMPLIFIED.search(bare):
                out.append(f"simplified characters: {key}: {theirs[:60]}")
            if not key.startswith("catalog.providers.") and theirs == mine and len(re.findall(r"[A-Za-z]{3,}", SLOT.sub("", mine))) >= 3:
                out.append(f"same as English: {key}: {theirs[:60]}")
    return out


def main() -> None:
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    for code in CODES:
        if code == "en" or (wanted and code != wanted):
            continue
        found = problems(code)
        if wanted:
            print("\n".join(found))
        else:
            print(f"{code}: {len(found)} problems")


if __name__ == "__main__":
    main()
