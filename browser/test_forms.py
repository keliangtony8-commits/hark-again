"""forms.py 规则单测（纯函数，不要浏览器）：python3 browser/test_forms.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import forms  # noqa: E402

O = [{"text": "请选择", "value": "", "disabled": True}, {"text": "北京", "value": "bj"},
     {"text": "上海", "value": "sh"}, {"text": " 广州  白云 ", "value": "gz"}, {"text": "Shenzhen", "value": "sz"},
     {"text": "上海浦东", "value": "pd"}, {"text": "停售", "value": "x", "disabled": True}]

assert forms.pick(O, "北京") == 1
assert forms.pick(O, "上海") == 2                    # 完全相同优先于“包含”（上海浦东也含“上海”）
assert forms.pick(O, "广州 白云") == 3               # 空白归一
assert forms.pick(O, "sz") == 4                      # 值
assert forms.pick(O, "shenzhen") == 4                # 忽略大小写
assert forms.pick(O, "浦东") == 5                    # 唯一包含
for want, frag in (("杭州", "没有「杭州」"), ("停售", "灰的"), ("", "没写"), ("海", "不止一项")):
    try:
        forms.pick(O, want); raise AssertionError(want)
    except forms.PickError as e:
        assert frag in str(e), (want, str(e))
        assert "请选择" not in str(e) and "「停售」" not in str(e).split("可选")[-1], str(e)  # 禁用项不列
many = [{"text": f"第{i}项", "value": str(i)} for i in range(50)]
try:
    forms.pick(many, "没有")
except forms.PickError as e:
    assert "共 50 项" in str(e) and "第29项" in str(e) and "第30项" not in str(e), str(e)

assert forms.key("Enter") == "Enter" and forms.key("") == "Enter"
assert forms.key("esc") == "Escape" and forms.key("回车") == "Enter" and forms.key("↓") == "ArrowDown"
assert forms.key("arrowdown") == "ArrowDown" and forms.key("Page Down") == "PageDown" and forms.key("shift+tab") == "Shift+Tab"
assert forms.key("pagedown") == "PageDown" and forms.key("空格") == "Space"
for bad in ("Control+w", "F5", "a", "Ctrl+P"):
    try:
        forms.key(bad); raise AssertionError(bad)
    except forms.KeyError_ as e:
        assert "browser_type" in str(e)
print("test_forms ok")
