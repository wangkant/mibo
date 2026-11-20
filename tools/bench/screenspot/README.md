# ScreenSpot pointing benchmark

Can a cheap picture-reading model, of the kind a Mibo user brings, point at the right thing on a screenshot?
Measured on the public grounding sets, not on anything this repo wrote. It measures only: nothing in the
product is changed or called.

- **ScreenSpot-v2**: [OS-Copilot/ScreenSpot-v2](https://huggingface.co/datasets/OS-Copilot/ScreenSpot-v2)
  (the re-annotated ScreenSpot from the OS-Atlas paper, arXiv 2410.23218), licence **Apache-2.0** (dataset card):
  use, copy, modify and redistribute, also commercially, keeping the licence and notices. Only the desktop (334)
  and web (437) parts are used; mobile is left out.
- **ScreenSpot-Pro**: [likaixin/ScreenSpot-Pro](https://huggingface.co/datasets/likaixin/ScreenSpot-Pro)
  (arXiv 2504.07981), licence **MIT**. A 48-item sample (one per application and text/icon pair) shows the hard end:
  professional software on 2K-5K screens.

The data stays out of the repo. Both sets are third-party material, read as data only.

## Commands

Python with `httpx` and `Pillow` (the measuring venv `.venv-web-platforms` has both). `DATA` is a folder
outside the repo; `OUT` is a scratch folder that holds a `.env` with `LLM_API_KEY` and `LLM_BASE_URL`
(OpenRouter). The scripts read the key and never print it.

```
python fetch.py DATA                 # v2 desktop+web images (~430 MB, read out of the 1.3 GB zip by range requests) and the Pro sample (~100 MB)
python bench.py DATA OUT spend       # what the key has spent so far (numbers only)
M=deepseek/deepseek-v4.1-flash,qwen/qwen3.7-flash,z-ai/glm-5.3-flash,openai/gpt-6-luna
python bench.py DATA OUT probe $M --cap 0.06   # 20 items asked in pixels and in 0-1000; keeps the better way per model (OUT/ways.json)
python bench.py DATA OUT main  $M --cap 0.28   # 150 desktop + 150 web, same for every model, text/icon balanced
python bench.py DATA OUT crop  $M --cap 0.05   # second look on a crop round the first answer
python bench.py DATA OUT pro   qwen/qwen3.7-flash,openai/gpt-6-luna --cap 0.04
python score.py DATA OUT             # OUT/report.md and OUT/report.json
```

Runs resume: a look already in `OUT/answers.jsonl` is not asked again, so rerunning after a stop at the cap only asks
what is missing. The sample is fixed by seed (`random.Random(2026)`), so every model and every rerun gets the same items.

How it asks and scores: one screenshot per call, full resolution, temperature 0, reasoning off where the model
allows it (`CFG` in bench.py, the same settings the in-house pointing study used). A point is right when it lies
inside the true box, which is how ScreenSpot is scored. The crop pass cuts 30% of the screen each way round the first
point, enlarges it to 1280 px wide, asks the same question and maps the answer back. It is asked on every first-look
miss (to count what it rescues) and on a fixed check subset (every 5th item, 60 items) to count what it breaks.

## Results, 2026-11-19 (spent $0.39 of OpenRouter credit)

First look, % right (n=300 per model; 95% intervals about ±3-5 points):

| | deepseek-v4.1-flash | qwen3.7-flash | glm-5.3-flash | gpt-6-luna |
|---|---|---|---|---|
| way kept after the probe | 0-1000 | 0-1000 | pixels | pixels |
| all (desktop + web) | 81.0 | 93.7 | 78.7 | **95.3** |
| desktop | 82.7 | 94.7 | 80.7 | 96.7 |
| web | 79.3 | 92.7 | 76.7 | 94.0 |
| text / icon | 79.3 / 82.7 | 94.0 / 93.3 | 81.3 / 76.0 | 95.3 / 95.3 |
| targets < 0.1% of the screen (n=20) | 90 | 95 | **30** | 100 |
| after the crop pass (estimated, all 300) | 88.6 | 94.7 | 92.7 | 95.7 |
| ScreenSpot-Pro sample (n=48) | - | 47.9 | - | 66.7 |
| $ per 1000 looks (v2 / Pro) | 0.17 | 0.06 / 0.08 | 0.29 | 0.37 / 0.82 |

The full tables (by text and icon within desktop and web, by target size, the crop pass, cost per pass) are in
`OUT/report.md`.

Published numbers on the same set (whole ScreenSpot-v2 including mobile, so only roughly comparable):
GPT-4o 20.1, OS-Atlas-7B 84.1, UI-TARS-7B 91.6 (UI-TARS paper, arXiv 2501.12326, table 6); Qwen2.5-VL-72B 90.7,
GTA1-72B 94.8, UI-TARS-1.5 94.2, Seed1.5-VL 95.2, UI-Venus-Ground-72B 95.3 (UI-Venus report, arXiv 2508.10833).
ScreenSpot-Pro: GPT-4o 0.8, Claude Computer Use 17.1, UI-TARS-72B 38.1, UI-TARS-1.5 61.6, UI-Venus-72B 61.9.

What this does not say: ScreenSpot's screenshots and instructions were written by annotators for other people's
apps and sites; they are not Mibo users' screens or the way Mibo users ask. The instruction names one visible thing
and the thing is always on the screen; in Mibo the model must also decide what to click and notice when it is absent.
