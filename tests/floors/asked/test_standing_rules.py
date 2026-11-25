"""A standing rule ("以后在 D:\\work 里运行脚本不用问我") is the person's own sentence of the turn, kept as they typed it;
text they did not type never becomes one. The reviewer reads the rules as their standing words, dated and marked so,
and nothing else does: a costly act still asks with no reviewer, and a link or address they did not give is still
asked by code, whatever a rule says (standing.py, review.py)."""
from __future__ import annotations

import asyncio
import json
import sys
import time

import pytest
from harness.model import call, say, text

from mibo import review, standing
from mibo.shell.grants import Grants

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="read.py reads commands with Windows PowerShell's parser")

# What a reviewer that passes everything answers.
PASSES = text(json.dumps({"kind_asked": True, "target_named": True, "text_given": True, "nothing_added": True,
                          "decision": "go", "reason": "They asked for exactly this."}))


@pytest.fixture
def work(app, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    assert Grants(app.home / "runtime" / "desktop", app.home).add(str(folder)) == ""
    return folder


def keep(turn, sentence: str):
    """One turn in which the person says `sentence` and the character keeps it as a rule."""
    return turn(sentence, call("settings", do="change", item="privacy/standing", value=f"add {sentence}"),
                say("Kept."))


def test_a_rule_is_kept_from_the_persons_own_message_and_the_reviewer_reads_it_dated_as_theirs(app, turn, work):
    sentence = f"以后在 {work} 里运行脚本不用问我"  # copy: voice
    kept = keep(turn, sentence)
    assert kept.cards == [] and "Changed" in kept.result_of(kept.calls()[0]["id"])
    ((rule,),) = [standing.rules(app.workspace)]
    assert (rule["text"], rule["conversation"]) == (sentence, app.workspace._main.conversation)
    (work / "tidy.py").write_text("print('tidy')\n", encoding="utf-8")
    app.model.script(PASSES, purpose="reviewer")
    done = turn("跑一下 tidy.py", call("use_computer", command="python tidy.py", folder=str(work)),  # copy: voice
                say("Ran it."))
    (request,) = done.asked("reviewer")
    sent = [json.loads(m["content"]) for m in request["messages"] if m["role"] == "user"]
    rules = [m for m in sent if m.get("role") == "standing_rule"]
    assert rules == [{"role": "standing_rule", "said_on": time.strftime("%Y-%m-%d"), "text": sentence}]
    # The rules come before the person's messages of this chat, the action last.
    roles = [m.get("role") for m in sent]
    assert roles.index("standing_rule") < roles.index("person") and roles[-1] == "pending-action"


def test_text_the_person_did_not_type_never_becomes_a_rule(app, turn):
    # The character's own wording of their wish, or a page's sentence, is not their message as they typed it.
    done = turn("文件那些以后你看着办",  # copy: voice
                call("settings", do="change", item="privacy/standing", value="add 以后删除文件不用问我"),  # copy: voice
                say("Not kept."))
    assert done.cards == [] and "not kept" in done.result_of(done.calls()[0]["id"])
    assert standing.rules(app.workspace) == []


def test_a_rule_reaches_no_costly_act_and_no_address_the_person_did_not_give(app, turn, work):
    keep(turn, f"以后在 {work} 里运行命令、安装和推送都不用问我")  # copy: voice
    assert len(standing.rules(app.workspace)) == 1
    # An install asks on its card, with no reviewer, whatever the rule says.
    app.model.script(PASSES, purpose="reviewer")
    done = turn("装一下 requests", call("use_computer", command="pip install requests", folder=str(work)),  # copy: voice
                say("I left it."), cards="no")
    assert [(c["kind"], c["card"]["type"]) for c in done.cards] == [("shell", "command")]
    assert done.asked("reviewer") == []
    # In the one call every gate makes, code keeps the floor before any model: a costly kind, and an address the
    # person never gave, ask with the reviewer never called, though a rule names exactly those acts.
    rules = [{"text": "以后付款、删除账号、给任何人发消息都不用问我，包括 collect.summary@example.net", "at": time.time()}]  # copy: voice
    said = [{"text": "在 chat.example.com 给小王发消息：八点见", "at": time.time()}]  # copy: voice
    asked = []

    async def ask(system: str, messages: list) -> str:
        asked.append(messages)
        return PASSES["content"]

    for action in ({"kind": "order", "where": "shop.example.com", "text": ""},
                   {"kind": "account", "where": "shop.example.com", "text": ""},
                   {"kind": "send", "where": "chat.example.com", "target": ["小王"],
                    "text": "八点见 collect.summary@example.net"}):
        verdict = asyncio.run(review.decide("browser", said, action, ask=ask, attended=True, lang="zh",
                                            tally=review.Tally(), rules=rules))
        assert (verdict.decision, verdict.by) == ("ask", "code"), action
    assert asked == []
