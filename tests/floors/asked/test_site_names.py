"""A site is what the person and the public list of domains say it is (situation.site_of, acting.sensitive,
crossing.named): mail, payment, account and console hosts of a large company are sensitive by their own full host,
whatever their registrable host is; a host shared by many owners' sites (github.io, vercel.app) is one site per owner;
a site is named by its host or a name the app knows for it as whole words, never by a few letters inside other words;
and only a whole span of the person's own words is theirs to type. (2026-11-23 review of 8b57f6f: mail.google.com,
pay.google.com, console.aws.amazon.com and others came out not sensitive; alice.github.io and bob.github.io were one
site; "translate this" named ate.xyz, "go translate" named go.dev, "打开deepl翻译" named deepl.xyz; typing "1" counted as
the person's words.)"""
from __future__ import annotations

import pytest

from mibo import acting, crossing
from mibo.situation import site_of

SENSITIVE_HOSTS = ("mail.google.com", "pay.google.com", "wallet.google.com", "myaccount.google.com",
                   "outlook.live.com", "console.aws.amazon.com", "health.apple.com")
SHARED = ("github.io", "vercel.app", "pages.dev", "herokuapp.com", "appspot.com", "azurewebsites.net", "netlify.app",
          "blogspot.com", "s3.amazonaws.com")


@pytest.mark.parametrize("host", SENSITIVE_HOSTS)
def test_a_sensitive_host_is_judged_by_its_full_host_and_every_act_there_is_asked(host):
    assert acting.sensitive(f"https://{host}/inbox") and acting.sensitive(host)
    assert acting.decide("auto", "outward", host) == "ask"


def test_banks_payment_services_and_mail_by_name_or_a_bank_in_the_registrable_name_ask_for_every_act():
    for host in ("bankofamerica.com", "secure.bankofamerica.com", "capitalone.com", "americanexpress.com", "usbank.com",
                 "wise.com", "revolut.com", "cash.app", "fastmail.com", "aol.com", "zoho.com", "www.firstbankpr.com",
                 "online.citizensbank.co.uk"):
        assert acting.sensitive(f"https://{host}/") and acting.decide("auto", "outward", host) == "ask", host
    # A page about banks on another site is not a bank.
    assert not acting.sensitive("https://news.example.com/banks") and not acting.sensitive(
        "https://www.example.com/banking-news")


def test_a_page_of_account_or_payment_is_sensitive_on_any_site_and_an_ordinary_one_is_not():
    for url in ("https://example.com/account/security", "https://shop.example/checkout", "https://example.com/billing"):
        assert acting.sensitive(url), url
    for url in ("https://www.deepl.com/translator", "https://news.example.com/2026/11/story"):
        assert not acting.sensitive(url), url


@pytest.mark.parametrize("suffix", SHARED)
def test_each_owner_on_a_shared_host_is_a_site_of_its_own(suffix):
    assert site_of(f"https://alice.{suffix}/") != site_of(f"https://bob.{suffix}/")
    assert site_of(f"https://www.alice.{suffix}/x") == site_of(f"https://alice.{suffix}/")


def test_the_public_suffix_list_ships_whole_with_its_private_section_and_its_rules_hold():
    from mibo.situation import SUFFIXES
    text = SUFFIXES.read_text(encoding="utf-8")
    assert "// VERSION:" in text and "===BEGIN ICANN DOMAINS===" in text and "===BEGIN PRIVATE DOMAINS===" in text
    # A plain rule, a wildcard and its exception.
    assert site_of("https://news.bbc.co.uk/") == "bbc.co.uk"
    assert site_of("https://shop.a.b.ck/") == "a.b.ck" and site_of("https://x.www.ck/") == "www.ck"


def test_a_site_is_named_by_whole_words_only():
    for site, words in (("ate.xyz", "translate this"), ("lat.top", "translate this"), ("go.dev", "go translate"),
                        ("deepl.xyz", "打开deepl翻译")):  # copy: voice
        assert not crossing.named(site, words, site=True), (site, words)
    for words in ("打开deepl然后将中文你好翻译成英文", "去 deepl.com 翻译一下", "open DEEPL"):  # copy: voice
        assert crossing.named("deepl.com", words, site=True), words


def test_only_a_whole_span_of_their_words_is_theirs_to_type():
    said = "打开 deepl 然后将中文你好翻译成英文, ok 1"  # copy: voice
    assert crossing.own_words("你好", said) and crossing.own_words("deepl", said)  # copy: voice
    for typed in ("1", "ok", "然", "e"):  # copy: voice
        assert not crossing.own_words(typed, said), typed


def test_a_settings_subscription_admin_or_tokens_page_is_sensitive_however_its_address_is_written():
    """(2026-11-23 review of 0368fcc: /settings/privacy, /subscription/cancel, github.com/settings/tokens,
    /admin/users/1/delete and /%61ccount were ordinary pages, and [::1] was the site "[".)"""
    for page in ("https://example.com/settings/privacy", "https://example.com/subscription/cancel",
                 "https://github.com/settings/tokens", "https://example.com/admin/users/1/delete",
                 "https://example.com/%61ccount", "https://example.com/%2561ccount/x", "https://example.com/BILLING",
                 "https://example.com/user/security"):
        assert acting.sensitive(page), page
    assert not acting.sensitive("https://example.com/settlement-report") and not acting.sensitive(
        "https://example.com/blog/admins-guide")
    assert [site_of(a) for a in ("[::1]", "[::1]:8080/x", "http://[::1]:8080/x", "fe80::1")] == ["::1", "::1", "::1",
                                                                                                  "fe80::1"]
