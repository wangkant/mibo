# Harness-Bench through Mibo, without Docker

Harness-Bench (Qihoo 360, arXiv:2605.27922) measures agent harnesses on 274 offline workflow tasks: each task ships
an instruction, a starting workspace and a hidden oracle, and a harness is scored on what it leaves in the workspace.
The benchmark runs every harness in a Debian container and grades in another. `run.py` runs the tasks through Mibo
on this computer and grades with the benchmark's own code in a process of its own (`grade.py`).

## Data and sources

| what | where | commit | licence |
|---|---|---|---|
| Tasks, oracles, grading code | github.com/Qihoo360/harness-bench | b8d8963 | see the repository |
| Published results | `published.json` (the paper's Table 2 and the leaderboard's pooled rows) | fetched 2026-11-24 | |

Check the benchmark out with Unix line endings (`git config core.autocrlf false; git config core.eol lf`): its
oracles compare digests of the workspace's files.

## Which tasks count

`check` admits a task when it has one prompt and no hooks or services of the controller, needs nothing but Python
(its standard library and the packages listed in `run.py`), its untouched workspace does not pass, and its own
reference answer laid over the workspace passes here. On Windows with Python 3.13 that is 254 of the 274
(2026-11-24): 11 reference answers do not pass here, 5 tasks need git, 2 need the controller's rounds or hooks, 1
needs fork, 1 has no weighted score.

## Run

```
python tools/bench/harnessbench/run.py check --checkout <harness-bench> --work <folder> --python <3.12+ with PyYAML>
python tools/bench/harnessbench/run.py run --checkout <harness-bench> --work <folder> --python <...> --keys <.env>
                                           [--sample 16 --seed 7] [--only <ids>] [--part 1/2 --port 59731]
```

`run.py`'s first lines say how the bench stands in for the benchmark's controller and for the person: the prompt, the
interpreter, the questions answered, the turns, and that the app is kept to this computer (`tools/offline.py`).

## What differs from the published runs

| | published | here |
|---|---|---|
| System | Debian container | Windows, the app's own command limits |
| Tasks | 274 | the 254 the check admits |
| Semantic judge | run (at most a task's `max_fallback_weight`, about 0.08) | not run |
| Time | the task's timeout, one session | chat turns; "Continue." after a turn that ended at the loop's ceiling |

## Records

| Where | What |
|---|---|
| `<work>/valid.json` | Every task, and why it is left out when it is |
| `<work>/<task>/result.json` | Score, cases, turns, questions asked, the grader's whole result |
| `<work>/model-<port>.jsonl` | One row per model call |
| `--out` | Summary: mean score, tasks at 0.8 or more (the benchmark's pass), full credit, per-task rows |
