"""dialogs.py 规则单测（纯函数，不要浏览器）：python3 browser/test_dialogs.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import dialogs as D  # noqa: E402

# alert / 离开提示：只能确定，永远记下
for kind in ("alert", "beforeunload"):
    for armed in (None, "dismiss", "accept"):
        d = D.decide(kind, "提交成功", armed=armed)
        assert d.accept and d.note == {"kind": kind, "message": "提交成功", "accepted": True, "auto": True}, d
# confirm：没说好 → 取消（auto），说好 accept → 确定，dismiss → 取消（不是 auto）
d = D.decide("confirm", "确定要取消订单吗？")
assert not d.accept and d.note["auto"] and d.text is None
d = D.decide("confirm", "确定要取消订单吗？", armed="accept")
assert d.accept and not d.note["auto"]
d = D.decide("confirm", "确定？", armed="dismiss")
assert not d.accept and not d.note["auto"]
# prompt：accept 用模型的字，没给用默认值；空字不进 note；没说好 → 取消
d = D.decide("prompt", "备注", default="无", armed="accept", text="放门口")
assert d.accept and d.text == "放门口" and d.note["text"] == "放门口"
d = D.decide("prompt", "备注", default="无", armed="accept")
assert d.text == "无"
d = D.decide("prompt", "备注", armed="accept")
assert d.accept and d.text == "" and "text" not in d.note
d = D.decide("prompt", "备注", default="无", text="x")
assert not d.accept and d.text is None
# 连环弹框：第 DIALOGS_MAX 个起 confirm 一律取消，alert 仍确定
d = D.decide("confirm", "再确认一次", armed="accept", seen=D.DIALOGS_MAX)
assert not d.accept and d.note.get("flood") and d.note["auto"]
assert D.decide("alert", "hi", seen=99).accept
# 话：空白归一 + 截断；未知类型按 alert
d = D.decide("weird", "a\n\n  b" + "x" * 500)
assert d.note["kind"] == "alert" and d.note["message"].startswith("a b") and len(d.note["message"]) == D.MESSAGE_MAX
# arm
assert D.arm("Accept ") == "accept" and D.arm("dismiss") == "dismiss" and D.arm("yes") is None and D.arm(None) is None
print("test_dialogs OK")
