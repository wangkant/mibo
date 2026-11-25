---
name: photos-by-date
description: Sort photos and videos into year and month folders by the date they were taken. Use when they ask to arrange photos by month, year or the dates of a trip ("把照片按月份整理", "照片按日期分类"); a mixed folder sorted by kind is tidy-downloads, space problems are free-up-disk-space, renaming is rename-files.
license: Apache-2.0
metadata:
  mibo-title-zh: 照片归档
  mibo-description-zh: 将照片和视频按年份、月份归入子文件夹，事先说明分组方案和日期来源，确认后再移动；不删除任何文件。
  mibo-title-en: Photo filing
  mibo-description-en: Sorts photos and videos into year and month folders by the date taken, explaining the grouping and the source of each date first and moving files only after approval; nothing is deleted.
---

# Sorting photos by date

Never delete. Nothing is moved before they have seen the plan.

1. Settle the folder (Pictures when they named none, or the phone-import or camera folder they name), whether its
   subfolders are included, and the grouping: `2025\2025-03` by month unless they ask for year only.
2. list_files sort date, recursive only when subfolders are included, once per kind with a pattern (*.jpg,
   *.jpeg, *.png, *.heic, *.webp, *.gif, *.mp4, *.mov). A listing shows at most 300 rows; for a larger set list
   by month with a pattern such as `IMG_202503*`, or count first with use_computer
   `Get-ChildItem -File -Recurse | Group-Object { $_.LastWriteTime.ToString('yyyy-MM') } | Select-Object Name, Count`.
3. Take each file's date from its name when it carries one (IMG_20250312_..., 微信图片_20250312...,
   Screenshot_2025-03-12, VID_20250312), else from the modified date. Tell them in one line that the modified date
   can be the copy date, not the shooting date.
4. Propose before moving: the folders with how many files go to each, and the files dated only by the modified
   date. Ask whether to go ahead unless they already said to.
5. Move with move_files, a `to` ending in `\` (`2025\2025-03\`) puts the file inside the month folder and makes
   it when missing; up to about 200 moves per call. One name already in the month folder stops that whole call
   with nothing moved: leave that file out and list it. For a large set tick off the batches with update_plan.
   Leave files changed in the last hour, files already in a year folder, and anything not a photo or video.
6. List likely duplicates (the same name with " (1)", or the same size and date) and let them decide.
7. End with the counts per folder, taken from the results. 撤销这次的改动 under the reply puts them back.
