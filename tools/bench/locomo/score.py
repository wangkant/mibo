"""Scores of a LoCoMo run (replay.py): token F1 by LoCoMo's own rule, and an LLM-judged accuracy (J) as mem0 and the
memory papers after it report it.

    python tools/bench/locomo/score.py <out folder> [--answers answers.jsonl] [--keys <file>]
        [--judge openai/gpt-4o-mini] [--budget 0.05] [--data <locomo10.json>]

F1 (the paper's metric, task_eval/evaluation.py eval_question_answering): the answer and the reply lowercased, commas,
punctuation and a/an/the/and taken out, each word Porter-stemmed (nltk), then token F1. Category 1 (multi-hop) splits
both at commas and averages, over the gold parts, the best F1 of any reply part; category 3 (open-domain) keeps the
gold answer before its first ';'; categories 2 and 4 are one F1. Needs nltk (pip install nltk).

J: the judge prompt of mem0's paper (arXiv 2504.19413; mem0ai/mem0 evaluation/metrics/llm_judge.py at aae5989,
Apache-2.0), unchanged, on gpt-4o-mini at temperature 0 with a JSON answer, as there. Verdicts are kept in
<id>/out/judge_<answers file> and not asked again; --keys names the file with LLM_API_KEY and LLM_BASE_URL (an
OpenRouter key), never printed; calls stop at --budget dollars.

Out: <out>/score_<answers file stem>.json and a table on stdout: by category, overall (1-4), by whom the question
is about (the person, the character, both), and by the age of its evidence when asked (all of it from sessions more
than 30 days before: past the chat record's MEMORY_LOG_DAYS)."""
from __future__ import annotations

import argparse
import json
import re
import string
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from nltk.stem import PorterStemmer

from sessions import old

NAMES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop"}
JUDGE_PRICE = (0.15, 0.60)
STEM = PorterStemmer()

# mem0's ACCURACY_PROMPT, word for word (evaluation/metrics/llm_judge.py, mem0ai/mem0 at aae5989, Apache-2.0).
JUDGE = """
Your task is to label an answer to a question as ’CORRECT’ or ’WRONG’. You will be given the following data:
    (1) a question (posed by one user to another user),
    (2) a ’gold’ (ground truth) answer,
    (3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic, for example:
Question: Do you remember what I got the last time I went to Hawaii?
Gold answer: A shell necklace
The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

Now it's time for the real question:
Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}

First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.
Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""


def normalize(s: str) -> str:
    s = s.replace(",", "").lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the|and)\b", " ", s)
    return " ".join(s.split())


def f1_score(prediction: str, truth: str) -> float:
    pred = [STEM.stem(w) for w in normalize(prediction).split()]
    gold = [STEM.stem(w) for w in normalize(truth).split()]
    same = sum((Counter(pred) & Counter(gold)).values())
    if same == 0:
        return 0.0
    precision, recall = same / len(pred), same / len(gold)
    return 2 * precision * recall / (precision + recall)


def f1(row: dict) -> float:
    answer, reply = str(row["answer"]), row["reply"]
    if row["category"] == 3:
        answer = answer.split(";")[0].strip()
    if row["category"] == 1:
        preds = [p.strip() for p in reply.split(",")]
        golds = [g.strip() for g in answer.split(",")]
        return sum(max(f1_score(p, g) for p in preds) for g in golds) / len(golds)
    return f1_score(reply, answer)


def read_keys(path: Path) -> dict:
    pairs = (line.partition("=") for line in path.read_text(encoding="utf-8").splitlines())
    return {k.strip(): v.strip().strip('"') for k, _, v in pairs if k.strip() in ("LLM_API_KEY", "LLM_BASE_URL")}


def judged(row: dict, keys: dict, model: str) -> tuple[int, float, str]:
    """(1 for CORRECT, the call's cost, the judge's words)."""
    body = {"model": model, "temperature": 0.0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": JUDGE.format(
                question=row["question"], gold_answer=row["answer"], generated_answer=row["reply"])}]}
    req = urllib.request.Request(keys["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + keys["LLM_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as answer:
        got = json.loads(answer.read())
    usage = got.get("usage") or {}
    cost = usage.get("cost")
    if cost is None:
        cost = (usage.get("prompt_tokens", 0) * JUDGE_PRICE[0] + usage.get("completion_tokens", 0) * JUDGE_PRICE[1]) / 1e6
    text = got["choices"][0]["message"]["content"]
    # mem0 reads the "label" key; a JSON object is asked for.
    label = str(json.loads(text[text.find("{"):text.rfind("}") + 1]).get("label", "")).upper()
    return int(label == "CORRECT"), float(cost), text


def about(row: dict, person: str, character: str) -> str:
    said = row["question"]
    a, b = re.search(rf"\b{person}\b", said), re.search(rf"\b{character}\b", said)
    return "both" if a and b else "person" if a else "character" if b else "neither"


def table(rows: list[dict], key) -> dict:
    groups: dict = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    out = {}
    for name, group in sorted(groups.items(), key=lambda g: str(g[0])):
        js = [r["j"] for r in group if r.get("j") is not None]
        out[str(name)] = {"n": len(group), "f1": round(100 * sum(r["f1"] for r in group) / len(group), 1),
                          "j": round(100 * sum(js) / len(js), 1) if js else None, "judged": len(js)}
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--answers", default="answers.jsonl")
    ap.add_argument("--keys", type=Path)
    ap.add_argument("--judge", default="openai/gpt-4o-mini")
    ap.add_argument("--budget", type=float, default=0.05)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args(argv)
    data = {s["sample_id"]: s for s in json.loads(args.data.read_text(encoding="utf-8"))}
    keys = read_keys(args.keys) if args.keys else None
    spent, rows = 0.0, []
    for path in sorted(args.out.glob(f"*/out/{args.answers}")):
        sample = data[path.parents[1].name]
        conv = sample["conversation"]
        cache = path.with_name("judge_" + args.answers)
        verdicts = {json.loads(line)["k"]: json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()} \
            if cache.exists() else {}
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            row.update(conv=sample["sample_id"], f1=f1(row), about=about(row, conv["speaker_a"], conv["speaker_b"]),
                       old=old(row, conv))
            if keys and row["k"] not in verdicts and spent < args.budget:
                j, cost, words = judged(row, keys, args.judge)
                spent += cost
                verdicts[row["k"]] = {"k": row["k"], "j": j, "words": words, "cost": round(cost, 7)}
                with cache.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(verdicts[row["k"]], ensure_ascii=False) + "\n")
            row["j"] = verdicts[row["k"]]["j"] if row["k"] in verdicts else None
            rows.append(row)
    result = {"answers": args.answers, "judge": args.judge if keys or any(r["j"] is not None for r in rows) else None,
              "judge_spent_now": round(spent, 5), "convs": sorted({r["conv"] for r in rows}),
              "overall": table(rows, lambda r: "1-4")["1-4"] if rows else {},
              "by_category": table(rows, lambda r: f"{r['category']} {NAMES[r['category']]}"),
              "by_conv": table(rows, lambda r: r["conv"]), "by_about": table(rows, lambda r: r["about"]),
              "by_evidence_age": table(rows, lambda r: "older than 30 days" if r["old"] else "within 30 days"),
              "refused_by_budget": sum(bool(r.get("refused")) for r in rows),
              "cost_answers": round(sum(r.get("cost", 0) for r in rows), 5)}
    (args.out / f"score_{Path(args.answers).stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                                    encoding="utf-8")
    print(f"| group | n | F1 | J ({result['judge']}) |\n|---|---|---|---|")
    for part in ("overall", "by_category", "by_conv", "by_about", "by_evidence_age"):
        groups = {"1-4": result["overall"]} if part == "overall" else result[part]
        for name, g in groups.items():
            print(f"| {name} | {g['n']} | {g['f1']} | {g['j'] if g['j'] is not None else '-'} |")
    print(json.dumps({k: result[k] for k in ("judge_spent_now", "refused_by_budget", "cost_answers")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
