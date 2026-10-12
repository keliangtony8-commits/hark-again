"""订单类工具：付款前的确认卡、下单后的回执。两张都是 order 块（blocks.OrderBlock）。

confirm_order 走内核的审批流程（risk 永远要批准），但审批卡换成订单卡本身（Tool.card）：
用户在卡上点“确认下单” = approval.reply approved → 卡片变“已确认”、工具返回让模型去完成付款；
点“不买了” / 停止 / 无人值守（定时任务 deny_all）→ 不付款。金额全部原样照页面写，服务器不算账。"""
import uuid

from ...blocks import OrderBlock
from ..tools import ToolContext, ToolResult, tool

ACTION_MAX = 12

_LINE = {"type": "object", "properties": {
    "name": {"type": "string"}, "price": {"type": "string", "description": "原样：¥59.00"},
    "qty": {"type": "integer", "minimum": 1}, "note": {"type": "string", "description": "规格：黑色 · M 码"},
    "image": {"type": "string", "description": "页面上这件商品的图片地址（可选）"}},
    "required": ["name", "price"]}
_FEE = {"type": "object", "properties": {"label": {"type": "string"}, "amount": {"type": "string"}}, "required": ["label", "amount"]}
_ORDER = {
    "merchant": {"type": "string", "description": "付给谁、哪家店：瑞幸咖啡 · 五道口店"},
    "items": {"type": "array", "items": _LINE},
    "breakdown": {"type": "array", "items": _FEE, "description": "运费、优惠、税，照页面写"},
    "total": {"type": "string", "description": "页面上的合计，原样"},
    "payment": {"type": "string", "description": "页面上的付款方式：招行信用卡 9258"},
    "destination": {"type": "string", "description": "送到哪 / 什么时候"},
}


def _block(args: dict, **extra) -> dict:
    """照参数画一张订单卡；参数不对抛 ValueError（内核会把错误交回模型，不打扰用户）。"""
    try:
        return OrderBlock(
            id=extra.pop("id", uuid.uuid4().hex),
            merchant=str(args.get("merchant") or "").strip(),
            items=[{k: v for k, v in i.items() if v not in (None, "")} for i in args.get("items") or []],
            breakdown=args.get("breakdown") or [],
            total=str(args.get("total") or "").strip(),
            payment=(args.get("payment") or "").strip() or None,
            destination=(args.get("destination") or "").strip() or None,
            **extra,
        ).model_dump()
    except Exception as e:  # pydantic ValidationError → 一句话给模型
        raise ValueError(f"订单卡字段不完整或格式不对（merchant、items[name, price]、total 必填）：{e}") from e


def _confirm_card(args: dict) -> dict:
    action = (args.get("action") or "确认下单").strip()[:ACTION_MAX] or "确认下单"
    b = _block(args, action=action)
    if not b["merchant"] or not b["total"]:
        raise ValueError("merchant 和 total 不能为空")
    return b


@tool("confirm_order", "正在等你确认订单",
      "付款/下单前的最后一步：把页面上的订单（商家、每件商品和价格、运费优惠、合计、付款方式、送达）原样做成订单卡，"
      "用户在卡上点按钮才算同意。只在已经停在付款页、总价确定时调用；用户同意后再去点付款，拒绝了就别买。"
      "金额照页面原样写，不要自己算。",
      {"type": "object", "properties": {**_ORDER,
          "action": {"type": "string", "description": "按钮上的字，说清买的是什么：确认下单 / 订这间房 / 付款"}},
       "required": ["merchant", "items", "total"]},
      risk=lambda args, ctx=None: "确认下单", card=_confirm_card)
async def confirm_order(ctx: ToolContext, total: str, merchant: str = "", **_) -> ToolResult:
    # 走到这里说明用户已经在订单卡上点了同意（卡片已由内核更新为 approved）
    return ToolResult(f"用户已在订单卡上确认（{merchant}，合计 {total}）。现在去完成付款；"
                      "付完用 show_receipt 展示订单号。如果页面要求的金额和卡上不一致，先停下来告诉用户，不要付。")


@tool("show_receipt", "正在整理订单回执",
      "下单/付款成功后，把页面上的订单回执做成订单卡（带订单号，没有按钮）。只在真的下单成功、看到订单号后用。",
      {"type": "object", "properties": {**_ORDER, "order_number": {"type": "string"}},
       "required": ["merchant", "items", "total", "order_number"]})
async def show_receipt(ctx: ToolContext, **args) -> ToolResult:
    number = str(args.get("order_number") or "").strip()
    if not number:
        return ToolResult("没有订单号，说明还没真正下单成功，不要出回执；先确认页面上的结果。")
    try:
        block = _block(args, order_number=number, state="placed")
    except ValueError as e:
        return ToolResult(str(e))
    return ToolResult(f"订单回执已展示（订单号 {number}）。文字里只说接下来会发生什么。", [block])
