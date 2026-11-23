"""The person's words for the steps operate.Hands takes: each step as the column beside the page shows it before
it happens, and why a step did not work."""
from __future__ import annotations

import re

# Why a step did not work, as the column beside the page tells the person; the first pattern found in the line.
WHY = [("covered", r"covered by another element"), ("hidden", r"Target hidden|outside viewport"),
       ("disabled", r"Target disabled"), ("other", r" is not \".*: nothing was done"),
       ("picker", r"opens a picker|does not take"),
       ("changed", r"^\[changed\]"), ("gone", r"detached|not on the (latest )?page|drawn anew"), ("back", r"no page before")]
WHY_SAID = {
    "zh": {"covered": "被其他内容遮挡，未点击。", "hidden": "当前不可见，未点击。", "disabled": "当前不可用，未点击。",
           "other": "与网页上的名称不符，未执行。", "picker": "该字段未接受输入的内容。",
           "changed": "网页内容在确认后发生变化，未执行。", "gone": "已不在网页上，未执行。", "back": "没有可返回的上一页。"},
    "en": {"covered": "Something else covers this control; it was not clicked.",
           "hidden": "This control is not in view now; it was not clicked.", "disabled": "This control is turned off now.",
           "other": "The control named is not the one on the page; nothing was done.",
           "picker": "The field did not take what was typed.",
           "changed": "The page changed after you confirmed; nothing was done.", "gone": "This control is no longer on the page.",
           "back": "There is no page to go back to."},
}

# What a person reads in the step log for each action, before it happens.
SAID = {
    "zh": {"click": "点击「{name}」", "type": "在「{name}」输入「{text}」", "press": "按 {key}", "hover": "将指针移到「{name}」",
           "down": "向下滚动", "up": "向上滚动", "in": "（在「{name}」中）", "until": "，直到出现「{text}」",
           "navigate": "打开 {host}", "back": "返回上一页", "wait": "等待页面加载", "find": "在页面上查找「{text}」",
           "box": "输入框", "point": "画面上的某个位置", "times": "（{n} 次）", "held": "网页将发送刚才输入的内容",
           "chose": "网页将保存刚才的选择", "leave": "网页提示：离开此网页后，未保存的内容可能会丢失。",
           "double": "双击「{name}」", "right": "右键单击「{name}」", "drag": "将「{name}」拖到「{to}」",
           "shows": "等待「{text}」出现", "gone": "等待「{text}」消失", "read": "读取网页内容：{text}",
           "more": "加载更多网页内容：{text}", "select": "选中「{name}」中的文字{text}"},
    "en": {"click": "Click “{name}”", "type": "Type “{text}” into “{name}”", "press": "Press {key}",
           "hover": "Point at “{name}”", "down": "Scroll down", "up": "Scroll up", "in": " in “{name}”",
           "until": " until “{text}” shows", "navigate": "Open {host}", "back": "Go back",
           "wait": "Wait for the page", "find": "Look for “{text}” on the page", "box": "the box",
           "point": "a point on the picture", "times": " ({n} times)",
           "held": "The page sending what was typed", "chose": "The page saving the choice just made",
           "leave": "The page warns that what is not saved may be lost if you leave it.",
           "double": "Double-click “{name}”", "right": "Right-click “{name}”", "drag": "Drag “{name}” onto “{to}”",
           "shows": "Wait for “{text}” to show", "gone": "Wait for “{text}” to go",
           "read": "Read the page: {text}", "more": "Load more of the page: {text}",
           "select": "Select the text{text} in “{name}”"},
}


def reason(line: str, lang: str) -> str:
    """Why a step failed, in the person's words; "" where the line gives no reason they could use."""
    return next((WHY_SAID[lang][key] for key, pattern in WHY if re.search(pattern, line)), "")
