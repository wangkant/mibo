# MiniWoB++ bench for the browser hands

MiniWoB++ as BrowserGym defines it: the 125 tasks of its benchmark list, AgentLab's five seeds each, scored by
BrowserGym's own rule. The agent is Mibo as a person uses it on a page: the task's page open in the app's own
browser, the goal typed once in a private chat beside the page, and the reply loop doing the rest with its own tools
(`look` and `act`, `mibo/surface.py`; every step through `web/operate.Hands` and `gate.py`) in one chat turn. The app
is served in the bench's process; its browser is the stand-in pane of the tests (`tests/harness/pane.py`) over a
headless Edge, so nothing shows on the screen.

## Data and sources

| what | where | commit | licence |
|---|---|---|---|
| Task pages (`miniwob/html`, 5.6 MB) | github.com/Farama-Foundation/miniwob-plusplus | 7fd85d7, the one BrowserGym's miniwob README pins | MIT |
| Task list, seeds, set-up, scorer | github.com/ServiceNow/BrowserGym (`browsergym/miniwob`, `experiments/benchmark`) | 62a678f | Apache-2.0 |
| Agent settings, step limit | github.com/ServiceNow/AgentLab (`agents/generic_agent`) | 8488c56 | Apache-2.0 |

Fetch the pages outside the repo (a sparse clone, then the pinned commit):

```
git clone --filter=blob:none --sparse https://github.com/Farama-Foundation/miniwob-plusplus.git miniwob
cd miniwob && git sparse-checkout set miniwob/html && git checkout 7fd85d71a4b60325c6585396ec4f48377d049838
```

The pages are served read-only from 127.0.0.1 to the headless tab; nothing in the download is run by Python.

## Run

```
python -I tools/bench/miniwob/proof.py --data <miniwob/html> --out <folder>
python -I tools/bench/miniwob/run.py --env <.env with LLM_API_KEY and LLM_BASE_URL> --data <miniwob/html> --out <folder> [--budget 0.50]
python -I tools/bench/miniwob/report.py <folder> [<result .json>] [--seeds 1] [--before <folder of an earlier run>]
```

Python: the `.venv-web-platforms` interpreter (playwright, httpx, the app's own packages). `--tasks all|forty|a,b`
(default all 125; `forty` is the list this repository picked before), `--repeats 1` (the first N of AgentLab's five
seeds a task), `--workers 2` (one process each, below-normal priority, each with its own home, app and browser),
`--ports 61280` (four a worker: app, meter, pages), `--model <openrouter id>`.

- The key is read from `--env` by the parent and handed to the workers in their environment; the app reads it
  from there through a stand-in of the credential store. Nothing of it is written or printed. The home's
  `settings.json` holds the rest (the model's address is the worker's meter).
- The model is measured by the app's own check at its start, as for a person; nothing is set by its name.
- Every model call passes through `tools/everyday.py`'s Meter; each worker holds `--budget / workers` dollars and
  refuses calls past it. A cut is listed in `run.json` (`not_run`).
- `<folder>/results.jsonl` holds one line an episode (a rerun skips the episodes already there), `episodes/` each
  episode's reply and steps with the range of its lines in `w<k>/model-full.jsonl` (every request and answer).
- `report.py --seeds N` scores the first N seeds a task; `--before` sets an earlier run beside this one: tasks won
  and lost, and what an episode took in each. `<folder>/causes.json` (`{"task-index": [cause, evidence, fault]}`)
  holds causes read from the traces.

## How the bench stands in for the person

- The task's tab is in front of the pane, at BrowserGym's 332x214 viewport, in a fresh browsing context each
  episode.
- The message is the goal word for word, with the turn choice the chat beside the page sends (`page`, browse.js), so
  the page in front comes looked at.
- Cards: every card of the app's browser is answered yes, this once; cards of the app's other places (commands and
  files, programs, MCP, switches) no. The app's floors stay: a password field is never typed into.
- The episode ends as BrowserGym's does: when the page's reward fires the turn is stopped as the stop button stops
  it, and the score is what the page held then. A turn is also stopped after 420 s.

## Faithfulness proof (`proof.py`, no real model)

- Untouched: all 125 tasks set up and scored at once give reward 0 and not done.
- BrowserGym's own reference solutions (`tests/miniwob` test_cheat: click-scroll-list, click-menu-2,
  use-colorwheel-2, seeds 0-4) through `run.setup` and `run.score`: reward 1. A wrong answer: reward 0 for the two
  tasks with one right answer; a wrong colour on use-colorwheel-2 can score, as BrowserGym counts any raw reward
  above 0 and that task gives partial credit for a near colour.
- The app driven by `run.episode` with a scripted stand-in model behind the same Meter (click-button, enter-text,
  click-scroll-list, two seeds): one act with the right answer scores 1, a wrong one 0, an idle reply 0, and a
  command asked for instead gets its card answered no within 60 s.

## What is AgentLab's and what differs

Same as AgentLab: the 125 tasks; the seeds (`RandomState(42).randint(0, SEED_MAX, 5)` task after task, where
`SEED_MAX = 2 ^ 32` is 34 in Python, so seeds repeat); the page seed drawn from each; the 332x214 viewport; the
human display removed (the goal is only in the task's words); episode time 1,000,000 ms; the score (raw reward
above 0 on the task's own address); the episode ending when the reward fires.

| | AgentLab GenericAgent | this bench |
|---|---|---|
| agent | GenericAgent, one LLM call a step | Mibo's reply loop, one chat turn |
| observation | AXTree and pruned HTML, action history, thinking | the page in front looked at with the message; each act answers with the page after it; a picture when the model asks and the app measured it takes pictures |
| actions | `miniwob_all`: click, fill, press, type, scroll by element id, mouse by coordinates; one a step | `act`'s steps (click, type, select_option, key, hover, drag, scroll_to, wait_for, go, back, read), up to 8 a call |
| step limit | 10 steps | the app's own ceilings; `reward10` is the score when the tenth action on the page had been made |
| cards | none | answered by the rule above |
