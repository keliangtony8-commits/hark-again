// REST 资源的数据模型（字段与 /api/* 返回一致）。
import 'block.dart';

DateTime? _date(dynamic v) => v is String ? DateTime.tryParse(v)?.toLocal() : null;

/// 聊天可选的模型（GET /api/catalog/models）。
class ModelCatalog {
  const ModelCatalog({required this.defaultId, required this.options, this.efforts = const {}, this.autoId, this.routes = const {}});
  factory ModelCatalog.fromJson(Map<String, dynamic> j) {
    final models = [for (final m in (j['models'] as List? ?? const [])) if (m is Map && m['id'] is String) m.cast<String, dynamic>()];
    return ModelCatalog(
      defaultId: j['default'] as String? ?? '',
      options: [for (final m in models) (id: m['id'] as String, label: m['label'] as String? ?? m['id'] as String)],
      efforts: {for (final m in models) m['id'] as String: ?ModelEfforts.fromJson(m)},
      autoId: [for (final m in models) if (m['auto'] == true) m['id'] as String].firstOrNull,
      routes: {
        for (final m in models)
          if (m['auto'] == true && m['routes'] is Map)
            for (final r in (m['routes'] as Map).entries)
              if (r.key is String && r.value is String) r.key as String: r.value as String,
      },
    );
  }

  /// “自动”这一项的 id（后端 model_router；旧服务器 / 关掉了 = null）：每轮由服务器在两档里挑。
  final String? autoId;

  /// 自动的两档：simple / complex → 别名。
  final Map<String, String> routes;

  bool isAuto(String? id) => id != null && id == autoId;

  /// 别名的显示名（不在列表里就原样）。
  String labelOf(String id) {
    for (final o in options) {
      if (o.id == id) return o.label;
    }
    return id;
  }

  /// 模型钮上的字：自动且知道上一轮用了谁 → “自动 · 快速”；否则就是这一项的名字。
  String chipLabel(({String id, String label}) eff, String? routed) =>
      isAuto(eff.id) && routed != null && routed.isNotEmpty ? '${eff.label} · ${labelOf(routed)}' : eff.label;

  /// 选择菜单里“自动”的一行说明：简单的用谁、复杂的用谁。
  String? autoHint() {
    final s = routes['simple'], c = routes['complex'];
    return s == null || c == null ? null : '简单的事用${labelOf(s)}，复杂的用${labelOf(c)}，每轮自动挑';
  }
  final String defaultId;
  final List<({String id, String label})> options;

  /// 能调思考强度的模型 → 档位（后端 reasoning.catalog；旧服务器没有这项 = 都不能调）。
  final Map<String, ModelEfforts> efforts;

  /// 这个模型可选的思考档；不足两档不值得给切换（返回 null）。
  ModelEfforts? effortsFor(String modelId) {
    final e = efforts[modelId];
    return e != null && e.levels.length > 1 ? e : null;
  }

  /// 对话的选择（null = 默认）→ 实际生效的那一项；选的别名已不在列表里也回落到默认（与后端 llm.chat_model 一致）。
  ({String id, String label})? effective(String? alias) {
    for (final id in [?alias, defaultId]) {
      for (final o in options) {
        if (o.id == id) return o;
      }
    }
    return options.isEmpty ? null : options.first;
  }

  /// 用户选了 [id] → 存到对话上的值：选默认就存 null（以后改默认会跟着变）。
  String? toChoice(String id) => id == defaultId ? null : id;

  /// `/model 名字`（v1.89）→ 那一项的 id；认不出 / 对上好几项 → null。
  /// 规则：大小写不敏感、去空白；“默认 / default” = 默认那项；先比 id、名字全等，再比开头（只对上一项才算）。
  String? find(String query) {
    final q = query.trim().toLowerCase();
    if (q.isEmpty) return null;
    if (q == '默认' || q == 'default') return defaultId;
    for (final o in options) {
      if (o.id.toLowerCase() == q || o.label.toLowerCase() == q) return o.id;
    }
    final hits = {for (final o in options) if (o.id.toLowerCase().startsWith(q) || o.label.toLowerCase().startsWith(q)) o.id};
    return hits.length == 1 ? hits.first : null;
  }

  /// 认不出时的那句话：列出可选的名字。
  String findMiss(String query) => '没有叫「${query.trim()}」的模型，可选：${options.map((o) => o.label).join('、')}';

  /// 至少两项才值得给切换。
  bool get selectable => options.length > 1;
}

/// 一档思考强度（low / medium / high …）。
class EffortLevel {
  const EffortLevel(this.id, this.label, [this.description = '']);
  final String id, label, description;
}

/// 一个模型的思考档位（从少到多）+ 默认档。规则与后端 reasoning.resolve 一致。
class ModelEfforts {
  const ModelEfforts(this.levels, this.defaultId);
  static ModelEfforts? fromJson(Map<String, dynamic> m) {
    final raw = m['efforts'];
    if (raw is! List) return null;
    final levels = [
      for (final e in raw)
        if (e is Map && e['id'] is String) EffortLevel(e['id'] as String, e['label'] as String? ?? e['id'] as String, e['description'] as String? ?? ''),
    ];
    if (levels.isEmpty) return null;
    final d = m['effort'];
    return ModelEfforts(levels, levels.any((l) => l.id == d) ? d as String : levels.first.id);
  }

  final List<EffortLevel> levels;
  final String defaultId;

  /// 对话的选择（null = 默认）→ 实际生效的档：这个模型没有那档也回默认（换过模型、改过配置）。
  EffortLevel effective(String? choice) =>
      levels.firstWhere((l) => l.id == choice, orElse: () => levels.firstWhere((l) => l.id == defaultId, orElse: () => levels.first));

  /// 选了 [id] → 存到对话上的值：选默认就存 null（以后改默认会跟着变）。
  String? toChoice(String id) => id == defaultId ? null : id;
}

class ConversationSummary {
  const ConversationSummary({required this.id, required this.title, this.updatedAt, this.pinned = false, this.model, this.reasoning, this.snippet, this.messageId, this.routedModel, this.planMode = false, this.status});
  factory ConversationSummary.fromJson(Map<String, dynamic> j) => ConversationSummary(
    id: j['id'] as String,
    title: j['title'] as String? ?? '新对话',
    updatedAt: _date(j['updated_at']),
    pinned: j['pinned'] as bool? ?? false,
    model: j['model'] as String?,
    reasoning: j['reasoning'] as String?,
    snippet: j['snippet'] as String?,
    messageId: j['message_id'] as String?,
    routedModel: j['routed_model'] as String?,
    planMode: j['mode'] == 'plan',
    status: ConversationStatus.parse(j['status']),
  );
  final String id, title;
  final DateTime? updatedAt;
  final bool pinned;

  /// 服务器自动起了标题（conversation.title 事件）：只换标题，其余照旧。
  ConversationSummary withTitle(String t) => ConversationSummary(
    id: id, title: t, updatedAt: updatedAt, pinned: pinned, model: model, reasoning: reasoning, snippet: snippet, messageId: messageId, routedModel: routedModel, planMode: planMode, status: status);

  /// 这个对话选的聊天模型别名；null = 服务器默认。
  final String? model;

  /// 这个对话选的思考强度；null = 模型默认。
  final String? reasoning;

  /// 计划模式（后端 conversations.mode == plan，app/plan_mode.py）：只看不改，先交方案给你批准。
  final bool planMode;

  /// 选了“自动”时上一轮实际用的别名（后端 conversations.routed_model）。
  final String? routedModel;

  /// 只在搜索结果里有：内容命中处的一小段摘录。
  final String? snippet;

  /// 只在内容命中时有：命中的那条消息（打开后滚过去并闪一下）。
  final String? messageId;

  /// v2.91 §N 项目对话列表的状态（后端 app/conversation_status.py）；主聊天列表、搜索结果、不认识的值 → null（不画胶囊）。
  final ConversationStatus? status;
}

/// 对话状态胶囊的三种值（服务器 status 字段）。
enum ConversationStatus {
  running('进行中'),
  waiting('等你回复'),
  done('已完成');

  const ConversationStatus(this.label);
  final String label;

  static ConversationStatus? parse(Object? v) => switch (v) {
        'running' => running,
        'waiting' => waiting,
        'done' => done,
        _ => null,
      };
}

/// 项目档案最长多少字（和后端 project_brief.BRIEF_MAX 一致）。
const briefMaxChars = 8000;

class Project {
  const Project({
    required this.id,
    required this.name,
    required this.emoji,
    required this.rules,
    this.brief = '',
    this.briefBy,
    this.briefUpdatedAt,
    this.updatedAt,
    this.conversationCount = 0,
    this.lastActiveAt,
  });
  factory Project.fromJson(Map<String, dynamic> j) => Project(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    emoji: j['emoji'] as String? ?? '📁',
    rules: j['rules'] as String? ?? '',
    brief: j['brief'] as String? ?? '',
    briefBy: j['brief_by'] as String?,
    briefUpdatedAt: _date(j['brief_updated_at']),
    updatedAt: _date(j['updated_at']),
    conversationCount: (j['conversation_count'] as num?)?.toInt() ?? 0,
    lastActiveAt: _date(j['last_active_at']),
  );
  final String id, name, emoji, rules;
  final DateTime? updatedAt;

  /// 项目档案（Markdown 活文档，用户和助手都能改）；briefBy = 最后一次谁改的：user | assistant（老服务端没有 → 空）。
  final String brief;
  final String? briefBy;
  final DateTime? briefUpdatedAt;

  /// 档案里第一行正文（跳过标题和空行），给列表卡片当副标题。
  String get briefLine {
    for (final l in brief.split('\n')) {
      final t = l.trim().replaceFirst(RegExp(r'^([-*+]|\d+\.)\s+'), '');
      if (t.isNotEmpty && !t.startsWith('#')) return t;
    }
    return '';
  }

  /// 服务端算的只读字段（老服务端没有 → 0 / null，卡片退回用 updatedAt）。
  final int conversationCount;
  final DateTime? lastActiveAt;

  DateTime? get activeAt => lastActiveAt ?? updatedAt;
}

class MemoryItem {
  const MemoryItem({required this.id, required this.content, required this.category, this.updatedAt});
  factory MemoryItem.fromJson(Map<String, dynamic> j) => MemoryItem(
    id: j['id'] as String,
    content: j['content'] as String? ?? '',
    category: j['category'] as String? ?? 'general',
    updatedAt: _date(j['updated_at']),
  );
  final String id, content, category;
  final DateTime? updatedAt;
}

class ScheduledTask {
  const ScheduledTask({
    required this.id,
    required this.name,
    required this.prompt,
    required this.cron,
    required this.active,
    required this.output,
    required this.runRequested,
    this.lastRunAt,
    this.lastStatus,
    this.failStreak = 0,
    this.pausedReason,
    this.nextRunAt,
    this.runAt,
    this.done = false,
    this.model,
    this.reasoning,
    this.kind = 'agent',
    this.notify = 'failure',
    this.projectId,
    this.runbook,
    this.note,
    this.skippedAt,
    this.wallLabel,
    this.wallReason,
    this.wallFixable = false,
    this.wallOpen,
    this.wallRetrying = false,
  });
  factory ScheduledTask.fromJson(Map<String, dynamic> j) => ScheduledTask(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    prompt: j['prompt'] as String? ?? '',
    cron: j['cron'] as String? ?? '',
    active: j['active'] as bool? ?? true,
    output: j['output'] as String? ?? 'report',
    runRequested: j['run_requested'] as bool? ?? false,
    lastRunAt: _date(j['last_run_at']),
    lastStatus: j['last_status'] as String?,
    failStreak: (j['fail_streak'] as num?)?.toInt() ?? 0,
    pausedReason: j['paused_reason'] as String?,
    nextRunAt: _date(j['next_run_at']),
    runAt: _date(j['run_at']),
    done: j['done'] as bool? ?? false,
    model: j['model'] as String?,
    reasoning: j['reasoning'] as String?,
    kind: j['kind'] as String? ?? 'agent',
    notify: j['notify'] as String? ?? 'failure',
    projectId: j['project_id'] as String?,
    runbook: _line(j['runbook']),
    note: _line(j['note']),
    skippedAt: _date(j['skipped_at']),
    wallLabel: _line(j['wall_label']),
    wallReason: _line(j['wall_reason']),
    wallFixable: j['wall_fixable'] as bool? ?? false,
    wallOpen: _line(j['wall_open']),
    wallRetrying: j['wall_retrying'] as bool? ?? false,
  );
  final String id, name, prompt, cron, output;

  /// v2.15 碰壁（后端 app/task_wall.py）：最近一次运行碰到的障碍，一句话（“需要登录 jw.example.edu”）+ 经过；没碰壁 = null。
  /// 只用服务端给的这几个字段，不自己解析壁的字符串。
  final String? wallLabel, wallReason;

  /// 要你处理（登录 / 重新连接 / 付费墙）才 true；验证码、页面改版这类它会自己再试。
  final bool wallFixable;

  /// 去哪一页处理（'vault' / 'connectors'；cardTargets 的键），没有 = null。
  final String? wallOpen;

  /// v2.19 修好就重跑：你刚存了对应的登录 / 连好了连接器（或点了重试），重跑已经排上、还没跑完。
  final bool wallRetrying;
  bool get walled => wallLabel != null;

  /// v2.13 助手自己记下的做法（第一次运行写）与观察（之后滚动改）；每次运行开头都读到（后端 app/task_brief.py）。没有 = null。
  final String? runbook, note;

  /// 被“跳过下一次”的那次计划时刻（还没到的才有）；nextRunAt 已经是它之后的那次。
  final DateTime? skippedAt;

  /// 'agent' = 到点交给助手（prompt 是指令）；'script' = 定时脚本（prompt 是 shell 命令，到点直接在工作区跑，不调模型）。建好不改。
  final String kind;

  /// 定时脚本什么时候告诉你：'failure' 只在失败时 / 'always' 每次 / 'change' 输出变了（文案见 task_labels.dart notifyLabels）。
  final String notify;

  /// 定时脚本在哪个项目的工作区跑（null = 我的文件）。
  final String? projectId;

  /// 每次运行用的模型别名 / 思考强度（null = 默认；规则同对话：ModelCatalog.effective / ModelEfforts.effective）。
  final String? model, reasoning;
  final bool active, runRequested;
  final DateTime? lastRunAt;

  /// 上一次结束的运行：'ok' | 'error'；没跑过 = null。
  final String? lastStatus;

  /// 连着失败了几次（成功归零）。服务端连续失败 3 次会把重复任务自动暂停（pausedReason = 'failures'）。
  final int failStreak;

  /// 'failures' = 连续失败被自动暂停；用户手动停的 = null。
  final String? pausedReason;

  /// 服务端按 cron 算好的下次运行（与 worker 同一套计算，只读）；停用或 cron 无效 = null。
  final DateTime? nextRunAt;

  /// 一次性任务的时刻（与 cron 二选一，cron 为空串）；重复任务 = null。
  final DateTime? runAt;

  /// 一次性任务已经跑过（服务端算好，只读）。
  final bool done;
  bool get isOnce => runAt != null;
  bool get isPanel => output == 'panel';
  bool get isScript => kind == 'script';

  /// v2.55 记录面板（服务端 app/panel_log.py）：在聊天里说一句就记一笔，内容按记下的笔算，不调模型；只能改标题。
  bool get isLog => kind == 'log';

  /// 到点交给模型的任务（定时脚本、记录面板都不调模型：没有模型 / 做法可选）。
  bool get usesModel => !isScript && !isLog;
  bool get lastFailed => lastStatus == 'error';
  bool get autoPaused => !active && pausedReason == 'failures';

  /// 任务自己运行时按指令结束了自己（服务端 task_brief.ENDED：停用不删除；打开开关即恢复）。
  bool get ended => !active && pausedReason == 'ended';

  /// 能跳过下一次：重复任务、开着（一次性的取消或改时间就行）。
  bool get canSkip => !isLog && !isOnce && active && nextRunAt != null;
}

/// 定时任务的一次运行（GET /api/tasks/{id}/runs，新的在前）。
class TaskRun {
  const TaskRun({
    required this.id,
    required this.trigger,
    required this.status,
    this.error,
    this.conversationId,
    this.startedAt,
    this.finishedAt,
    this.durationMs,
    this.jobId,
    this.silentReason,
    this.wallLabel,
  });
  factory TaskRun.fromJson(Map<String, dynamic> j) => TaskRun(
    id: j['id'] as String,
    trigger: j['trigger'] as String? ?? 'schedule',
    status: j['status'] as String? ?? 'ok',
    error: j['error'] as String?,
    conversationId: j['conversation_id'] as String?,
    startedAt: _date(j['started_at']),
    finishedAt: _date(j['finished_at']),
    durationMs: (j['duration_ms'] as num?)?.toInt(),
    jobId: j['job_id'] as String?,
    silentReason: j['silent_reason'] as String?,
    wallLabel: _line(j['wall_label']),
  );

  /// v2.15 这次碰的壁（一句话）；error 里是“壁：经过”。没碰壁 = null。
  final String? wallLabel;
  bool get walled => failed && wallLabel != null;

  /// 这次没东西可报、没打扰你的一句原因（不进收件箱，对话仍可点开）；说了话 = null。
  final String? silentReason;
  bool get silent => !failed && silentReason != null;
  final String id, trigger, status;

  /// 定时脚本这次跑的后台任务（没告诉你、所以没开对话时，点这一行看它的日志）。
  final String? jobId;
  final String? error;

  /// 报告任务那次的对话；面板任务、或对话已被删 → null（不可点开）。
  final String? conversationId;
  final DateTime? startedAt, finishedAt;
  final int? durationMs;
  bool get running => status == 'running';
  bool get failed => status == 'error';
  bool get manual => trigger == 'manual';
}

String? _webUrl(Object? v) => v is String && (v.startsWith('https://') || v.startsWith('http://')) ? v : null;

/// 一行字段：去首尾空白，空串当没有。
String? _line(Object? v) => v is String && v.trim().isNotEmpty ? v.trim() : null;

class HomeCard {
  const HomeCard({
    required this.id,
    required this.kind,
    required this.title,
    required this.blocks,
    this.actionPrompt,
    this.conversationId,
    this.taskId,
    this.target,
    this.actionLabel,
    this.origin,
    this.imageUrl,
    this.linkUrl,
    this.headline,
    this.gist,
    required this.dismissed,
    this.unread = false,
    this.updatedAt,
    this.snoozedUntil,
    this.removedAt,
    this.revivable = false,
  });
  factory HomeCard.fromJson(Map<String, dynamic> j) => HomeCard(
    id: j['id'] as String,
    kind: j['kind'] as String? ?? 'action',
    title: j['title'] as String? ?? '',
    blocks: blocksFrom(j['blocks']),
    actionPrompt: j['action_prompt'] as String?,
    conversationId: j['conversation_id'] as String?,
    taskId: j['task_id'] as String?,
    target: j['target'] as String?,
    actionLabel: j['action_label'] as String?,
    origin: j['origin'] as String?,
    imageUrl: _webUrl(j['image_url']),
    linkUrl: _webUrl(j['link_url']),
    headline: _line(j['headline']),
    gist: _line(j['gist']),
    dismissed: j['dismissed'] as bool? ?? false,
    unread: j['unread'] as bool? ?? false,
    updatedAt: _date(j['updated_at']),
    snoozedUntil: _date(j['snoozed_until']),
    removedAt: _date(j['removed_at']),
    revivable: j['revivable'] as bool? ?? false,
  );
  final String id, kind, title;
  final List<Block> blocks;
  final String? actionPrompt, conversationId, taskId;

  /// 客户端里的去处（'usage' = 用量页，`project:<id>` = 某个项目…），见 features/home/action_card.dart 的 cardTargets。
  final String? target;

  /// 主按钮上的字（服务端空 = “去做”），用 [actionText]。
  final String? actionLabel;

  /// 谁放的卡：'agent' = 助手提议替你做的事（点主按钮后收起，见 backend app/home_offers.py）；空 = 系统提醒。
  final String? origin;
  bool get offered => origin == 'agent';

  /// 助手提议的卡已被点过：服务端开了对话并记在卡上（POST /api/cards/{id}/start），卡变成“已交给助手 · 查看对话”。
  bool get started => offered && conversationId != null;
  String get actionText => (actionLabel ?? '').trim().isEmpty ? '去做' : actionLabel!.trim();

  /// 建议卡的卡顶配图 / 原页链接（只认 http(s)，其余当没有）。
  final String? imageUrl, linkUrl;

  /// 原页的域名（去掉 www.），卡上写“来源 · 域名”；没有链接为 null。
  String? get linkHost {
    final h = linkUrl == null ? '' : (Uri.tryParse(linkUrl!)?.host ?? '');
    return h.isEmpty ? null : (h.startsWith('www.') ? h.substring(4) : h);
  }

  /// 报告卡的“一眼”：摘要卡标题 + 一句话（服务端 app/report_gist.py 投递时取出；老服务器没有）。用 [glance]。
  final String? headline, gist;

  /// 收件箱行的副标题：`headline · gist`；都没有（老服务器 / 老卡）就退回正文纯文本，去掉 Markdown 记号，截 80 字。
  String get glance {
    final parts = [?headline, ?gist];
    if (parts.isNotEmpty) return parts.join(' · ');
    final t = plainText(blocks).replaceAll(RegExp(r'[#*_`>|-]'), '').replaceAll(RegExp(r'\s+'), ' ').trim();
    return t.isEmpty ? '点开查看结果' : (t.length > 80 ? '${t.substring(0, 80)}…' : t);
  }

  final bool dismissed, unread;
  final DateTime? updatedAt;

  /// 稍后提醒到这个时刻（本地时间）。非空就先不显示；到点由服务端放回（清空 + 重新未读），客户端不比本机时钟。
  final DateTime? snoozedUntil;
  bool get snoozed => snoozedUntil != null;

  /// v2.17 从 Home 移除的面板：移除时刻 + 还能不能找回（服务端 app/panel_trash.py 判定，30 天内；客户端只认 [revivable]）。
  final DateTime? removedAt;
  final bool revivable;
}

/// GET /api/inbox：未读数 + 最新一条未读（轮询用的轻量摘要）。
class InboxSummary {
  const InboxSummary({this.unread = 0, this.latest});
  factory InboxSummary.fromJson(Map<String, dynamic> j) =>
      InboxSummary(unread: j['unread'] as int? ?? 0, latest: j['latest'] == null ? null : InboxItem.fromJson(j['latest'] as Map<String, dynamic>));
  final int unread;
  final InboxItem? latest;

  /// 相对上一次是不是“来了新的”：最新一条换了且未读数变多。只读掉/忽略不算。
  bool hasNewSince(InboxSummary prev) => latest != null && latest!.id != prev.latest?.id && unread > prev.unread;

  bool sameAs(InboxSummary o) => unread == o.unread && latest?.id == o.latest?.id;
}

class InboxItem {
  const InboxItem({required this.id, required this.kind, required this.title, this.conversationId, this.headline, this.gist});
  factory InboxItem.fromJson(Map<String, dynamic> j) => InboxItem(
    id: j['id'] as String,
    kind: j['kind'] as String? ?? 'report',
    title: j['title'] as String? ?? '',
    conversationId: j['conversation_id'] as String?,
    headline: _line(j['headline']),
    gist: _line(j['gist']),
  );
  final String id, kind, title;
  final String? conversationId;

  /// 报告的“一眼”（见 [HomeCard.glance]）；横幅第二行 = [glance]，都没有为 null（横幅只显示标题）。
  final String? headline, gist;
  String? get glance {
    final parts = [?headline, ?gist];
    return parts.isEmpty ? null : parts.join(' · ');
  }
}

/// 技能。[builtin] 内置原样（只读）；[customized] 是内置的自定义版（同 id 顶替内置，可改、可恢复默认）；
/// 两者都 false 就是用户自己写的（可删）。老服务器没有 customized = false。
class Skill {
  const Skill({
    required this.id,
    required this.name,
    required this.description,
    required this.body,
    required this.builtin,
    this.customized = false,
    this.enabled = true,
  });
  factory Skill.fromJson(Map<String, dynamic> j) => Skill(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    description: j['description'] as String? ?? '',
    body: j['body'] as String? ?? '',
    builtin: j['builtin'] as bool? ?? false,
    customized: j['customized'] as bool? ?? false,
    enabled: j['enabled'] as bool? ?? true,
  ); // 旧服务器没有开关 = 全启用
  final String id, name, description, body;
  final bool builtin, customized;

  /// 停用的技能留在库里，但模型看不到、用不了。
  final bool enabled;

  /// 出身是内置（原样或自定义版）：列在“内置”分组，不能删除。
  bool get fromBuiltin => builtin || customized;
}

/// 保险箱条目（脱敏）：服务器永不返回明文，只有 preview。
class SecretItem {
  const SecretItem({required this.id, required this.kind, required this.name, this.username, required this.hosts, required this.preview, this.retriedNote, this.queryParam, this.headerName = 'Authorization'});
  factory SecretItem.fromJson(Map<String, dynamic> j) => SecretItem(
    id: j['id'] as String,
    kind: j['kind'] as String? ?? 'api_key',
    name: j['name'] as String? ?? '',
    username: j['username'] as String?,
    hosts: [for (final h in j['hosts'] as List? ?? const []) '$h'],
    preview: j['preview'] as String? ?? '',
    retriedNote: j['retried_note'] as String?,
    queryParam: j['query_param'] as String?,
    headerName: j['header_name'] as String? ?? 'Authorization',
  );
  final String id, kind, name, preview;

  /// v2.52 API Key 怎么带上：给了 = 放网址参数 ?queryParam=；否则放请求头 [headerName]（后端 app/api_keys.py）。
  final String? queryParam;
  final String headerName;

  /// v2.19 只在新建的响应里有：因为这条登录而重跑的碰壁任务那句话（后端 task_wall.retry_note），没有 = null。
  final String? retriedNote;
  final String? username;
  final List<String> hosts;
  bool get isLogin => kind == 'login';
  /// 命令环境变量：name 就是变量名，没有域名（后端 app/command_env.py）。
  bool get isEnv => kind == 'env';
}

/// OAuth 连接器（Google、GitHub…）。id 就是 provider。
/// 只认服务器给的 [status] + [setup]（判定在后端 app/connector_accounts.py）；旧字段 configured 不读（v2.90.2）。
class Connector {
  const Connector({required this.id, required this.name, required this.desc, required this.status, this.account, this.setup});
  factory Connector.fromJson(Map<String, dynamic> j) => Connector(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    desc: j['desc'] as String? ?? '',
    account: j['account'] as String?,
    // 没有 status 的服务器（v2.36 之前）已不存在；万一缺了：有账户 = 已连接，否则按“没配”处理——宁可不显示，也不给一颗点了会失败的按钮
    status: j['status'] as String? ?? (j['account'] != null ? 'connected' : 'unconfigured'),
    setup: j['setup'] is Map<String, dynamic> ? ConnectorSetup.fromJson(j['setup'] as Map<String, dynamic>) : null,
  );
  final String id, name, desc;
  final String? account;

  /// connected | expired | available | unconfigured。
  final String status;

  /// v2.90.2 服务器没配这个 OAuth 应用时给部署者的引导；配好了 = null。
  final ConnectorSetup? setup;

  /// 有账户（含授权失效的）。
  bool get connected => account != null;
  bool get expired => status == 'expired';

  /// 连接器页显示这一行：没配又没连过的不显示（v2.90.2：不给“看起来能点、点了失败”的东西）。
  bool get shown => status != 'unconfigured';

  /// 现在点“连接 / 重新连接”真能走通：服务器配好了这个应用。
  bool get authorizable => setup == null && status != 'unconfigured';
}

/// 服务器还差的那一步（GET /api/connectors 每项的 setup）：去哪注册应用、回调地址、.env 里要填的变量名。
class ConnectorSetup {
  const ConnectorSetup({required this.console, required this.callback, required this.env});
  factory ConnectorSetup.fromJson(Map<String, dynamic> j) => ConnectorSetup(
    console: j['console'] as String? ?? '',
    callback: j['callback'] as String? ?? '',
    env: [for (final e in (j['env'] as List? ?? const [])) '$e'],
  );
  final String console, callback;
  final List<String> env;
}

class McpServerItem {
  const McpServerItem({required this.id, required this.name, required this.url, required this.hasToken, this.problem, this.retriedNote});
  factory McpServerItem.fromJson(Map<String, dynamic> j) => McpServerItem(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    url: j['url'] as String? ?? '',
    hasToken: j['has_token'] as bool? ?? false,
    problem: j['problem'] as String?,
    retriedNote: j['retried_note'] as String?,
  );
  final String id, name, url;
  final bool hasToken;

  /// v2.19 只在新建的响应里有：因为连上它而重跑的碰壁任务那句话，没有 = null。
  final String? retriedNote;

  /// 还没恢复的问题："auth"（令牌被拒）| "down"（连不上）| null（老服务器不给 = 没问题）。规则见后端 connectors/mcp.py。
  final String? problem;

  /// 行上的那句话；不认识的值当没有。
  String? get problemText => switch (problem) { 'auth' => '令牌被拒绝', 'down' => '无法连接', _ => null };
}

class PageItem {
  const PageItem({required this.id, required this.title, required this.url, this.updatedAt, this.published = true});
  factory PageItem.fromJson(Map<String, dynamic> j) => PageItem(
    id: j['id'] as String,
    title: j['title'] as String? ?? '',
    url: j['url'] as String? ?? '',
    updatedAt: j['updated'] is num ? DateTime.fromMillisecondsSinceEpoch(((j['updated'] as num) * 1000).round()) : null,
    published: j['published'] != false,
  ); // 老服务器没有此字段 = 已发布
  final String id, title, url;
  final DateTime? updatedAt;

  /// false = 已下线：链接暂时打不开（文件还在，重新发布后同一链接恢复）
  final bool published;
}

/// 对话的分享状态（GET/POST/DELETE /api/conversations/{id}/share）。
/// page == null：从没分享过；page 有但 shared == false：停止分享了（链接保留，再分享原链接恢复）。
/// stale：快照之后对话又有新内容。
class ConversationShare {
  const ConversationShare({this.page, this.shared = false, this.stale = false});
  factory ConversationShare.fromJson(Map<String, dynamic> j) => ConversationShare(
        page: j['slug'] is String ? PageItem.fromJson(j) : null,
        shared: j['shared'] == true,
        stale: j['stale'] == true,
      );
  final PageItem? page;
  final bool shared, stale;
}

class ProjectFile {
  const ProjectFile({required this.path, required this.name, required this.size, required this.mime, this.modified});
  factory ProjectFile.fromJson(Map<String, dynamic> j) => ProjectFile(
    path: j['path'] as String,
    name: j['name'] as String? ?? '',
    size: j['size'] as int? ?? 0,
    mime: j['mime'] as String? ?? '',
    modified: switch (j['modified']) {
      final num t => DateTime.fromMillisecondsSinceEpoch((t * 1000).round()),
      _ => null,
    },
  );
  final String path, name, mime;
  final int size;

  /// 最后修改时间（后端给 Unix 秒；老服务端没有 → null）。
  final DateTime? modified;
}
