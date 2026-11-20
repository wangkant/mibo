"use strict";
// The interface's words: one catalog per language (persona_agent/locales/<code>.json, i18next's JSON
// layout: a namespace per script, plural forms as key_one, key_other and so on, key_zero for none),
// the same files the Python side reads. /locale.js hands the page its language and catalog before the
// other scripts run; a missing word falls back to English, then to its key.
window.paI18n = (() => {
  // The ten languages, each in its own words.
  const LANGUAGES = [
    ["zh", "简体中文"],
    ["en", "English"],
    ["zh-TW", "繁體中文"],
    ["ja", "日本語"],
    ["ko", "한국어"],
    ["es", "Español"],
    ["fr", "Français"],
    ["de", "Deutsch"],
    ["pt-BR", "Português (Brasil)"],
    ["ru", "Русский"],
  ];
  // Every open window of the app: one that changed the language says so, and the others start again in it.
  const windows = new BroadcastChannel("mibo-language");
  windows.onmessage = () => location.reload();
  let lang = "en";
  let strings = {};
  let english = {};
  const merged = new Map();

  const find = (tree, key) =>
    key.split(".").reduce((node, part) => (node && typeof node === "object" ? node[part] : undefined), tree);
  const fill = (text, values = {}) =>
    String(text).replace(/\{(\w+)\}/g, (whole, name) => (name in values ? String(values[name]) : whole));

  // A count picks the language's own plural form (Intl.PluralRules); none takes key_zero when there is one.
  function pick(tree, code, key, count) {
    if (typeof count === "number") {
      const forms = [...(count === 0 ? ["zero"] : []), new Intl.PluralRules(code).select(count), "other"];
      for (const form of forms) {
        const found = find(tree, `${key}_${form}`);
        if (typeof found === "string") return found;
      }
    }
    return find(tree, key);
  }

  function t(key, values = {}) {
    const found = pick(strings, lang, key, values.count) ?? pick(english, "en", key, values.count);
    return typeof found === "string" ? fill(found, values) : key;
  }

  function overlay(base, over) {
    if (over === undefined) return base;
    if (!base || typeof base !== "object" || Array.isArray(base) || !over || typeof over !== "object" || Array.isArray(over))
      return over;
    const out = { ...base };
    for (const [key, value] of Object.entries(over)) out[key] = overlay(base[key], value);
    return out;
  }

  // A namespace's words as one object, the language's over English's.
  function words(ns) {
    if (!merged.has(ns)) merged.set(ns, overlay(english[ns] || {}, strings[ns]));
    return merged.get(ns);
  }

  function load(code, catalog, fallback) {
    lang = code;
    strings = catalog;
    english = fallback || english;
    merged.clear();
    document.documentElement.lang = code === "zh" ? "zh-CN" : code;
  }

  // Another language now: its catalog is fetched, and the page draws itself again.
  async function use(code) {
    if (code === lang) return;
    const response = await fetch(`/assets/locales/${encodeURIComponent(code)}.json`, { cache: "no-store" });
    if (!response.ok) throw new Error("language_unknown");
    load(code, await response.json());
  }

  return {
    t,
    fill,
    words,
    load,
    use,
    languages: LANGUAGES,
    // This window changed the language: the others start again in it.
    told: () => windows.postMessage(lang),
    get lang() {
      return lang;
    },
    // The language as a locale for Intl and toLocale*: Chinese as written in mainland China.
    get locale() {
      return lang === "zh" ? "zh-CN" : lang;
    },
  };
})();
