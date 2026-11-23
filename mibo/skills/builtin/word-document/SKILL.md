---
name: word-document
description: Write a Word document someone will hand in, send or print - a report, a summary, a plan, a notice, a letter - as a finished .docx file, or change one they have. Use when they ask for a document or for something made into Word ("做成 Word", "写一份报告"); the content of minutes is meeting-minutes.
license: Apache-2.0
metadata:
  mibo-title-zh: 撰写 Word 文档
  mibo-description-zh: 将报告、总结、方案、通知、会议纪要等内容生成排版规范的 Word 文档（.docx），可直接提交、发送或打印；也可修改已有文档中的文字并保留原有格式。
---

# Writing a Word document

The document is made with write_file on a path ending in .docx; its content is Markdown, and the app turns it
into the finished file (A4, Word's own heading and list styles, page numbers). Never open Word to type it.

1. Settle what it is for, who reads it and how long it should be. Use what they gave you and what you remember;
   ask one question only when the document turns on the answer. Save it in the folder they named, else in their
   Documents, under a name in their language that says what it is: `2026年第三季度工作总结.docx`.
2. Lay it out:
   - One `#` line at the top is the title. `##` lines are the sections, `###` the parts within them. Chinese
     section numbers go in the heading's text (`## 一、总体情况`).
   - Each paragraph on its own line. Keep paragraphs to one point each.
   - `-` items for things of the same kind, `1.` items for steps or a ranking; indent by two spaces to nest.
   - A table whenever figures or options are compared: a header row, then one row each, the unit in the header
     (`金额（万元）`), numbers written plainly so they line up.
   - `>` for a note or a quotation, ``` for code or text to be copied exactly, **bold** for the few words a
     reader must not miss, [words](https://...) for a link.
   - A line `\newpage` only where a new page is wanted, such as after a cover.
3. Write it whole: every section with its real content, the facts and numbers from them or from sources you read,
   none made up. A field only they can fill is marked plainly, as `【待填写：联系电话】`. Keep to the length asked;
   when it runs long, cut words rather than parts.
4. After write_file, tell them in a sentence or two what the document holds and where it is, by its name. Offer to
   show it (open with show true) rather than opening it unasked.

## Changing a document they have

- read_file it first. edit_file replaces text within one paragraph or one table cell, exactly as read_file shows
  it (no line numbers); the paragraph keeps its style and the words around the change keep their look.
- To add a paragraph after one, give that paragraph as old_string and the same paragraph, a new line and the new
  one as new_string: the new one takes the same style.
- A table row is shown as `| a | b |`; change one cell at a time.
- To rewrite most of it, write a new file under a new name, unless they asked for theirs to be replaced.

Pictures, footnotes, comments, tracked changes and a table of contents are not made this way: say so when they
ask for one, and suggest adding it in Word.
