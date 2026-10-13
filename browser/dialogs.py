"""网页原生弹框（alert / confirm / prompt / 离开页面提示）怎么处理（v2.56）——唯一规则，纯逻辑，不碰 Chromium。

为什么要有：Playwright 没人接 dialog 事件时会自动“取消”。于是“确定要取消订单吗？”“确定删除这个地址吗？”
被悄悄点了取消，模型以为点成了；alert("手机号格式不对") / alert("提交成功") 的话也直接丢了，模型不知道发生了什么。
三家参考（Codex / Gemini CLI / deepseek-harness）都不托管浏览器，无代码可搬；语义参照 Playwright MCP
browser_handle_dialog（模型决定确定还是取消）——但我们的服务是一次请求一个动作，弹框不能挂着等下一次请求
（挂着的弹框会卡住页面里的所有脚本，快照都拍不了），所以改成“动作前先说好，弹出来当场按说好的办”。

规则（decide，每弹一个框调一次）：
1. alert：只能点确定 → 确定，把话记下来告诉模型。
2. beforeunload（离开页面提示）：模型本来就要离开 → 确定离开，记下。
3. confirm：这次动作带了 dialog="accept" → 确定；带了 "dismiss" 或什么都没带 → 取消。
   没说好就默认取消：不替用户确认没想过的事（删除、退订、付款），告诉模型页面问了什么，要确认就带 confirm 再做一次。
4. prompt：带了 accept → 确定并填 text（没给 text 用页面默认值）；否则取消。
5. 用户在实时画面里亲手点（接管）→ service 用 dialog="accept"：那是用户自己的操作。
6. 一次动作里弹了超过 DIALOGS_MAX 个框（网页连环弹框）→ 之后的 confirm / prompt 一律取消，只记条数。
话只留前 MESSAGE_MAX 字。给模型的说法在后端 app/agent/builtin/browser.py dialog_note。
"""
from dataclasses import dataclass

MESSAGE_MAX = 300
DIALOGS_MAX = 5
KINDS = ("alert", "confirm", "prompt", "beforeunload")
ARMS = ("accept", "dismiss")


@dataclass
class Decision:
    accept: bool
    text: str | None   # prompt 要填的字（只有 accept 的 prompt）
    note: dict         # 进快照 dialogs 字段：{kind, message, accepted, auto, text?}


def arm(value) -> str | None:
    """请求里的 dialog 字段 → "accept" / "dismiss" / None（其它值当没说）。"""
    v = str(value or "").strip().lower()
    return v if v in ARMS else None


def decide(kind: str, message: str, default: str = "", armed: str | None = None, seen: int = 0,
           text: str | None = None) -> Decision:
    """kind = Playwright dialog.type；armed = 这次动作说好的处理；seen = 这次动作里之前已弹过几个；
    text = 模型给 prompt 要填的字（None = 用页面默认值）。"""
    kind = kind if kind in KINDS else "alert"
    msg = " ".join(str(message or "").split())[:MESSAGE_MAX]
    flood = seen >= DIALOGS_MAX
    if kind in ("alert", "beforeunload"):
        accept, auto = True, True
    else:
        accept = armed == "accept" and not flood
        auto = armed is None or flood   # 没说好（或连环弹框）而替模型做的决定
    fill = None
    if kind == "prompt" and accept:
        fill = text if text is not None else (default or "")
    note = {"kind": kind, "message": msg, "accepted": accept, "auto": auto}
    if flood:
        note["flood"] = True
    if fill:
        note["text"] = fill[:MESSAGE_MAX]
    return Decision(accept, fill, note)

