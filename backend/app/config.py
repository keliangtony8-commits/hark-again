"""所有配置的唯一入口。其他模块只 import settings，不直接读环境变量。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("settings_",))  # 允许 model_prices 这类字段名
    database_url: str
    # 模型接口：默认指向自带的 LiteLLM 网关（业务只认别名 fast / smart）。
    # 省内存的“直连模式”：LLM_BASE_URL 直接填供应商的 OpenAI 兼容地址（如阶跃 Step Plan），
    # LLM_API_KEY 填供应商 key，MODEL_MAP 把别名翻译成真实模型名；不用跑 LiteLLM 容器。
    llm_base_url: str
    litellm_master_key: str = ""
    llm_api_key: str = ""           # 空 = 用 LITELLM_MASTER_KEY（网关模式）
    model_map: dict[str, str] = {}  # 别名 → 上游模型名；空 = 网关自己翻译
    default_model: str = "fast"
    # 聊天里可选的模型：别名 → 显示名，顺序 = 客户端切换顺序。每个对话可以选一个（conversations.model），
    # 没选或选的别名后来被删了就用 default_model。定时任务、摘要不受影响
    chat_models: dict[str, str] = {"fast": "快速", "smart": "深度"}
    summary_model: str = "fast"     # 滚动摘要用的便宜模型别名
    # 看图（vision.py）：能直接收图片的别名（阶跃 step-3.7-flash = fast、step-5-preview = smart 实测都能看图；lite 不能）；其余别名看到的是图片的文字描述。
    # vision_model = 写描述用的看图别名（每张图只描述一次并缓存）；image_max_side = 发给模型前缩到的最长边（省 token）
    vision_models: list[str] = ["fast", "smart"]
    vision_model: str = "fast"
    image_max_side: int = 1280
    history_chars: int = 24000      # 发给模型的对话原文预算（字符）；超出部分折叠进摘要
    # 用量与花费（usage.py）：别名 → [输入单价, 输出单价]，单位 currency / 百万 token；没写的别名只记 token 不算钱
    model_prices: dict[str, list[float]] = {}
    currency: str = "CNY"
    monthly_budget: float = 0.0     # 每月预算，0 = 不设；只用于提示，不拦截调用
    budget_alerts: list[float] = [0.8, 1.0]  # 本月花费跨过预算的这些比例时，在 Home 放一张提醒卡（每月每档一次）
    searxng_url: str = "http://searxng:8080"
    timezone: str = "Asia/Shanghai"
    data_dir: str = "/data"
    max_upload_mb: int = 20
    sandbox_url: str = "http://sandbox:9000"
    sandbox_token: str = "change-me"
    stt_model: str = "stt"      # 语音识别别名（gateway 模式走 OpenAI 音频接口）
    embed_model: str = "embed"  # 记忆检索的向量别名
    # 语音供应商：gateway = 识别走网关 stt 别名、朗读用设备自带语音；
    # stepfun = 识别用阶跃 stepaudio-2.5-asr（SSE）、朗读用 stepaudio-2.5-tts（服务器合成，更自然）
    voice_provider: str = "gateway"
    step_api_key: str = ""
    step_base_url: str = "https://api.stepfun.ai/step_plan/v1"  # 国内账号用 https://api.stepfun.com/step_plan/v1
    step_asr_model: str = "stepaudio-2.5-asr"
    step_tts_model: str = "stepaudio-2.5-tts"
    step_tts_voice: str = "elegantgentle-female"
    browser_url: str = "http://browser:9100"
    browser_token: str = "change-me"
    vault_key: str = ""  # Fernet 密钥，见 .env.example
    public_url: str = "http://localhost"  # 外网访问地址，OAuth 回调用
    app_scheme: str = "myassistant"  # 原生 App 的深链 scheme，须与 AndroidManifest / Info.plist 一致
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    # 安卓 App（Capacitor）的 WebView 来源；网页同源访问不需要
    cors_origins: list[str] = ["https://localhost", "capacitor://localhost", "http://localhost"]

    owner_username: str
    owner_password: str
    jwt_secret: str
    jwt_ttl_hours: int = 24 * 30

    system_prompt: str = (
        "你是用户的私人助手。先给答案，再给理由；简洁、具体、不说套话。\n"
        "需要最新或可核实的信息时先 web_search，再按需 web_fetch，不要编造。\n"
        "用户说出以后还用得上的偏好或事实时调用 remember；某条记忆变了用 update_memory，要求忘掉用 forget（都按记忆后的 # 引用）。\n"
        "多行同类对比用 show_table，要点开的页面用 show_links；卡片里有的内容文字里不要重复。\n"
        "需要登录、点击或填表的网站用 browser_open 等浏览器工具；只是读资料用 web_fetch（浏览器很费 token）。"
        "遇到登录、密码、验证码，请用户在实时画面里自己操作，完成后 browser_read 继续。\n"
        "用户想反复查看的变化信息（价格、包裹、比分、预算）用 create_panel 放到 Home（已有的面板和卡片用 manage_home 查看、改、删）；定时去做一件事用 schedule_task。\n"
        "用户要别人也能看的东西（行程、邀请、菜单、简历）时用 publish_page 做成网页。\n"
        "任务和某个技能匹配时，先 use_skill 读取做法再动手；用户让你记住一套做法时用 save_skill。"
    )


settings = Settings()
