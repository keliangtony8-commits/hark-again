"""shadow.py 规则单测（纯函数，不要浏览器）：python3 browser/test_shadow.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import shadow as S  # noqa: E402

assert S.js_args() == {"shadowDepth": S.DEPTH_MAX, "shadowRoots": S.ROOT_MAX}
# 段落接在主页面后面，带标签名；空白行收拢
t = S.merge_text("主页面", [("buy-box", "  ¥89  \n\n\n 加入购物车 "), ("x-empty", "  \n "), ("x-icon", "×")])
assert t == "主页面\n\n【组件 · buy-box】\n¥89\n\n加入购物车", repr(t)
# 重复段、主页面已有的（插槽里的字）不写
t = S.merge_text("欢迎 小明", [("a-b", "同意"), ("c-d", "同意"), ("slot-x", "欢迎 小明")])
assert t.count("【组件") == 1 and "c-d" not in t and "slot-x" not in t, t
# 每段截到 TEXT_MAX，段数到 ROOT_MAX 停
t = S.merge_text("", [("x", "字" * (S.TEXT_MAX + 50))])
assert t.count("字") == S.TEXT_MAX
t = S.merge_text("", [(f"x-{i}", f"第{i}段") for i in range(S.ROOT_MAX + 5)])
assert t.count("【组件") == S.ROOT_MAX
# 没有组件文字 = 原样
assert S.merge_text("abc", []) == "abc"
print("shadow ok")
