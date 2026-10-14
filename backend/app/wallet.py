"""钱包（v2.74，对标 Hark 设置里的 Wallets + 结账时浏览器代填付款卡）：“存卡 / 认卡 / 什么时候能把卡填进网页”只此一处。

存：卡号 + 安全码整包加密（vault.encrypt），库里明文只有 label、卡组织、末 4 位、有效期、持卡人、邮编。
没有任何接口返回卡号或安全码；模型只见 describe() 那一行。
填：browser_pay_card → may_fill（用户刚在订单卡上点了同意、订单卡付款方式写的就是这张卡、没过期、
没超时）→ frame_block（卡号框只能在主页面同站或公认的支付机构内嵌框里）→ fields() 生成要填的值 →
浏览器代填（卡号/安全码框打上 data-secret，之后快照里不出现它的值）→ scrub() 再把页面文字里回显的整串卡号抹掉。
付款按钮：订单卡刚批准过 → order_covers_click 认为这一下已经同意过，不再弹第二张通用审批卡（Hark：pay step 只问一次）。"""
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import vault
from .browser_sessions import Tab, site_of
from .models import PaymentCard
from .wire_time import iso

CARDS_MAX = 10
LABEL_MAX = 60
HOLDER_MAX = 80
POSTAL_MAX = 16
YEARS_AHEAD = 20       # 有效期最多填到今年 + 20 年
ORDER_TTL_S = 15 * 60  # 订单卡批准后多久内可以代填卡 / 点付款

BRAND_NAMES = {"visa": "Visa", "mastercard": "Mastercard", "amex": "American Express", "unionpay": "银联",
               "jcb": "JCB", "discover": "Discover", "diners": "Diners Club", "card": "银行卡"}

# 公认的支付机构：结账页把卡号框嵌在它们的内嵌框里是常态（Stripe Elements、Braintree Hosted Fields…）。
# 别的网站嵌进来的框一律不填卡（和 v2.59 “主站密码不填进别人家的框”同一个道理）。
PAYMENT_FRAME_SITES = frozenset({
    "stripe.com", "stripe.network", "braintreegateway.com", "braintree-api.com", "adyen.com", "adyenpayments.com",
    "checkout.com", "paypal.com", "paypalobjects.com", "squareup.com", "squarecdn.com", "recurly.com",
    "chargebee.com", "airwallex.com", "worldpay.com", "cybersource.com", "authorize.net", "globalpay.com",
    "klarna.com", "mollie.com", "paddle.com", "alipay.com", "tenpay.com", "unionpay.com", "95516.com",
})

PAY_WORDS = re.compile(r"支付|付款|购买|下单|提交订单|确认订单|pay|buy|purchase|checkout|place order|complete order", re.I)
NOT_PAY = re.compile(r"删除|发送|发布|delete|send|post", re.I)

KINDS = ("number", "exp", "exp_month", "exp_year", "cvc", "holder", "postal")
SECRET_KINDS = frozenset({"number", "cvc"})


class CardError(ValueError):
    def __init__(self, message: str, kind: str = "invalid"):
        super().__init__(message)
        self.kind = kind  # invalid | dupe | full


# ---------- 卡号规则 ----------

def digits(number: str) -> str:
    """去掉空格、横线；别的字符 → CardError。"""
    s = re.sub(r"[\s-]", "", number or "")
    if not s.isdigit():
        raise CardError("卡号只能是数字（可以带空格）")
    if not 12 <= len(s) <= 19:
        raise CardError("卡号位数不对（12–19 位）")
    return s


def brand(number: str) -> str:
    n = number
    p2, p4 = int(n[:2]), int(n[:4])
    if p2 in (34, 37):
        return "amex"
    if n[0] == "4":
        return "visa"
    if 51 <= p2 <= 55 or 2221 <= p4 <= 2720:
        return "mastercard"
    if p2 == 62:
        return "unionpay"
    if 3528 <= p4 <= 3589:
        return "jcb"
    if n.startswith("6011") or p2 == 65 or 644 <= int(n[:3]) <= 649:
        return "discover"
    if p2 in (36, 38) or 300 <= int(n[:3]) <= 305:
        return "diners"
    return "card"


def luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def check_number(number: str) -> tuple[str, str]:
    """→ (纯数字卡号, 卡组织)。银联有的借记卡不满足 Luhn 校验，只对银联放宽。"""
    n = digits(number)
    b = brand(n)
    if b != "unionpay" and not luhn(n):
        raise CardError("卡号校验没通过，可能抄错了一位")
    return n, b


def check_expiry(month: int | str, year: int | str, today: date | None = None) -> tuple[int, int]:
    today = today or date.today()
    try:
        m, y = int(str(month).strip()), int(str(year).strip())
    except ValueError:
        raise CardError("有效期要写数字：月 1–12，年 2028 或 28") from None
    y = y + 2000 if y < 100 else y
    if not 1 <= m <= 12:
        raise CardError("有效期的月份要在 1–12 之间")
    if (y, m) < (today.year, today.month):
        raise CardError("这张卡已经过期了")
    if y > today.year + YEARS_AHEAD:
        raise CardError("有效期的年份不对")
    return m, y


def check_cvc(cvc: str, card_brand: str) -> str:
    c = (cvc or "").strip()
    want = (4,) if card_brand == "amex" else (3,) if card_brand != "card" else (3, 4)
    if not c.isdigit() or len(c) not in want:
        raise CardError(f"安全码是卡背面的 {'4' if card_brand == 'amex' else '3'} 位数字")
    return c


def expired(card: PaymentCard, today: date | None = None) -> bool:
    today = today or date.today()
    return (card.exp_year, card.exp_month) < (today.year, today.month)


def exp_text(card: PaymentCard) -> str:
    return f"{card.exp_month:02d}/{card.exp_year % 100:02d}"


def describe(card: PaymentCard) -> str:
    """模型和日志里这张卡的全部样子：招行信用卡（Visa 尾号 9258，有效期到 2028 年 9 月，没过期）。
    真测 B41：写成“有效期 09/30”时模型把它当成 9 月 30 日、对用户说“卡已经过期了”→ 写全年月 + 明说过没过期。"""
    state = "已过期" if expired(card) else "没过期"
    return f"{card.label}（{BRAND_NAMES.get(card.brand, '银行卡')} 尾号 {card.last4}，有效期到 {card.exp_year} 年 {card.exp_month} 月，{state}）"


def public(card: PaymentCard) -> dict:
    return {"id": card.id, "label": card.label, "brand": card.brand, "brand_name": BRAND_NAMES.get(card.brand, "银行卡"),
            "last4": card.last4, "exp_month": card.exp_month, "exp_year": card.exp_year, "exp": exp_text(card),
            "holder": card.holder, "postal_code": card.postal_code, "expired": expired(card),
            "created_at": iso(card.created_at), "last_used_at": iso(card.last_used_at) if card.last_used_at else None}


# ---------- 存 / 删 / 找 ----------

async def cards(db: AsyncSession) -> list[PaymentCard]:
    return list((await db.scalars(select(PaymentCard).order_by(PaymentCard.created_at))).all())


async def add(db: AsyncSession, number: str, exp_month, exp_year, cvc: str, label: str = "", holder: str = "",
              postal_code: str = "", today: date | None = None) -> PaymentCard:
    n, b = check_number(number)
    m, y = check_expiry(exp_month, exp_year, today)
    c = check_cvc(cvc, b)
    have = await cards(db)
    for old in have:
        if old.last4 == n[-4:] and old.brand == b and (old.exp_month, old.exp_year) == (m, y):
            raise CardError(f"钱包里已经有这张卡了：{old.label}", "dupe")
    if len(have) >= CARDS_MAX:
        raise CardError(f"钱包最多放 {CARDS_MAX} 张卡，先删一张不用的", "full")
    holder, postal = (holder or "").strip()[:HOLDER_MAX], re.sub(r"\s", "", postal_code or "")[:POSTAL_MAX]
    label = re.sub(r"\s+", " ", (label or "").strip())[:LABEL_MAX] or f"{BRAND_NAMES.get(b, '银行卡')} {n[-4:]}"
    card = PaymentCard(label=label, brand=b, last4=n[-4:], exp_month=m, exp_year=y, holder=holder, postal_code=postal,
                       ciphertext=vault.encrypt(json.dumps({"number": n, "cvc": c})))
    db.add(card)
    return card


def rename(card: PaymentCard, label: str) -> None:
    label = re.sub(r"\s+", " ", (label or "").strip())[:LABEL_MAX]
    if not label:
        raise CardError("名字不能为空")
    card.label = label


def find(have: list[PaymentCard], want: str) -> PaymentCard | None:
    """模型说的“哪张卡”：id → 名字（不分大小写）→ 句子里的末 4 位 → 唯一的卡组织 → 只有一张卡时就是它。"""
    w = (want or "").strip()
    if not have:
        return None
    for c in have:
        if w == c.id or w.casefold() == c.label.casefold():
            return c
    hits = [c for c in have if c.last4 in re.findall(r"\d{4}", w)]
    if len(hits) == 1:
        return hits[0]
    hits = [c for c in have if c.label.casefold() in w.casefold() or BRAND_NAMES.get(c.brand, "").casefold() == w.casefold()]
    if len(hits) == 1:
        return hits[0]
    return have[0] if len(have) == 1 and not w else None


def reveal(card: PaymentCard) -> dict:
    return json.loads(vault.decrypt(card.ciphertext))


def mark_used(card: PaymentCard) -> None:
    card.last_used_at = datetime.now(timezone.utc)


def prompt_line(have: list[PaymentCard]) -> str:
    """系统提示里的一行（卡变了才变，缓存稳定）；没有卡 → ""。"""
    if not have:
        return ""
    # 真测 B42：原来的写法像操作说明，用户问“钱包里有哪些卡”时模型去翻记忆、答“没有”→ 先说这是用户的钱包、问到就照这里答
    return ("用户的钱包（我的 → 钱包）里存着这些付款卡，问到钱包、银行卡、哪张卡快过期时直接照这里回答：" + "；".join(describe(c) for c in have)
            + "。结账时先 confirm_order 让用户确认（订单卡的付款方式写这张卡），批准后用 browser_pay_card 代填；卡号和安全码你永远看不到。")


# ---------- 什么时候能填 ----------

def remember_order(tab: Tab, payment: str | None, total: str, now: float | None = None) -> None:
    """订单卡批准了：记下这一单（钱包代填和付款按钮只认它）。"""
    tab.order = {"payment": payment or "", "total": total, "at": now if now is not None else time.time()}


def forget_order(tab: Tab) -> None:
    tab.order = None


def _live_order(tab: Tab, now: float | None = None) -> dict | None:
    o = tab.order
    if not o:
        return None
    return o if (now if now is not None else time.time()) - o["at"] <= ORDER_TTL_S else None


def may_fill(tab: Tab, card: PaymentCard, now: float | None = None, today: date | None = None) -> str | None:
    """不能填 → 原因（给模型）；能填 → None。"""
    if expired(card, today):
        return f"{describe(card)}：这张卡过期了，不能用；告诉用户，让他到 我的 → 钱包 换一张。"
    o = _live_order(tab, now)
    if o is None:
        return ("还没有用户刚批准的订单：先停在付款页，用 confirm_order 把订单原样做成订单卡（payment 写要用的这张卡），"
                "用户点了同意再代填。")
    pay = o["payment"]
    if card.last4 not in pay and card.label.casefold() not in pay.casefold():
        return (f"用户批准的订单卡上付款方式是「{pay or '没写'}」，不是 {describe(card)}：要换卡就重新 confirm_order，"
                "让用户在新订单卡上同意。")
    return None


def frame_block(tab: Tab, refs: list[str]) -> str | None:
    """卡号这类框在别家网站的内嵌框里（不是同站、也不是公认的支付机构）→ 那个域名；都放心 → None。"""
    for r in refs:
        host = tab.frames.get(str(r))
        if host and site_of(host) not in PAYMENT_FRAME_SITES and site_of(host) != site_of(tab.url):
            return host
    return None


def order_covers_click(tab: Tab, name: str, now: float | None = None) -> bool:
    """点的是付款类按钮、且用户刚在订单卡上同意过这一单 → 不再弹第二张审批卡。"""
    return bool(name) and bool(PAY_WORDS.search(name)) and not NOT_PAY.search(name) and _live_order(tab, now) is not None


def _month_options(m: int) -> list[str]:
    import calendar
    return [f"{m:02d}", str(m), f"{m}月", f"{m:02d}月", calendar.month_abbr[m], calendar.month_name[m]]


def fields(card: PaymentCard, secret: dict, refs: dict[str, str], names: dict[str, str]) -> list[dict]:
    """要填的框 → 浏览器请求里的 fields：[{ref, value, options, secret}]。options = 下拉框可接受的写法（依次试）。
    合并的有效期框按占位写法：带 YYYY / 年年年年 → 09/2028，否则 09/28。"""
    out = []
    for kind in KINDS:
        ref = str(refs.get(kind) or "").strip()
        if not ref:
            continue
        name = names.get(ref, "")
        if kind == "number":
            values = [secret["number"]]
        elif kind == "cvc":
            values = [secret["cvc"]]
        elif kind == "exp":
            long = re.search(r"YYYY|yyyy|年年年年", name)
            values = [f"{card.exp_month:02d}/{card.exp_year if long else card.exp_year % 100:02d}"]
        elif kind == "exp_month":
            values = _month_options(card.exp_month)
        elif kind == "exp_year":
            values = [str(card.exp_year), f"{card.exp_year % 100:02d}", f"{card.exp_year}年"]
        elif kind == "holder":
            values = [card.holder]
        else:
            values = [card.postal_code]
        if not values[0]:
            raise CardError(f"钱包里这张卡没有存{'持卡人姓名' if kind == 'holder' else '邮编'}：这一格请用户自己填，或用 browser_type 填页面上给的。")
        out.append({"ref": ref, "value": values[0], "options": values, "secret": kind in SECRET_KINDS})
    if not any(f["secret"] and f["value"] == secret["number"] for f in out):
        raise CardError("至少要给卡号框的编号（number）")
    return out


# 真测 B43：模型只给了卡号框编号，有效期 / 安全码空着就点了付款 → 页面“请填写完整的卡信息”。
# 模型没给的那几格，按快照里框的名字（标签 / 占位）补上；按钮、链接的名字不会对上这些词。
GUESS = (
    ("exp", re.compile(r"MM\s*/\s*(YY|YYYY)|月\s*/\s*年|有效期|到期|expir|exp\b", re.I)),
    ("cvc", re.compile(r"安全码|校验码|CVV|CVC|CSC|CID|security code", re.I)),
    ("holder", re.compile(r"持卡人|cardholder|name on card|card holder", re.I)),
    ("postal", re.compile(r"邮编|邮政编码|postal|zip", re.I)),
)
NAME_MAX = 30  # 名字太长的（整段说明文字）不算一个框


def guess_refs(given: dict[str, str], names: dict[str, str], card: PaymentCard) -> tuple[dict[str, str], list[str]]:
    """→ (补全后的 refs, 补上的 kind)。只补模型没给的；同一个名字对上不止一个框就不补（判不准）；
    卡里没存持卡人 / 邮编就不补那一格（页面要的话让模型自己处理）；有效期已分月/年给了就不再补合并框。"""
    used = set(given.values())
    out, added = dict(given), []
    for kind, rx in GUESS:
        if kind in out or (kind == "exp" and ("exp_month" in out or "exp_year" in out)):
            continue
        if (kind == "holder" and not card.holder) or (kind == "postal" and not card.postal_code):
            continue
        hits = [r for r, n in names.items() if r not in used and n and len(n) <= NAME_MAX and rx.search(n)]
        if len(hits) == 1:
            out[kind] = hits[0]
            used.add(hits[0])
            added.append(kind)
    return out, added


# 真测 B44：代填被拒（还没出订单卡）后，模型用 browser_type 自己往卡号框里敲了一个“测试卡号”和安全码——编造的卡信息。
# 卡号 / 安全码只能由 browser_pay_card 从钱包填；用户自己在聊天里报的卡号也不经模型手（走钱包或接管）。
CARD_FIELD = re.compile(r"卡号|银行卡号|信用卡号|card\s*number|cc-?number|安全码|校验码|CVV|CVC|CSC|security code", re.I)


def typing_block(field_name: str, text: str) -> str | None:
    """browser_type 往卡号 / 安全码框里打字，或打的是一串像卡号的数字（12–19 位且过 Luhn）→ 拒绝的原因；否则 None。"""
    d = re.sub(r"[\s-]", "", text or "")
    looks = d.isdigit() and 12 <= len(d) <= 19 and luhn(d)
    if not (CARD_FIELD.search(field_name or "") or looks):
        return None
    return ("卡号和安全码不能用 browser_type 输入（你看不到真实卡号，绝不能自己编一个）：用户批准订单卡后用 browser_pay_card 从钱包代填；"
            "钱包里没有这张卡就请用户到 我的 → 钱包 添加，或用 browser_handoff 让他自己在画面里填。")


def order_hint(have: list[PaymentCard], payment: str | None) -> str:
    """订单卡批准后给模型的下一步（真测 B44 run1：批准后模型不知道有代填工具，叫用户自己填卡）。"""
    pay = payment or ""
    hit = next((c for c in have if c.last4 in pay or c.label.casefold() in pay.casefold()), None)
    if hit is None:
        return ""
    return (f"付款方式是钱包里的 {describe(hit)}：到了填卡页就用 browser_pay_card（deferred_tool 调用）代填卡号、有效期、安全码，"
            "别自己输入、也别叫用户自己填；填好核对金额再点付款按钮（不会再问一次）。")


_RUN = re.compile(r"\d(?:[ \-\u00a0]?\d){11,18}")


def scrub(text: str, number: str, last4: str) -> str:
    """页面文字里回显的整串卡号（带不带空格）→ •••• 9258。"""
    def sub(m: re.Match) -> str:
        return f"•••• {last4}" if re.sub(r"\D", "", m.group()) == number else m.group()
    return _RUN.sub(sub, text or "")
