"""钟表工具：现在几点、换算时区、算相对日期（规则全在 app/clock.py）。只读、不花模型额度、可并行。"""
from ... import clock
from ..tools import ToolContext, ToolResult, tool

_TZ = {"type": "string", "description": "IANA 时区名（如 Asia/Shanghai、America/New_York），也认“东京”“纽约”、UTC+8；不填 = 用户的时区"}


def _fail(e: clock.ClockError) -> ToolResult:
    return ToolResult(f"没算成：{e}", failed=str(e))


@tool("get_current_time", "正在看时间",
      "现在的准确日期、星期、时刻和 UTC 偏移。系统提示里的“现在”是这一轮开始时的；一轮做了很久、"
      "定时任务里要判断“现在过没过某个点”、或用户问别的城市现在几点时调它。",
      {"type": "object", "properties": {"timezone": _TZ}}, parallel=True)
async def get_current_time(ctx: ToolContext, timezone: str = "") -> ToolResult:
    try:
        text, detail = clock.now_text(timezone)
    except clock.ClockError as e:
        return _fail(e)
    return ToolResult(text, detail=detail)


@tool("convert_time", "正在换算时区",
      "把某个时区某一天的钟点换算到另一个时区（按那一天的夏令时）。说别的时区的时间、跨时区约会议、看航班当地时间时用，"
      "不要自己加减时差。不是今天的事一定带 date。",
      {"type": "object", "properties": {
          "time": {"type": "string", "description": "24 小时制 HH:MM，如 19:30"},
          "source_timezone": _TZ,
          "target_timezone": _TZ,
          "date": {"type": "string", "description": "这个钟点在源时区是哪天，YYYY-MM-DD；不填 = 源时区的今天"},
      }, "required": ["time", "source_timezone", "target_timezone"]}, parallel=True)
async def convert_time(ctx: ToolContext, time: str, source_timezone: str, target_timezone: str,
                       date: str = "") -> ToolResult:
    try:
        c = clock.convert(time, source_timezone, target_timezone, date or None)
    except clock.ClockError as e:
        return _fail(e)
    return ToolResult(c.text, detail=c.detail)


@tool("resolve_relative_date", "正在算日期",
      "把“明天”“下周一”“10 天后”“月底前两周”这类相对说法换成准确的日期和星期。凡是要说出或用到一个相对日期"
      "（回答、建定时任务、写进记忆、填表），都先调它，不要自己心算——哪怕前面算过相似的日子。"
      "你先按今天的日期和星期想好是第几天（今天 0、明天 1、昨天 -1），工具算出日期；常见写法工具会自己核对，"
      "对不上时以写法为准并告诉你。一句话里有几个日子就调几次（可一起调）。",
      {"type": "object", "properties": {
          "expression": {"type": "string", "description": "用户原话里的说法，原样照抄，如“下周三”“in 10 days”"},
          "days_from_today": {"type": "integer", "description": "离今天几天（今天 0，明天 1，过去为负）"},
          "timezone": _TZ,
      }, "required": ["expression", "days_from_today"]}, parallel=True)
async def resolve_relative_date(ctx: ToolContext, expression: str, days_from_today: int,
                                timezone: str = "") -> ToolResult:
    try:
        r = clock.resolve(expression, days_from_today, timezone)
    except clock.ClockError as e:
        return _fail(e)
    return ToolResult(r.text, detail=r.detail)
