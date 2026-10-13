"""frames.py 规则单测（纯函数，不要浏览器）：python3 browser/test_frames.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import frames as F  # noqa: E402

box = {"width": 400, "height": 300}
assert F.include("https://js.stripe.com/v3/x", box, 1)
assert F.include("about:blank", box, 1) and F.include("about:srcdoc", box, 2)
assert not F.include("https://a.com", None, 1)                       # 看不见 / 已脱离
assert not F.include("https://pixel.ads.com", {"width": 1, "height": 1}, 1)  # 统计像素
assert not F.include("https://a.com", {"width": 300, "height": 10}, 1)
assert not F.include("https://a.com", box, F.DEPTH_MAX + 1)
assert not F.include("https://a.com", box, 0)                         # 0 = 主页面自己
assert not F.include("javascript:void(0)", box, 1) and not F.include("data:text/html,x", box, 1)
assert F.include("HTTPS://A.COM", box, 1)

assert F.label("https://js.stripe.com/v3", "https://shop.cn/pay") == "js.stripe.com"
assert F.label("https://www.youtube.com/embed/1", "https://a.cn") == "youtube.com"
assert F.label("https://shop.cn/frame", "https://shop.cn/pay") == "同站"
assert F.label("about:blank", "https://shop.cn") == "同站"

assert F.budget(0) == F.ELEMENT_MAX and F.budget(149) == 1 and F.budget(200) == 0

# 文字：框接在后面、带标签；空框不写；每框截 FRAME_TEXT_MAX
t = F.merge_text("主页", [("js.stripe.com", "卡号 有效期"), ("同站", "  "), ("x.com", "长" * 5000)], 6000)
assert t.startswith("主页\n\n【内嵌框 · js.stripe.com】\n卡号 有效期") and "同站" not in t
assert t.count("长") == F.FRAME_TEXT_MAX
# 总长不超；主页面至少留 MAIN_MIN，框先被截
t = F.merge_text("主" * 6000, [("a.com", "框" * 1500), ("b.com", "框" * 1500)], 6000)
assert len(t) <= 6000 + 40 and t.count("主") >= F.MAIN_MIN and "【内嵌框 · a.com】" in t, (len(t), t.count("主"))
# 主页面短 → 框能占满剩下的
t = F.merge_text("短", [("a.com", "字" * 1500)] * 3, 6000)
assert t.count("字") == 4500
# 没框 → 主页面照旧截 total
assert F.merge_text("主" * 7000, [], 6000) == "主" * 6000
print("frames ok")
