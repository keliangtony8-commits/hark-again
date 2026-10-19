"""云浏览器对网站自报的“身份”——唯一规则入口（v3.5.x，接管点不动 Cloudflare Turnstile 查根因时加）。

用户在接管页亲手点人机验证（Turnstile 复选框）：点击确实送进了跨源 iframe（isTrusted、pointerType=mouse、
buttons 正确，见 test_takeover_chromium.py），但 Cloudflare 转一圈又退回复选框——它判的是“这是不是自动化浏览器”，
而 Playwright 默认把这几处明摆着告诉网页：
- `--enable-automation` → navigator.webdriver = true（WebDriver 规范要求自动化会话这么报）；
- UA 里是 `HeadlessChrome/…`。
这里只关掉这两处“自动化开关 / 无头标记”，让网页看到的是一个普通的 Chrome（版本号就是真实内核的大版本，
格式同真 Chrome 的精简 UA：`Chrome/<大版本>.0.0.0`）。**不做**指纹伪造（不改 canvas / WebGL / 屏幕 / 插件，
不注入脚本改事件），网站风控仍可能凭 IP（机房 IP）、无头渲染特征等判为机器人——这一点不保证。

仍留着的已知信号（改不了或不该在这里改）：Playwright 1.47 的旧无头模式下 navigator.userAgentData.brands 里
还有 “HeadlessChrome”、outerWidth/outerHeight 为 0；要去掉得换新无头模式（Playwright ≥1.49 的 channel="chromium"），
那是换镜像版本的事，见 HANDOFF。
"""
import re

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]  # navigator.webdriver 不再是 true
IGNORE_DEFAULT_ARGS = ["--enable-automation"]                    # Playwright 默认加的“受自动化控制”开关


def user_agent(browser_version: str) -> str:
    """真实内核版本（Browser.version，如 '128.0.6613.18'）→ 普通桌面 Chrome 的精简 UA（不带 Headless）。
    平台段固定 'X11; Linux x86_64'：Chrome 的 UA 精简在 Linux 上一律这么报（arm 机器也一样，和默认 UA 同）。"""
    m = re.match(r"\d+", browser_version or "")
    major = m.group(0) if m else "128"
    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
