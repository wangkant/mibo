---
name: powerpoint-deck
description: Make a PowerPoint deck (.pptx) for a talk, a report, a class or a pitch, one point per slide with speaker notes, or change the text of one they have. Use when they ask for slides or a presentation ("做个 PPT", "做成幻灯片", "演示文稿").
license: Apache-2.0
metadata:
  mibo-title-zh: 制作 PPT 演示文稿
  mibo-description-zh: 为汇报、讲课或路演生成 PowerPoint 演示文稿（.pptx）：封面、每页一个要点、需要时附表格与演讲者备注；也可修改已有演示文稿中的文字。
---

# Making a PowerPoint deck

The deck is made with write_file on a path ending in .pptx; its content is Markdown, and the app turns it into the
finished file. Never open PowerPoint to type it.

1. Settle who it is for, how long the talk is and what the audience should take away. Roughly one slide a minute;
   8 to 15 slides for a ten-minute talk. Save it in the folder they named, else in their Documents, under a name in
   their language: `新产品发布会.pptx`.
2. Each `#` line starts a slide and is its title. Write titles that say the point (`收入增长 24%，超出目标`),
   not just the topic (`收入情况`).
3. The first slide is the cover: its `#` title and a line or two under it (subtitle, who, date), no list. The last
   slide sums up or says what comes next.
4. Under a title:
   - `-` items, three to six of them, each a short phrase (about 20 Chinese characters at most); indent by two
     spaces for a point under a point. Never a paragraph on a slide.
   - Or a Markdown table when figures are compared: a header row and a few rows, no more than six or seven.
   - `>` lines are the speaker's notes: what to say on that slide, in full sentences. Put the detail there rather
     than on the slide.
5. After write_file, tell them in a sentence or two how many slides it has and where the file is. Offer to show it
   (open with show true) rather than opening it unasked.

## Changing a deck they have

- read_file it first: each slide comes under a `[slide n]` line.
- edit_file replaces text within one paragraph of a slide or one table cell; the slide keeps its design.
- To add or reorder slides, write a new file under a new name, unless they asked for theirs to be replaced.

Pictures, charts, animations and a designed theme are not made this way: say so when they ask for one, and
suggest adding it in PowerPoint.
