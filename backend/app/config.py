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
    extract_model: str = ""         # extract_data 结构化提取用的模型别名（空 = summary_model；app/extract.py，每段原文约一次小调用）
    # 自动选模型（app/model_router.py）：对话 / 任务可以选“自动”（auto），每轮开头决定用简单档还是复杂档。
    # model_router = auto（本地规则 + 拿不准时问一次 router_model，约 500 输入 token）/ rules（只用规则，拿不准用复杂档，零调用）/ off（不提供“自动”）。
    # router_default = 没选过模型的对话默认就是“自动”；router_model 空 = summary_model
    model_router: str = "auto"
    router_simple: str = "fast"
    router_complex: str = "smart"
    router_model: str = ""
    router_default: bool = False
    user_shell: bool = True         # 输入框里 !命令 直接在工作区电脑上跑、不经过模型（app/user_shell.py）；false = 当普通消息发给助手
    user_shell_seconds: int = 120   # 用户命令前台最长秒数（沙盒前台上限也是 120）
    auto_title: bool = True         # 第一轮回复后用 summary_model 给新对话起总结标题，之后每约 10 条消息复查一次话题（app/conversation_title.py；每段对话首次 + 每 10 条一次小调用）
    # 看图（vision.py）：能直接收图片的别名（阶跃 step-3.7-flash = fast、step-5-preview = smart 实测都能看图；lite 不能）；其余别名看到的是图片的文字描述。
    # vision_model = 写描述用的看图别名（每张图只描述一次并缓存）；image_max_side = 发给模型前缩到的最长边（省 token）
    vision_models: list[str] = ["fast", "smart"]
    vision_model: str = "fast"
    image_max_side: int = 1280
    history_chars: int = 24000      # 发给模型的对话原文预算（字符）；超出部分折叠进摘要
    # 跨轮工具轨迹（agent/tool_trace.py）：最近几条回复把工具调用 + 截短的结果原样放回历史（0 = 关，只留一行摘要）；
    # 每条回复的轨迹最多多少字。开着每轮约多花 history_trace_turns × history_trace_chars / 3 个输入 token。
    history_trace_turns: int = 2
    history_trace_chars: int = 6000
    # 用量与花费（usage.py）：别名 → [输入单价, 输出单价]，单位 currency / 百万 token；没写的别名只记 token 不算钱
    # 单价（每百万 token）：别名 → [输入, 输出, 命中缓存的输入?]；第三个不填 = 命中也按输入价算（prompt_cache.cost）
    model_prices: dict[str, list[float]] = {}
    # 按对话发 prompt_cache_key（OpenAI 等认；不认的供应商回 400 会自动去掉，见 prompt_cache.py）
    prompt_cache_key: bool = False
    currency: str = "CNY"
    monthly_budget: float = 0.0     # 每月预算，0 = 不设；只用于提示，不拦截调用
    budget_alerts: list[float] = [0.8, 1.0]  # 本月花费跨过预算的这些比例时，在 Home 放一张提醒卡（每月每档一次）
    searxng_url: str = "http://searxng:8080"
    # 助手按模型给的地址出网时（web_guard.py）默认拒内网 / 本机；确需读内网某台机器就在这里列主机名（逗号分隔）
    outbound_allow_hosts: str = ""
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
    # 一轮回复的预算（参考 Gemini CLI MAX_TURNS=100；Codex/deepseek-harness 不设上限只靠用户停止）：
    # agent_max_steps = 最多调用模型几次（每次可带多个工具调用）；agent_turn_tokens = 这一轮累计 token（每次调用的输入都含
    # 全部上文，越往后越贵）。哪个先到都一样：收掉工具，让模型说清做到哪、还差什么，用户回“继续”接着做。
    # 步数至少按 1 算；token 设 0 = 不按 token 管。
    agent_max_steps: int = 40
    agent_turn_tokens: int = 600_000
    # 同一步里连续的只读工具调用（读文件、搜索、读网页）同时跑几个（agent/parallel.py；deepseek-harness 默认 10）；≤1 = 一个个来
    agent_parallel_tools: int = 8
    # 话说一半就停（agent/next_speaker.py，移植 Gemini nextSpeakerChecker）：回复结尾像“接下来我去……”却没调用工具，
    # 替用户补一句“继续”。auto = 本地规则闸门 + 便宜模型判官（只在闸门打开时多一次 summary_model 小调用）；
    # rules = 只看规则、零调用；off = 不检测。next_speaker_max = 每轮最多补几次
    next_speaker_check: str = "auto"
    next_speaker_max: int = 2
    # 工作区规则文件（AGENTS.md 一类，app/workspace_instructions.py）：根目录的每轮进系统提示、子目录的碰到时追加，
    # 每批最多多少字节（deepseek-harness 65536；约 4 字节 1 token，16384 ≈ 4k token 封顶）。0 = 不读
    workspace_instructions_bytes: int = 16384
    # 断线后回答继续写多久（app/live_turns.py）：订阅这一轮的连接全断了，最多再跑几分钟等客户端重连接着看，
    # 到点按“停止”收尾（半截存为 stopped）。0 = 断线即停（v1.60 及以前的行为）。
    turn_offline_minutes: int = 30
    # 子助手（delegate 工具，agent/subagent.py）：一次最多并行几个（Codex 默认 6 个线程，我们 4G 小机器取 4）；
    # 每个子助手的步数 / token / 分钟上限（Gemini generalist：20 轮、10 分钟；到了就收掉工具让它交代进度）。深度固定 1：子助手不能再派。
    # 服务器主机模式（app/host_mode.py）：宿主机上的 host agent（deploy/host-agent）监听这个 unix socket；空 = 没装，功能不出现
    host_agent_socket: str = ""
    host_agent_token: str = ""
    host_command_max_seconds: int = 600
    subagent_max_tasks: int = 4
    subagent_max_steps: int = 20
    subagent_turn_tokens: int = 300_000
    subagent_minutes: float = 10
    # 上文窗口（token）：一轮里上文过窗口的 80% 就先剪长工具结果、不够再把较早的步骤压成摘要（agent/compact.py）。
    # context_tokens = 默认；model_context = 按别名覆盖，如 {"smart": 256000}。窗口填小于真实值只会早点压，不会出错
    # 模型调用的重试（app/llm_retry.py，移植自 deepseek-harness 的 retry-policy）：限流 / 服务器错 / 超时 / 断网 / 空回复
    # 才重试，指数退避 500 ms 起、最长 10 s、±10% 抖动；0 = 不重试。供应商给的 Retry-After 超过上限就不等（直接失败或换备用模型）。
    # llm_idle_seconds = 流式回复多久没新数据算超时（Codex 默认 300 s；我们手机端等不了那么久）。
    # model_fallbacks = 别名 → 备用别名，如 {"smart": "fast"}：重试用完仍失败，这一轮改用备用模型（Gemini CLI 的 flash 回退）
    llm_max_retries: int = 5
    llm_retry_initial_ms: int = 500
    llm_retry_max_ms: int = 10_000
    llm_idle_seconds: float = 120
    model_fallbacks: dict[str, str] = {}
    context_tokens: int = 128_000
    model_context: dict[str, int] = {}
    # 旧工具结果遮盖（agent/tool_mask.py，移植自 Gemini CLI toolOutputMaskingService）：每次调模型前，最新一批和最近
    # tool_mask_protect_tokens 的工具输出原样；更早的累计 ≥ tool_mask_min_tokens 才成批换成预览 + 全文文件路径（无损）。
    # tool_mask_min_tokens=0 关闭
    # 超长日志型工具输出的要点（agent/distill.py，移植自 Gemini CLI toolDistillationService）：首尾截断之外，从被省略的
    # 中间段挑出报错 / 失败 / 退出码 / 文件:行号补在结果末尾。auto = 全文 ≥ tool_distill_chars 时多一次 summary_model
    # 小调用摘要（失败退回本地挑行）；rules = 只本地挑行、零调用；off = 不做
    tool_distill: str = "auto"
    tool_distill_chars: int = 80_000
    tool_mask_protect_tokens: int = 24_000
    tool_mask_min_tokens: int = 12_000
    # 思考强度（app/reasoning.py）：按别名配可选档 + 默认，如 {"smart": {"levels": ["low", "medium", "high"], "default": "medium"}}；
    # 没配的别名不发 reasoning_effort（供应商自己的默认）。客户端在输入框模型钮旁边给“思考”档位
    model_reasoning: dict = {}
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
    preview_rewrite: bool = True  # 端口预览改写页面里以 / 开头的绝对路径（preview_rewrite.py）；有问题时设 false 原样转发
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

    # 不常用的工具（tools 里 deferred=True）不进每次请求的工具列表，经 deferred_tool 查看 / 调用（agent/deferred.py）；False = 全给
    defer_tools: bool = True

    system_prompt: str = (
        "你是 Toyuis，用户的私人助手。先给答案，再给理由；简洁、具体、不说套话。\n"
        "调用工具前说的话用户已经看到了；工具回来后只说新的结果，别把前面那段话再说一遍。\n"
        "需要最新或可核实的信息时先 web_search，再按需 web_fetch，不要编造；要配图先 image_search，图片地址只用搜到的。\n"
        "用户给 YouTube / B 站视频链接要总结或问内容时用 analyze_video 读字幕（长视频再 search_transcript），引用时间点附跳转链接。\n"
        "要说出或用到相对日期（明天、下周三、10 天后）先 resolve_relative_date，别的时区的钟点用 convert_time，不要心算日期和时差。\n"
        "用户提到以前聊过、定过的事（上次、之前说的）而上文和记忆里没有时，先 search_history 翻以前的对话，引用以原文为准，别凭印象编。\n"
        "用户说出以后还用得上的偏好或事实时调用 remember（要你以后都用某种语言回复、或改回跟随他的语言，是设置不是记忆：deferred_tool call set_reply_language {code: zh-Hans/zh-Hant/en/auto}）；某条记忆变了用 update_memory，要求忘掉用 forget（都按记忆后的 # 引用）。记忆没全列出来时，要用到没看到的偏好或事实先 search_memory。\n"
        "关于某个人、地方、项目的一串细节记进 memory_note 主题笔记（同一主题一篇，先看笔记目录）；记忆里易变的事实（价格、营业时间、别人的近况）可能过时，便宜就先核实，没核实就说是之前记下的。\n"
        "多行同类对比用 show_table，要点开的页面用 show_links；用户拿去发的文字（邮件、消息、帖子）用 show_draft；"
        "长的计划、行程、简报用 show_summary；用户想看样子时用 show_images（图片地址只用网页里真实出现的）；挑要买/要订、样子也算数的一组东西用 show_products（商品宫格）；付款前必须用 confirm_order 让用户在订单卡上确认，下单成功后用 show_receipt 出回执。卡片里有的内容文字里不要重复。\n"
        "需要登录、点击或填表的网站用 browser_open 等浏览器工具；只是读资料用 web_fetch（浏览器很费 token）。同一网站的浏览器会话（含登录）会一直保留，先看页面是否已登录再决定要不要登录。"
        "遇到登录用 browser_login、短信/邮箱验证码用 browser_code：它们会在聊天里弹卡片让用户填，你看不到也不要索要密码和验证码；"
        "图形验证码、扫码请用户在实时画面里自己操作，完成后 browser_read 继续。\n"
        "做事缺只有用户知道的具体信息（地址、电话、人数、几个选项里挑哪个）时用 ask_user 弹表单卡一次问齐，别在文字里连环追问；简单的是非题直接问。\n"
        "用户想反复查看的变化信息（价格、包裹、比分、预算）用 create_panel 放到 Home（已有的面板和卡片用 manage_home 查看、改、删）；定时去做一件事用 schedule_task；用户要“准备今天”/当日简报时先 day_overview 再按技能 prep-my-day 写；发现值得替用户做、但要他点头的事（定时运行里尤其如此）用 offer_on_home 在 Home 放一张建议卡（只有用户本人能做的，如重新连接账号，用 open 直达那一页、不写 prompt）。\n"
        "用户要别人也能看的东西（行程、邀请、菜单、简历）时用 publish_page 做成网页。\n"
        "任务和某个技能匹配时，先 use_skill 读取做法再动手；用户让你记住一套做法时用 save_skill，小改已有技能用 edit_skill。"
    )


settings = Settings()
