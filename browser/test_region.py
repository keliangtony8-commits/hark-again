"""地区规则单元测试（不需要 Chromium）：python3 browser/test_region.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import region

# 默认：中文 + 上海
r = region.pick(env={})
assert r == region.Region("zh-CN", "Asia/Shanghai") and r.options() == {"locale": "zh-CN", "timezone_id": "Asia/Shanghai"}
# 请求给的优先
assert region.pick("en-US", "America/New_York", env={}) == region.Region("en-US", "America/New_York")
# 规范写法
assert region.clean_locale("zh_tw") == "zh-TW" and region.clean_locale("zh-hant-hk") == "zh-Hant-HK"
assert region.clean_locale("EN") == "en"
# 不像 locale / 时区 → 退回默认（不让 Chromium 因为一个坏值整个上下文起不来）
for bad in ("", None, 3, "en US", "zh-CN;rm", "x" * 40, "en-'"):
    assert region.clean_locale(bad) is None, bad
for bad in ("", None, "../etc/passwd", "Asia/Shanghai;x", "Mars/Olympus", "Asia/../UTC"):
    assert region.clean_tz(bad) is None, bad
assert region.clean_tz("UTC") == "UTC" and region.clean_tz(" Europe/Berlin ") == "Europe/Berlin"
assert region.pick("en US", "Mars/Olympus", env={}) == region.Region("zh-CN", "Asia/Shanghai")
# 环境变量：BROWSER_TZ > TIMEZONE > 默认；坏值跳过
assert region.env_tz({"BROWSER_TZ": "Europe/London", "TIMEZONE": "Asia/Tokyo"}) == "Europe/London"
assert region.env_tz({"BROWSER_TZ": "bad zone", "TIMEZONE": "Asia/Tokyo"}) == "Asia/Tokyo"
assert region.pick(None, None, env={"TIMEZONE": "Asia/Tokyo"}).timezone_id == "Asia/Tokyo"
# 重开判定：没记录（老会话）不动；一样不动；变了重开
a, b = region.Region("zh-CN", "Asia/Shanghai"), region.Region("en-US", "Asia/Shanghai")
assert not region.needs_reopen(None, a) and not region.needs_reopen(a, region.Region("zh-CN", "Asia/Shanghai"))
assert region.needs_reopen(a, b) and region.needs_reopen(a, region.Region("zh-CN", "UTC"))
print("test_region ok")
