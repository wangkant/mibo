---
name: tidy-downloads
description: Tidy a cluttered folder such as Downloads or the Desktop - sort its files into subfolders by kind and point out duplicates and large old files, leaving every deletion to the person. Use when they ask to tidy or sort a folder; lack of space is free-up-disk-space, photos by date is photos-by-date.
license: Apache-2.0
metadata:
  mibo-title-zh: 整理下载文件夹
  mibo-description-zh: 将下载文件夹、桌面等杂乱的文件夹按类型归入子文件夹，并列出重复文件和占用空间较大的旧文件；是否删除由你决定。
---

# Tidying a folder

Work with list_files and move_files. The folder is the one they named; Downloads when they said 下载 or
named none.

1. Look first and change nothing. list_files on the folder shows what kinds of files are there; sorted by size
   it shows the ten largest, with their dates.
2. Propose a plan in your reply, in a few lines: the subfolders (named in their language), how many files go to
   each, and the large old files they may no longer need. Ask whether to go ahead. Move nothing in this turn
   unless they already said to just do it.
3. When they agree, move the files with move_files, many moves in one call: a `to` that ends in a backslash
   puts the file inside that folder, made if it is missing, and nothing existing is replaced.
   Leave files still downloading (.crdownload, .part, .tmp) and files changed in the last hour where they are.
4. Never delete. List duplicates (the same name with " (1)", or the same size and name) and large old installers,
   and let them decide. If they ask to delete, that is delete_files: it goes to the Recycle Bin and, once they have
   asked for it, runs without a question.
5. End with what moved where, in two or three lines, taken from the tool results rather than from the plan.

Kinds: images jpg jpeg png gif webp heic bmp svg; documents pdf doc docx xls xlsx ppt pptx txt md csv;
installers exe msi; archives zip rar 7z gz; video mp4 mov mkv avi webm; audio mp3 wav flac m4a aac.
