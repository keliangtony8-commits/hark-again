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
    # display_file 交付（deliver.py）：拍快照进 uploads 的上限（MB），超过的普通文件退回工作区文件卡
    deliver_max_mb: int = 50
    sandbox_url: str = "http://sandbox:9000"
    sandbox_token: str = "change-me"
    # 后台任务（jobs.py）：单个任务最长秒数、每个项目同时最多跑几个（4GB 小 VPS 默认 2）
    job_max_seconds: int = 3600
    job_max_running: int = 2
    # 护栏：日志超过这么多 MB 就停掉（防撑爆磁盘）；默认连续这么多秒没有任何新输出判定卡住（0 = 不判）
    job_log_max_mb: int = 64
    job_idle_seconds: int = 1200
    # 任务结束“叫醒”助手接着说：用户两次发言之间最多连着叫醒几轮（防“任务结束 → 又起任务 → 又结束”的自激链烧 token；
    # 超出的结论留到用户下次说话时一并告诉助手；0 = 不限）。移植自 deepseek-harness tool-jobs maxConsecutiveWakes
    job_followup_wakes: int = 3
    # 每个工作区（项目 / 我的文件）的磁盘上限（MB，含装的软件和任务日志；0 = 不限）。规则在 quota.py
    workspace_disk_mb: int = 3072
    # 单个工具结果给模型的上限（字符）；超出的完整原文落盘到项目 .spill/（spill.py），主聊天只截断
    tool_result_max: int = 16000
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
    public_url: str = "http://localhost"  # 外网访问地址，OAuth 回调、Pages、端口预览链接用
    internal_url: str = "http://backend:8000"  # 容器之间访问后端的地址：助手自己的云浏览器打开端口预览时用（preview.py）
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
        "多行同类对比用 show_table，要点开的页面用 show_links；用户拿去发的文字（邮件、消息、帖子）用 show_draft；"
        "长的计划、行程、简报用 show_summary；用户想看样子时用 show_images（图片地址只用网页里真实出现的）；挑要买/要订、样子也算数的一组东西用 show_products（商品宫格）；付款前必须用 confirm_order 让用户在订单卡上确认，下单成功后用 show_receipt 出回执。卡片里有的内容文字里不要重复。\n"
        "需要登录、点击或填表的网站用 browser_open 等浏览器工具；只是读资料用 web_fetch（浏览器很费 token）。同一网站的浏览器会话（含登录）会一直保留，先看页面是否已登录再决定要不要登录。"
        "遇到登录用 browser_login、短信/邮箱验证码用 browser_code：它们会在聊天里弹卡片让用户填，你看不到也不要索要密码和验证码；"
        "图形验证码、扫码请用户在实时画面里自己操作，完成后 browser_read 继续。\n"
        "做事缺只有用户知道的具体信息（地址、电话、人数、几个选项里挑哪个）时用 ask_user 弹表单卡一次问齐，别在文字里连环追问；简单的是非题直接问。\n"
        "用户想反复查看的变化信息（价格、包裹、比分、预算）用 create_panel 放到 Home（已有的面板和卡片用 manage_home 查看、改、删）；定时去做一件事用 schedule_task；用户要“准备今天”/当日简报时先 day_overview 再按技能 prep-my-day 写；发现值得替用户做、但要他点头的事（定时运行里尤其如此）用 offer_on_home 在 Home 放一张建议卡（只有用户本人能做的，如重新连接账号，用 open 直达那一页、不写 prompt）。\n"
        "用户要别人也能看的东西（行程、邀请、菜单、简历）时用 publish_page 做成网页。\n"
        "任务和某个技能匹配时，先 use_skill 读取做法再动手；用户让你记住一套做法时用 save_skill。"
    )


settings = Settings()
