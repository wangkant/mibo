"""The asking rule (cardwait.py): a costly step, one Mibo's own undo cannot give back, is asked every time and on its
own, and no earlier yes reaches it; what undo restores is not costly. Costly is money paid or spent, a deletion
nothing restores, the account itself, handing over access or private details, a binding submission, and this
computer past what undo covers. Each bullet is held at the gates that sort acts: a page's controls (web/gate.py),
another program's window (desk/gate.py) and commands (review.py)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from mibo import acting, cardwait, review
from mibo.desk import gate as desk
from mibo.shell import files
from mibo.web import gate

SHOP = "https://shop.example.com/item/1"


def test_a_costly_step_is_asked_on_its_own_and_no_yes_reaches_it():
    for kind in cardwait.COSTLY:
        assert cardwait.costly(kind) and cardwait.risk_of(kind) == kind
        assert not any(cardwait.reaches(answered, kind) for answered in (kind, "act", "recycle", "open"))
    # Widening the character's own permissions is asked alone too.
    assert not cardwait.reaches("widen", "widen") and not cardwait.reaches("act", "widen")
    # An ordinary step and a restorable delete are carried by a yes of their own kind.
    assert cardwait.reaches("act", "act") and cardwait.reaches("recycle", "recycle") and cardwait.reaches("recycle", "act")
    assert not cardwait.reaches("act", "recycle") and not cardwait.costly("recycle")


def test_a_yes_to_a_costly_step_is_never_kept_for_the_turn():
    everyone = cardwait.Asking()
    for kind in cardwait.COSTLY:
        everyone.yes_given(("main", "t1"), kind)
        assert not everyone.carried(("main", "t1"), kind)


# (a page control's name, the kind its gate gives): money spent, the account itself, a binding submission, and the
# ordinary acts beside them that undo or the person can take back.
PAGE = [
    ("立即支付", "order"), ("开通会员", "order"), ("自动续费", "order"), ("Subscribe", "order"),
    ("使用积分", "order"), ("Redeem points", "order"),
    ("加入购物车", ""), ("Add to cart", ""), ("比价", ""), ("签到", ""),
    ("修改密码", "account"), ("Change password", "account"), ("解绑手机", "account"), ("退出登录", "account"),
    ("修改头像", ""), ("Update profile", ""), ("Edit nickname", ""),
    ("电子签名", "bind"), ("提交申请", "bind"), ("Sign contract", "bind"), ("File tax return", "bind"),
    ("Sign in", ""), ("Sign up", ""),
    ("永久删除", "delete"), ("Delete post", "delete"),
]


@pytest.mark.parametrize("name, kind", PAGE)
def test_a_page_control_is_costly_by_what_undo_cannot_give_back(name, kind):
    assert gate.classify("click", name, "button", {}, SHOP)[0] == kind
    if kind:
        assert acting.decide("auto", kind, "shop.example.com") == "ask"


def test_typing_an_id_number_an_address_or_a_bank_account_hands_over_private_details():
    for typed in ("身份证号：110101199003071234", "Home address: 1 Main St", "银行卡号: 6222020200112233445",
                  "SSN: 123-45-6789", "110101199003071234"):
        assert gate.hands_over(typed), typed
    for typed in ("备注：明天见", "Note: bring snacks", "订单号 20261122"):
        assert not gate.hands_over(typed), typed


def control(role: str, name: str, *, parent=None, cls: str = "") -> SimpleNamespace:
    """A stand-in for one control of another program's window, as desk/uia.py reads it."""
    return SimpleNamespace(role=role, name=name, parent=parent, cls=cls, patterns=[], top=1, auto="", hwnd=0)


def test_in_file_explorer_the_recycle_bin_is_not_costly_and_past_it_is():
    item = control("listitem", "报告.docx", parent=control("list", "项目视图", cls="UIItemsView"))
    window = control("window", "下载")

    def press(name: str) -> str:
        return desk.press(control("button", name, parent=window), "下载 - 文件资源管理器", True, "", None, "invoke",
                          "explorer.exe")[0]

    sorted_as = {"Delete": desk.key("Delete", item, "下载", True, "")[0],
                 "shift+delete": desk.key("shift+delete", item, "下载", True, "")[0],
                 "删除": press("删除"), "永久删除": press("永久删除"), "清空回收站": press("清空回收站")}
    assert sorted_as == {"Delete": "recycle", "shift+delete": "delete", "删除": "recycle", "永久删除": "delete",
                         "清空回收站": "delete"}
    assert acting.decide("auto", "recycle", "", "programs") == "review"
    assert acting.decide("auto", "delete", "", "programs") == "ask"


@pytest.mark.skipif(sys.platform != "win32", reason="the Recycle Bin is Windows'")
def test_a_delete_the_recycle_bin_cannot_hold_is_costly(tmp_path):
    # Windows deletes for good, without a word, what its bin cannot hold.
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert files.bin_keeps([str(tmp_path / "a.txt")], 1)
    assert not files.bin_keeps([str(tmp_path / "a.txt")], 10 ** 15)


def test_a_command_is_costly_by_what_it_does_beyond_the_recycle_bin():
    # Remove-Item and del go to the Recycle Bin; a push, an install or a delete past the bin reach past undo.
    assert not review.costly_command("Remove-Item notes.txt") and not review.costly_command("del a.txt")
    for command in ("git push", "pip install requests", "Remove-Item notes.txt; git push"):
        assert review.costly_command(command), command
