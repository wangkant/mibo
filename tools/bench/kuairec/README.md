# KuaiRec replay of the feed's learning and ranking

KuaiRec's small matrix (Kuaishou, 2020) records the reaction of 1,411 people to almost every one of
3,327 short videos, so whatever the feed would bring a person, their real reaction to it is known.
These scripts play sampled people forward through the app's own ranking (`recommend.candidates`
over `feed.ranked` and the taste model in `taste.py`), one card at a time, and compare it with
picking at random, the most watched, a bandit over categories and the best possible.

Dataset: KuaiRec 2.0, Gao et al., CIKM 2022, https://kuairec.com, zip from
https://zenodo.org/records/18164998 (KuaiRec.zip, 431,964,858 bytes, md5 261550d472c48eff4990fb13c0e5bcf7).
Licence: the zip's LICENSE and the GitHub repo say CC BY-SA 4.0 (the Zenodo record says CC BY 4.0):
use, share and adapt with attribution; anything adapted from it that is shared goes out under the
same licence. Keep the data and anything derived from it out of this repository.

## Commands

From the repo root, with the venv that has no extra packages (standard library only):

```
PY=../../.venv-web-platforms/Scripts/python.exe
D=../ref/datasets/kuairec

# 1. once: download (432 MB) and check
mkdir -p $D/raw && curl -L -o $D/raw/KuaiRec.zip https://zenodo.org/records/18164998/files/KuaiRec.zip
md5sum $D/raw/KuaiRec.zip      # 261550d472c48eff4990fb13c0e5bcf7

# 2. the library and the sample (about a minute; reads the zip, extracts nothing)
$PY -I tools/bench/kuairec/prepare.py --zip $D/raw/KuaiRec.zip --out $D/prepared --people 300 --seed 7

# 3. the replay: the app and the four baselines on all 300 people, then the variants on 50
#    (2 to 3 minutes of one core per person and app arm at 300 cards; resumes if stopped;
#    app_author is there too but was not run: 965 of the 1,195 uploaders have one video)
$PY -I tools/bench/kuairec/replay.py --data $D/prepared --out $D/results --arms random,popular,bandit,oracle,app --workers 20
$PY -I tools/bench/kuairec/replay.py --data $D/prepared --out $D/results --people 50 --workers 20 \
    --arms app_pop,app_greedy,app_explore,app_site,app_topics,app_tags,app_open05

# 4. the numbers
$PY -I tools/bench/kuairec/report.py --data $D/prepared --out $D/results --json
```

No model is called and no port is opened. The runtimes live under `<out>/work` while they run and
are removed after each person.

## How a video becomes a library item

| app field | filled from | note |
|---|---|---|
| title | caption, else cover text, else hashtags | 4% of library videos have no caption |
| excerpt (description) | cover text, hashtags, `分类：一级/二级/三级` | so the category reaches the topic matcher and the variety rule the way a card's words do |
| source (origin feature) | `ks-<first-level category>`, like `bili-rank-<partition>` | `app_author`: the uploader; `app_site`: none |
| site | 快手 | |
| kind | video | Kuaishou's player is not on the app's list; a listed player address stands in, else every video would be a text card |
| length | video duration | 99.9% are under 240 s, so `len:short` for nearly all; `secs` (log seconds) tells them apart |
| language | the caption's script: zh, read | no signal |
| seen_at / fresh | all found at the start | equal for every item at any moment: no signal |
| judged, fits, love | none (the character's own judgement needs a model) | `app_pop` puts the crowd's popularity quartile in `love` |
| tags | none | `app_tags`: second and third category levels, with the "tags" family on |
| topics | none (a new person) | `app_topics`: the three categories the person watches through most among the other half of the videos |

The library is the half of the 3,327 videos whose md5(video_id) is even (1,644); each person's pool
is the library videos they have a reaction to (about 1,620). The other half only says which
categories a person would name. Popularity is the mean watch ratio of each video over the 1,111
people outside the sample.

## How a reaction becomes the card's events

Watch ratio (wr) is seconds played over the video's length; seconds played is the dataset's.

| reaction | card events | taste label |
|---|---|---|
| wr ≥ 1 (watched through) | seen, end open, open, play (seconds played) | play (1, 2.0): half the video's own length or 60 s |
| played under 3 s | seen, end quick, skip | closed at once (0, 1.5) |
| wr < 0.5 | seen, end close, skip | skip (0, 1.0) |
| 0.5 ≤ wr < 1 | seen, end timeout | quiet no (0, 0.3) |

`app_open05` opens from wr 0.5 instead. Cards come 12 minutes apart; the model is refit after each
card's events, as the app's minute timer would. The model's draws are seeded by the clock, so each
person starts at their own minute of the first day. All items are found at once, so videos the
model scores the same (every video of one source, here) keep the ranking's last tie-break, the id:
one fixed order inside each category, the same for everyone.

`replay.py` keeps the answers of a few reads that never change during a replay (the library file,
`life.clean_card`, `taste.Reader`, `taste.Priors`, `feed.load_topics`) so it runs sooner; the cards and the fitted model come out identical with and without them.

## What it measures

Over the first 10, 30, 100 and 300 cards per arm: the mean watch ratio of what was shown, the share
watched through, where each shown video's watch ratio stands among that person's own for videos of
about that length ("stand": 0.5 for random picks; a short video is watched through more easily, so
this is the measure that bringing short videos cannot raise), distinct first-level categories, the gap to the best possible and the share of the
random-to-best distance covered, when the app's running mean passes each baseline, the same for
people with narrow tastes and people who like little, the variants against the app on the same
people, and diagnostics (events, the explore slot, what follows a quick close, how much signal
category, uploader, popularity and length carry in the data, and how the learned source weights
match each person's true category rates).

People are Kuaishou users of 2020 watching an autoplaying feed, not Mibo's people deciding whether to
open a card; the map from watch ratio to card events is an assumption, and the numbers say how the
model learns from this kind of behaviour, not what Mibo's people would do.
