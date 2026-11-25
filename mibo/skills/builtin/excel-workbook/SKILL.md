---
name: excel-workbook
description: Put figures, lists or records (a budget, a schedule, a sign-up list) into an Excel workbook (.xlsx), one table per sheet with live formulas, or change cells of one they have. Use when they ask for a spreadsheet or a table file ("整理成表格", "做个 Excel", "导出成 xlsx").
license: Apache-2.0
metadata:
  mibo-title-zh: Excel 表格制作
  mibo-description-zh: 将数据、清单或记录整理为 Excel 工作簿（.xlsx），每个工作表一张表，含表头、规范数值与自动计算的公式；也可修改已有表格中的单元格。
  mibo-title-en: Excel workbooks
  mibo-description-en: Puts figures, lists or records into an Excel workbook (.xlsx), one table per sheet with headers, clean values and live formulas, or changes cells of an existing one.
  mibo-required: "true"
---

# Making an Excel workbook

The workbook is made with write_file on a path ending in .xlsx; its content is Markdown tables, and the app turns
them into the finished file. Never open Excel to type it.

1. Settle what the table is for and what one row is (one expense, one person, one day). Save it in the folder
   they named, else in their Documents, under a name in their language: `2026年11月家庭支出.xlsx`.
2. One sheet per table. A `# 收支` line names the sheet that the table under it fills (at most 31 characters,
   none of / \ ? * [ ] :). The first row is the header; then one record per row, every row with the same columns.
3. Values as Excel should hold them:
   - Numbers written plainly, without units in the cell; the unit goes in the header (`金额（元）`).
   - Dates as `2026-11-22`, percentages as `12.5%`.
   - Numbers that are names keep their form: an ID, a phone number or a code with a leading zero is written as
     it is.
4. Totals, averages and anything worked out from other cells are formulas, never sums you did yourself:
   `=SUM(C2:C31)`, `=AVERAGE(D2:D13)`, `=C2*D2`. Cells are named as Excel names them: column letter, row
   number, the header being row 1. Check that each formula points at the rows the data is really in.
5. After write_file, tell them in a sentence or two what each sheet holds and where the file is. Offer to show it
   (open with show true) rather than opening it unasked.

## Changing a workbook they have

- read_file it first: each cell comes as `B3=value`.
- edit_file replaces text within one cell. A whole cell's value replaced by a number, a date or a formula is held
  as that.
- To add rows or restructure it, write a new file under a new name, unless they asked for theirs to be replaced.

Charts, pivot tables, macros and colour rules are not made this way: say so when they ask for one, and suggest
adding it in Excel.
