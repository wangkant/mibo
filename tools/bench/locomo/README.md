# LoCoMo bench for the memory

Mibo's memory on LoCoMo, the long-conversation memory benchmark memory products report on: one conversation fed to
the app as one person's chat with the character over its dated sessions, then each question asked once, in its own
words, in a fresh chat, and the reply scored by the benchmark's own F1 and by an LLM judge.

| | |
|---|---|
| Benchmark | LoCoMo (Maharana et al., ACL 2024, arXiv 2402.17753): `data/locomo10.json`, 10 conversations of 19 to 32 dated sessions, 1,986 questions in five categories |
| Source | https://github.com/snap-research/locomo at 3eb6f2c (2024-08-13); `locomo10.json` sha256 79fa87e9…ff4 |
| Licence | CC BY-NC 4.0 (`LICENSE.txt`): the data is fetched outside the repository and never committed; this folder holds no part of it |
| Questions | Categories 1-4 (1 multi-hop, 2 temporal, 3 open-domain, 4 single-hop; the numbers as `task_eval/evaluation.py` treats them). Category 5 (adversarial) is left out, as mem0 and the memory papers after it leave it out |
| F1 | `task_eval/evaluation.py` `eval_question_answering`, rewritten in `score.py` (Porter stems from nltk); equal to the original on every row of a run (`largest row difference 0`) |
| J | mem0's judge prompt (arXiv 2504.19413; `evaluation/metrics/llm_judge.py`, mem0ai/mem0 at aae5989, Apache-2.0), word for word in `score.py`, on `openai/gpt-4o-mini` at temperature 0. Labelled J (gpt-4o-mini, mem0 prompt) wherever it is shown |

Fetch the data outside the repository:

```
curl -O https://raw.githubusercontent.com/snap-research/locomo/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json
```

## Run

```
python tools/bench/locomo/replay.py --data <locomo10.json> --out <folder> --mode oracle --only conv-30
python tools/bench/locomo/replay.py --data <locomo10.json> --out <folder> --keys <file> [--convs 2] [--seed 20261121] [--budget 0.60]
python tools/bench/locomo/replay.py --data <locomo10.json> --out <other folder> --keys <file> --mode off --only <id> [--every 6]
python tools/bench/locomo/score.py <folder> --data <locomo10.json> [--answers answers.jsonl] [--keys <file>] [--budget 0.05]
python tools/bench/locomo/trace.py <folder> [--answers answers.jsonl]
```

`replay.py` runs on the `.venv-web-platforms` interpreter from the repository root (the checkout's own `mibo`);
`score.py` and `trace.py` need only nltk (`pip install nltk`), in any interpreter. `--keys` names a file with
`LLM_API_KEY` and `LLM_BASE_URL` (OpenRouter); the key is never printed and reaches the app only through its
environment (`tools/scratchhome.py`). Every model call passes through `tools/everyday.py`'s Meter on `--port` + 1,
which refuses calls past `--budget` dollars; `score.py` stops judging at its own `--budget`.

- `--mode oracle` answers each question with its gold answer through the app's whole reply path: the scorer's top.
  With no `--keys` the app's memory calls go to a stand-in model and nothing is spent.
- `--mode off` feeds a fresh home with memory off in Settings › Memory and no chat record (`MEMORY_LOG_DAYS=0`)
  from the start, and asks only the questions whose evidence is all older than the chat record's 30 days: the floor
  of what needs an old session. Give it its own `--out`.
- `--resume` starts a fed home again and asks the questions its answers file does not hold yet (after a budget cut).
- `--convs N --seed S` draws N conversations with `random.Random(S).sample` over the ten ids in file order; `--only`
  names them instead. `--every N` asks the questions whose index is a multiple of N.

Out, under `<folder>`: `run.json` (mode, model, seed, drawn ids, commit, command, spent), `model.jsonl` and
`model-full.jsonl` (every call, whole), and per conversation `<id>/out/`: `answers*.jsonl` (reply, steps, memories
shown as used, the range of its calls), `feed.jsonl`, `folds.jsonl` (each fold's answer and what came of it),
`calls.jsonl` (each call's purpose), `person_s<N>.json` (the store after session N's fold), `person_end.json`,
`chatlog_end.json` (the chat record the questions found), `judge_*.jsonl`; `score_*.json`, `trace_*.json`.

## How the run stands in for the person

The app is one character talking with one person, so the conversation is put in as that:

- **Speakers.** speaker_a is the person, speaker_b the character; the character's name in the app is speaker_b's.
  Before the first session the person says "Remember that my name is <speaker_a>." (the app's remember command), as
  on a first day: nothing in LoCoMo has a person say their own name.
- **Turns.** Each line of the person's is a message in the app's main chat through its own chat interface
  (`POST /api/chat`), so the app's turn path takes it in: its chat record, the page's copy, the person's store after
  the turn, compaction and the fold's own triggers. The character's answer is the next line of speaker_b, handed to
  the reply loop in place of the model's answer: a turn of the feed makes no model call; only the app's memory calls
  (fold, compaction) go to the model. A session that ends on the person's line is answered "Talk soon!". A session
  speaker_b opens has that line put in the chat's turns as the app keeps a line the character says unasked
  (`followup.py`'s commit). A shared photo is its BLIP caption after the words: "… [shared a photo: <caption>]", as
  LoCoMo's own evaluation adds it.
- **Time.** The app runs on a movable clock: `tools/memory_life.py`'s sitecustomize makes `time.time`,
  `datetime.now` and `date.today` in the app's process give the session's date (the app has no clock setting of its
  own). Each session starts at its date and time, a line a minute. Six minutes after its last line (past the fold's
  five minutes of quiet) the fold's trigger `Agent._maybe_fold_person`, which the app's minute loop calls, is called
  at once instead of waiting up to a minute for the loop. The questions come at 10:00 the day after the last session,
  after the chat record is pruned as the app's daily round prunes it (`ChatLog.prune`, `MEMORY_LOG_DAYS` 30).
- **Questions.** Each in a new chat (`POST /api/chats`), the question's words alone, no instruction added; the app's
  reply loop answers with its own recall (the store, past chats) and tools. The chat is deleted afterwards, so no
  later question finds it in past-chat search. While the questions run the fold is held (marked running), so every
  question sees the same store.
- **Language.** `AGENT_LANG=en`: LoCoMo is English.
- **Offline.** The app's process reaches no host but this computer (its model is the Meter on 127.0.0.1): a public
  copy of LoCoMo is on the web, and a reply loop that searches finds it. Name lookups for other hosts fail in the
  app's process (the sitecustomize), and ddgs's own client is given a proxy that is not there (`DDGS_PROXY`).

## Results of 2026-11-21

Partial: 2 of 10 conversations, drawn with `--seed 20261121` (conv-49, conv-41, the first two of the draw). Model
`deepseek/deepseek-v4.1-flash` for the app's every call; J by `openai/gpt-4o-mini` with mem0's prompt. Commit 42d9ec8.
conv-49: all 156 category 1-4 questions (multi-hop 37, temporal 33, open-domain 13, single-hop 73); conv-41: every
4th by index, 38 questions (8, 7, 2, 21), offline. 72 cents in all, judge and the two discarded runs below included.

| | n | F1 | J (gpt-4o-mini, mem0 prompt) |
|---|---|---|---|
| both conversations, categories 1-4 | 194 | 4.7 | 24.2 |
| multi-hop / temporal / open-domain / single-hop | 45 / 40 / 15 / 94 | | 24.4 / 15.0 / 46.7 / 24.5 |
| conv-49 / conv-41 | 156 / 38 | 4.6 / 5.0 | 25.6 / 18.4 |
| evidence all older than 30 days / within 30 days (conv-49) | 107 / 49 | 3.3 / 7.5 | 7.5 / 65.3 |
| evidence all older than 30 days / within 30 days (conv-41) | 26 / 12 | 2.7 / 9.9 | 0.0 / 58.3 |
| stand-in: gold answers through the reply path (conv-49) | 156 | 100.0 | 100.0 |
| stand-in: memory off, old-evidence questions, every 6th (conv-49) | 17 | 2.0 | 0.0 |
| the real run on those same 17 | 17 | | 0.0 |

```
python tools/bench/locomo/replay.py --data <locomo10.json> --out run --only conv-49 --keys <file> --budget 0.50
python tools/bench/locomo/replay.py --data <locomo10.json> --out run2 --only conv-41 --every 4 --keys <file> --budget 0.14 --port 61490
python tools/bench/locomo/replay.py --data <locomo10.json> --out oracle --only conv-49 --mode oracle --port 61484
python tools/bench/locomo/replay.py --data <locomo10.json> --out run_off --only conv-49 --mode off --every 6 --keys <file> --budget 0.055 --port 61486
```

The conv-49 real run was made before the bench took the app offline; none of its 767 requests holds the web copy of
LoCoMo. Two earlier memory-off runs did reach it (`mirarto-atelier.github.io`) and were discarded; the second showed
the app recalling that page in later fresh chats from what it had read.

## Comparing with published numbers

`published.json` lists what the LoCoMo paper, mem0's paper and vendor pages report. None of it is on equal terms with
a run of this bench:

- Their answer prompt asks for a short phrase in the conversation's words; here the question is asked alone and the
  reply is a companion's. F1 punishes every extra word, so F1 here is far below theirs for the same knowledge; J
  forgives length.
- They keep what both speakers said; the app keeps what the person says of themselves (the character's own lines
  are never a source of facts), so questions about speaker_b depend on the chat record alone.
- They read all ten conversations; a partial run reads one or two.
- mem0's current harness (mem0ai/memory-benchmarks) and vendor pages use far more lenient judges (partial credit,
  14 days of date tolerance) and stronger answer models; their 90+ are not comparable to J with the prompt above.
- About 6.4% of the gold answers are wrong (Penfield Labs' audit), and the gpt-4o-mini judge accepts many vague
  answers.
