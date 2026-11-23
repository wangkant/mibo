"""What is never kept as said: a Chinese ID number, a card number, a password, a one-time code or a key, found in
any text in the ten chat languages, and masked wherever a chat's record, the page's copy or a summary holds it."""
from __future__ import annotations

import re
import unicodedata

# A password's or a one-time code's word, in the ten chat languages.
_SECRET_WORD = (r"密码|密碼|口令|验证码|驗證碼|校验码|校驗碼|动态码|動態碼|"
                r"passwords?|passcodes?|passwd|\bpin\b|verification code|security code|one[- ]time code|\botp\b"
                r"|\bcvv2?\b|\bcvc\b|パスワード|暗証番号|認証コード|確認コード|ワンタイム(?:パスワード|コード)"
                r"|비밀번호|암호|인증\s?번호|인증\s?코드|contraseña|código de (?:verificación|seguridad)"
                r"|mot de passe|code de (?:vérification|sécurité|confirmation)|passwort|kennwort"
                r"|bestätigungscode|verifizierungscode|sicherheitscode|senha|código de (?:verificação|confirmação)"
                r"|пароль|код подтверждения|код из смс")
# A key's word, and a value shaped like a key after it: 16 or more letters, digits, - and _, a letter and a digit
# among them. Talk about keys ("my API key is not working", "API key 还剩 5000") has none.
_KEY_WORD = r"\bapi[ _-]?keys?\b|密钥|秘钥|私钥"
_KEY = r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,}"
# The word with its value after it ("密码是…", "password: …", "验证码 482913"); the word alone ("我总忘记密码") is none.
_SECRET = re.compile(rf"(?:{_SECRET_WORD})\s*(?:是|为|為|は|는|은|:|：|=|\bis\b|\bist\b|\bes\b|\best\b|\bé\b|—)\s*\S"
                     rf"|(?:{_SECRET_WORD})\D{{0,6}}\d{{4,}}|(?:{_KEY_WORD})\D{{0,12}}?{_KEY}", re.IGNORECASE)
_ID18 = re.compile(r"(?<![0-9A-Za-z])\d{17}[0-9Xx](?![0-9A-Za-z])")
_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
# The value after a password's or a code's word, as `_SECRET` finds it; a question ("密码是什么") has none.
_SECRET_VALUE = re.compile(rf"((?:{_SECRET_WORD})\s*(?:是|为|為|は|는|은|:|：|=|\bis\b|\bist\b|\bes\b|\best\b|\bé\b|—)\s*)"
                           rf"(?!什么|甚么|多少|啥|哪)([^\s，,。;；!！?？、]+)|((?:{_SECRET_WORD})\D{{0,6}}?)(\d{{4,}})"
                           rf"|((?:{_KEY_WORD})\D{{0,12}}?)({_KEY})", re.IGNORECASE)
# A card number as cards print it: 13 to 19 digits in a row, in groups of four, or Amex's 4-6-5. No card network
# issues numbers starting 19 or 20, which is how dates and times begin ("2026-11-18 141500").
_CARD_SHOWN = re.compile(r"(?<![\d-])(?!19|20)(?:\d{13,19}|\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,3})?"
                         r"|\d{4}[ -]\d{6}[ -]\d{5})(?![\d-])")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _id_checks(number: str) -> bool:
    """A Chinese ID number's check digit is right."""
    return "10X98765432"[sum(int(c) * w for c, w in zip(number, _ID_WEIGHTS)) % 11] == number[-1].upper()


def secret(text: str) -> bool:
    """A Chinese ID number (its check digit right), a card number (Luhn), a password or a one-time code:
    never kept, whoever writes it."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    if _SECRET.search(text):
        return True
    if any(_id_checks(m.group()) for m in _ID18.finditer(text)):
        return True
    return any(_luhn(re.sub(r"\D", "", m.group())) for m in _CARD.finditer(text))


def _masked(text: str, found: dict[str, str]) -> str:
    """`text` with each secret hidden; `found` gets {the secret as written: what it became}."""
    def hidden(raw: str, shown: str) -> str:
        found[raw] = shown
        return shown

    def digits(m: re.Match) -> str:
        d = re.sub(r"\D", "", m.group())
        return hidden(m.group(), f"{d[:2]}****{d[-2:]}")

    def value(m: re.Match) -> str:
        raw = m.group(2) or m.group(4) or m.group(6)
        return m.group() if raw == "****" else (m.group(1) or m.group(3) or m.group(5)) + hidden(raw, "****")

    text = _ID18.sub(lambda m: digits(m) if _id_checks(m.group()) else m.group(), text)
    text = _CARD_SHOWN.sub(lambda m: digits(m) if _luhn(re.sub(r"\D", "", m.group())) else m.group(), text)
    return _SECRET_VALUE.sub(value, text)


def secret_values(text: str) -> dict[str, str]:
    """{each secret in `text` as written: what `mask` shows for it}, so other lines that repeat it without its word
    hide it too. Values shorter than 4 characters are left out: they would hide ordinary words."""
    found: dict[str, str] = {}
    for form in {str(text or ""), unicodedata.normalize("NFKC", str(text or ""))}:
        _masked(form, found)
    return {raw: shown for raw, shown in found.items() if len(raw) >= 4}


def mask(text: str, values: dict[str, str] | None = None) -> tuple[str, bool]:
    """`text` with what `secret` finds hidden, and whether anything was: an ID or card number keeps its first 2 and
    last 2 digits around ****; a password or code after its word becomes ****; `values` (secret_values of the
    turn's other lines) are hidden wherever they stand. Other text is unchanged."""
    text = str(text or "")
    masked = text
    for raw, shown in (values or {}).items():
        masked = masked.replace(raw, shown)
    if secret(masked):
        hidden = _masked(masked, {})
        if hidden == masked:
            # Full-width digits or letters, as secret() reads them.
            plain = unicodedata.normalize("NFKC", masked)
            hidden = _masked(plain, {})
            hidden = hidden if hidden != plain else masked
        masked = hidden
    return masked, masked != text
