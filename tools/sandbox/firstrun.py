"""The first-run suite: a new home's first run walked in the app's real window, step by step as a person walks it
(a language picked, the character, the model already connected, a topic of their own, a line about themselves),
then the chat it opens on and one turn with the stand-in model. A picture of the screen at each step.

    python tools/sandbox/firstrun.py --out <folder>

The presses are the page's own buttons pressed through the window's bridge, the same on all three systems.
"""
from __future__ import annotations

import json
import sys
import time

from _suite import Suite, Window, api, scratch_home, scrub_env, stand_in_model
from package_smoke import REPLY

F = "first run"
VISIBLE = "(s => { const e = document.querySelector(s); return !!e && !e.closest('[hidden]') && e.getClientRects().length > 0; })"
STEP = "[...document.querySelectorAll('.onboard-dot')].findIndex(d => d.classList.contains('onboard-dot-now'))"
SET = ("((s, v) => { const e = document.querySelector(s); e.value = v;"
       " e.dispatchEvent(new Event('input', {bubbles: true})); return true; })")
TOPIC = "沙盒测试"  # copy: voice


def walk(w: Window, suite: Suite) -> None:

    def press(selector):
        return w.js(f"(() => {{ const b = document.querySelector({json.dumps(selector)}); if (!b || b.disabled) return false; b.click(); return true; }})()")

    def shown(selector, seconds=20):
        return w.until(f"{VISIBLE}({json.dumps(selector)})", seconds) is True

    def at(n, seconds=20):
        return w.until(f"{STEP} === {n}", seconds) is True

    if sys.platform == "win32":
        # The app starts as the figure alone; opening the window is what its double-click does.
        w.app.show()
    suite.check(F, "a new home opens on the first run", shown("#onboard-view", 30))
    suite.check(F, "it starts on the language step", at(0), w.js(STEP))
    suite.shot("1-language")
    press(".onboard-lang[lang='en']")
    suite.check(F, "picking English turns the screens to English", w.until("paI18n.lang === 'en'", 15) is True,
                w.js("paI18n.lang"))
    press(".onboard-next")
    suite.check(F, "Next goes to the character", at(1))
    suite.check(F, "the characters are offered", w.until("document.querySelectorAll('.onboard-characters button').length > 0", 20) is True)
    suite.shot("2-character")
    press(".onboard-next")
    suite.check(F, "Next goes to the model", at(2))
    suite.check(F, "the model from the home's settings shows as connected", shown(".onboard-connected"))
    suite.shot("3-model")
    press(".onboard-next")
    suite.check(F, "Next goes to the topics", at(3))
    w.js(f"{SET}('.onboard-add .onboard-field', {json.dumps(TOPIC)})")
    w.js("document.querySelector('.onboard-add').requestSubmit()")
    suite.check(F, "a topic of their own is added and picked",
                w.until(f"[...document.querySelectorAll('.onboard-chip')].some(c => c.dataset.name === {json.dumps(TOPIC)}"
                        " && c.getAttribute('aria-pressed') === 'true')", 10) is True)
    suite.shot("4-topics")
    press(".onboard-next")
    # The round of finds goes out to the web for the topic; its wait is skipped as a person may.
    deadline = time.time() + 60
    while time.time() < deadline and w.js(STEP) != 4:
        if w.js(f"{VISIBLE}('.onboard-skip')"):
            press(".onboard-skip")
        time.sleep(2)
    suite.check(F, "the topics step goes on to the last look", at(4, 5))
    saved = api(w.home, "feed/interests?lang=en")
    suite.check(F, "the topic was saved", TOPIC in json.dumps(saved, ensure_ascii=False), saved)
    if shown(".onboard-tell-field", 10):
        w.js(f"{SET}('.onboard-tell-field', 'I like quiet mornings and long walks.')")  # copy: voice
        press(".onboard-tell-button")
        suite.check(F, "their own words are told and kept", shown(".onboard-told", 60))
    else:
        suite.check(F, "the last look asks for their own words", False)
    suite.shot("5-about")
    press(".onboard-next")
    suite.check(F, "Finish opens the chat", w.until(f"!{VISIBLE}('#onboard-view') && {VISIBLE}('#chat-view')", 30) is True,
                w.views())
    suite.check(F, "the first run is kept as walked", api(w.home, "look").get("toured") is True)
    w.until("!!document.querySelector('#chat-view .chat-input')", 20)
    w.js(f"{SET}('#chat-view .chat-input', 'hello')")
    w.js("document.querySelector('#chat-view .chat-composer').requestSubmit()")
    answered = w.until(f"document.querySelector('#chat-view .chat-messages').innerText.includes({json.dumps(REPLY)})", 90)
    suite.check(F, "the character answers its first message", answered is True)
    suite.shot("6-chat")
    suite.check(F, "nothing was sent to the system browser", not w.sent_to_browser, w.sent_to_browser)


def main() -> int:
    suite = Suite("firstrun", __doc__.split("\n\n")[0])
    scrub_env()
    home = scratch_home(stand_in_model(), lang="zh")
    window = Window(suite, home)
    code = window.run(lambda w: walk(w, suite))
    suite.check("window", "mibo start returns 0 once the window closes", code == 0, code)
    return suite.finish()


if __name__ == "__main__":
    sys.exit(main())
