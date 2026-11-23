---
name: rename-files
description: Rename a batch of files by one rule - number them, add a date or prefix, replace a word, unify case. Use when they ask to rename many files ("批量改名", "把这些文件按日期重命名", "rename these files"); one file is just move_files, sorting into folders is tidy-downloads or photos-by-date.
license: Apache-2.0
metadata:
  mibo-title-zh: 批量重命名文件
  mibo-description-zh: 按统一规则批量重命名文件（编号、添加日期或前缀、替换字词、统一大小写），先列出新旧名称对照，经你确认后执行，不覆盖已有文件。
---

# Renaming a batch of files

Never replace a file that is already there; a clash is reported, not forced. Names change, contents never.

1. Settle the folder (the one they named, else ask), which files (a pattern such as `*.jpg`) and the rule. Call
   list_files with that pattern and the sort the numbering follows: name, or date, which lists newest first (count from the bottom for oldest
   first). A date in
   the new name is the modified date the listing gives, unless the old name already carries one.
2. Work out every new name yourself and show it in the reply: the first three and the last two as `旧名 → 新名`,
   the total count, and any clash (two files would get one name, or the name exists). Keep each extension; pad
   numbers to one width (001, 002); avoid the characters Windows forbids (\ / : * ? " < > |).
3. Ask once whether to go ahead, unless they already said to just do it.
4. Rename with move_files, each `to` the new name in the same folder, all moves in one call or in calls of about 200. One clash
   stops the whole call with nothing renamed, and so does a new name that another file in the set still has
   (shifting 2.jpg to 3.jpg while 3.jpg is there): rename those to temporary names first, then to the final ones.
5. Report how many were renamed from the tool's result. Mention that 撤销这次的改动 under the reply takes the
   renaming back.

Many hundreds of files may go in one use_computer command instead, without -Force, for example
`Get-ChildItem -Filter *.jpg | Rename-Item -NewName { 'trip_' + $_.Name }`. Its new names are made as it runs, so
撤销这次的改动 cannot take them back: say so before running it, and prefer move_files when they may want to undo.
Report the errors in its output as the files left unrenamed.
