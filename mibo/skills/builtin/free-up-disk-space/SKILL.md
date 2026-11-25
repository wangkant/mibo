---
name: free-up-disk-space
description: Find the largest folders and files in the person's own folders and free space only by what they pick. Use when they say a drive is full, ask what takes up space, or want space back ("C 盘满了", "清理一下 C 盘", "什么占了这么多空间"); sorting one folder into subfolders is tidy-downloads.
license: Apache-2.0
metadata:
  mibo-title-zh: 磁盘清理
  mibo-description-zh: 找出个人文件夹中占用空间最大的文件夹和文件，列出可清理的候选项及其大小；仅删除指定项目，不清理系统文件，不卸载程序。
  mibo-title-en: Disk cleanup
  mibo-description-en: Finds the largest folders and files among the person's own folders and lists candidates to clear with their sizes; only the items chosen are deleted, and system files and programs are left alone.
---

# Finding what fills the disk

Measure first, change nothing until they pick. Windows, Program Files and the app's own folder are never touched.

1. Free space per drive with use_computer:
   `Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}}, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}`
   and say which drive is short.
2. list_files with folder desktop, documents, downloads, pictures, videos and music in turn, sort size. Each
   subfolder comes with its total; the first line counts only the files directly inside, so a folder's size is
   that plus its subfolders. Go one level into the largest two or three. Then list_files recursive, sort size,
   on the largest folders for the 15 largest files. Any other folder is asked for in the chat before it is read.
3. Add up what you measured and set it against the drive's used space. The rest is programs, Windows and app
   data, which cannot be read here (a whole drive or a system folder is never granted): say so in one line.
4. Report in a short table: where the space is (folder, GB), then the likely candidates with size and date: old
   installers (.exe, .msi) in Downloads, copies with " (1)", large videos, archives already unpacked. Never call
   anything junk on a guess.
5. Wait for them to pick. Then delete_files only the items they named; these go to the Recycle Bin and run
   without a further question. A pick larger than the Recycle Bin holds is deleted for good, so the app asks in
   the chat first; say that before a very large pick.
6. Say plainly that the Recycle Bin still holds the space until it is emptied. Emptying it is a deletion nothing
   restores: ask in the chat every time, or suggest they empty it themselves.
7. End with the space freed, taken from a second Get-PSDrive, not estimated.

Never clear system caches or uninstall programs; point them to Windows' Storage settings or 磁盘清理 for those.
