// 聊天状态的唯一归属地（对应网页版 useChat）。
// 把服务器事件流折叠成消息列表；界面只读 ChatState、只调 open/send/replyApproval/replyForm。
// family 参数：'' = 主聊天；项目 id = 该项目里的聊天。
// 离线：先显示 chat_cache 里的上次内容（瞬开），再向服务器要新的；连不上就留着缓存并标 offline，界面给“离线”条。
// 发件箱：发出的消息先作为 Outbox.queued 进列表；线通了就真正发出（sent），一次只在飞一条。
//   没连上等太久 → failed；发出后、回复开始前断线 → failed（服务器可能没收到；连上后问一次，服务器那边正在答就改回已发出）。
// 续传（v1.61，服务器 live_turns）：回答不绑在连接上。回复中途断线 → 生成中的那条和 streaming 都留着，
//   连上后发 turn.resume {turn_id, after: 收到的最后一个 seq}，服务器只补后面的；事件带 turn_id + seq，重复的丢掉。
//   游标太旧（服务器日志已截断）→ turn.snapshot 整份替换生成中的那条；服务器说没这轮了（重启 / 已过保留期）→ 以 GET 为准。
//   打开对话（和每次重连）都问一次 turn.resume {conversation_id}：别的设备 / 断线前发起、还在写的回答接着看。
//   老服务器不带 turn_id：按旧规则（断线丢半截、连上后 GET）。
//   failed 由用户 resend()（挪到末尾重新排队）或 discard()。
//   未发出的消息按对话存进 chat_cache 的发件箱（listenSelf 一处写，不在各个分支里散写），
//   切走/App 被杀后再打开这个对话会以“发送失败”回来。
// 停止：生成中 stop() 发 message.cancel，等服务器回 message.done（半截回复，stopped）或 message.stopped（还没吐字）
//   再收尾——不在本地先砍，界面和服务器落库的内容始终一致。stopping 期间停止键置灰防连点。
// 重新生成：只针对最后一条回复（或上一轮失败、没有回复时的“重试”）。不排队——线不通直接提示；
//   先在本地撤掉旧回复（立刻看到思考动画），服务器拒绝或中途断线就重新拉对话，把真实状态拿回来。
// 编辑：只针对最后一条用户消息（editableId），= 带新文字的重新生成：本地先改气泡、撤掉后面的回复，
//   message.start 带回服务器版本（user_message）再覆盖一次；附件保留，本地 id 不变（列表不重建）。
// 定位：搜索命中正文时 open(id, focus: 消息 id)。focus 是一次性请求，ChatView 等那条消息出现在列表里就 takeFocus()
//   取走、滚过去并闪一下；服务器版本拉回来仍找不到（已被删/重新生成）就静默作废。
// 模型：ChatState.model = 这个对话选的别名（null = 默认），打开时先取列表里的、再以服务器详情为准。
//   setModel() 先改本地；已有对话立刻 PATCH，没成功（断网）或还是新对话就记 _modelDirty，
//   随下一条 user.message / message.regenerate 带上 model（"" = 回默认）——所以“切到深度再点重新生成”= 换模型重答。
// 途中补充（v1.83，服务器 steering）：生成中再发纯文字 = 补充给正在进行的这一轮（user.message 带 steer + client_id），
//   气泡立刻插在生成中那条前面；服务器收下回 turn.steered（client_id 认领本地气泡）；插不进（刚好答完）就排成下一轮，
//   那一轮的 message.start 带回 client_id，气泡挪到末尾、去掉“补充”标记。别的设备补充的从 turn.steered / 快照里补上。
//   思考强度（ChatState.effort，null = 模型默认）和模型是同一份“模型选择”：setEffort 走同一条路（同一个 dirty 标记、一起带上）。
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/chat_socket.dart';
import '../../core/resource.dart';
import '../../models/activity.dart';
import '../../models/block.dart';
import '../../models/export.dart';
import '../../models/message.dart';
import '../../models/resources.dart';
import '../../models/retry_notice.dart';
import '../../theme/tokens.dart';
import 'chat_cache.dart';

class ChatState {
  const ChatState(
      {this.conversations = const [],
      this.activeId,
      this.messages = const [],
      this.streaming = false,
      this.stopping = false,
      this.error,
      this.offline = false,
      this.linkDown = false,
      this.focus,
      this.model,
      this.effort,
      this.routed,
      this.planMode = false});
  final List<ConversationSummary> conversations;
  final String? activeId;
  final List<Message> messages;
  final bool streaming;

  /// 已请求停止，等服务器收尾。
  final bool stopping;
  final String? error;

  /// 上一次同步没连上服务器，正在显示缓存。
  final bool offline;

  /// 聊天长连接断了（重连中）。
  final bool linkDown;

  /// 待定位的消息（一次性，见 takeFocus）。
  final String? focus;

  /// 当前对话选的模型别名；null = 服务器默认。
  final String? model;

  /// 当前对话选的思考强度；null = 模型默认（后端 reasoning.resolve）。
  final String? effort;

  /// 选了“自动”时这一轮 / 上一轮服务器实际用的别名（turn.model 事件、对话详情 routed_model）；模型钮显示“自动 · 快速”。
  final String? routed;

  /// 当前对话在计划模式（v1.71，后端 app/plan_mode.py）：助手只看不改，先交方案给你批准。和模型同属“模型选择”，同一条路送到服务器。
  final bool planMode;

  /// 输入框是否该等：在生成，或有一条在排队（一次只排一条，避免新对话被拆成几段）。
  bool get busy => streaming || messages.any((m) => m.outbox == Outbox.queued);

  /// 停止键可点：在生成且还没请求过停止。
  bool get canStop => streaming && !stopping;

  /// 生成中能不能补一句给这一轮（服务器 steering；新对话的第一轮还没有 id 时不行）。
  bool get canSteer => streaming && !stopping && activeId != null;

  /// 能否“重新生成”：最后一条是已落库的回复，或是已发出却没等到回复的用户消息（上一轮失败 → 重试）。
  bool get canRegenerate =>
      !busy && activeId != null && messages.isNotEmpty && !messages.last.pending && !messages.last.unsent;

  /// 能编辑的那条用户消息：最后一条用户消息，已在服务器上，且没在生成（条件同 canRegenerate）。
  String? get editableId {
    if (!canRegenerate) return null;
    final i = messages.lastIndexWhere((m) => m.isUser);
    return i < 0 ? null : messages[i].id;
  }

  /// 离线条：拉不到数据或连不上长连接，都算。
  bool get showOffline => offline || linkDown;

  ChatState copyWith(
          {List<ConversationSummary>? conversations,
          String? Function()? activeId,
          List<Message>? messages,
          bool? streaming,
          bool? stopping,
          String? Function()? error,
          bool? offline,
          bool? linkDown,
          String? Function()? focus,
          String? Function()? model,
          String? Function()? effort,
          String? Function()? routed,
          bool? planMode}) =>
      ChatState(
        conversations: conversations ?? this.conversations,
        activeId: activeId != null ? activeId() : this.activeId,
        messages: messages ?? this.messages,
        streaming: streaming ?? this.streaming,
        // 一轮结束（streaming 变 false）自动清掉 stopping，免得各个收尾分支各写一遍
        stopping: (streaming ?? this.streaming) && (stopping ?? this.stopping),
        error: error != null ? error() : this.error,
        offline: offline ?? this.offline,
        linkDown: linkDown ?? this.linkDown,
        focus: focus != null ? focus() : this.focus,
        model: model != null ? model() : this.model,
        effort: effort != null ? effort() : this.effort,
        routed: routed != null ? routed() : this.routed,
        planMode: planMode ?? this.planMode,
      );
}

class ChatController extends Notifier<ChatState> {
  ChatController(this.projectId);
  final String projectId;
  StreamSubscription<Map<String, dynamic>>? _sub;
  StreamSubscription<LinkStatus>? _statusSub;
  Timer? _giveUp; // 排队消息的放弃计时
  bool _started = false; // 在飞的这条已收到 message.start
  bool _resync = false; // 断线丢了中途的事件，连上后要重新拉当前对话
  bool _regenerating = false; // 在飞的这一轮是重新生成（用户消息早已在服务器上）
  bool _modelDirty = false; // 本机改了模型 / 思考强度还没送到服务器（新对话 / PATCH 没成功）
  String? _turnId; // 在看的这一轮（服务器 live_turns 的 id；老服务器没有）
  String? _turnConv; // 这一轮属于哪个对话（续传时带上，服务器核对）
  int _seq = 0; // 这一轮收到的最后一个事件编号
  bool _reattach = false; // 回复中途断线、服务器支持续传：连上后 turn.resume 接着收
  String? _probe; // 发出后、回复前断线的那个对话：连上后问服务器是不是已经在答
  int _openSeq = 0; // 快速连点切换对话时，只认最后一次 open 的结果

  Api get _api => ref.read(apiProvider);
  ChatSocket get _socket => ref.read(chatSocketProvider);
  ChatCache get _cache => ref.read(chatCacheProvider);

  @override
  ChatState build() {
    final socket = ref.watch(chatSocketProvider);
    _sub = socket.events.listen(_onEvent);
    _statusSub = socket.status.listen(_onLink);
    listenSelf(_saveOutbox);
    ref.onDispose(() {
      _sub?.cancel();
      _statusSub?.cancel();
      _giveUp?.cancel();
    });
    Future.microtask(_start);
    return ChatState(linkDown: socket.current == LinkStatus.down);
  }

  /// 先摆出缓存的列表（打开就有东西看），再去服务器刷新。
  Future<void> _start() async {
    final cached = await _cache.conversations(projectId);
    if (cached != null && state.conversations.isEmpty) {
      state = state.copyWith(conversations: [for (final j in cached) ConversationSummary.fromJson(j)]);
    }
    if (state.activeId == null && state.messages.isEmpty) {
      final restored = await _cache.outbox(projectId, null);
      if (restored.isNotEmpty && state.activeId == null && state.messages.isEmpty) state = state.copyWith(messages: restored);
    }
    await refreshList();
  }

  /// 发件箱持久化：同一个对话里未发出的消息（id + 状态）一变就整份写。
  /// 换对话那一步（activeId 变了）是在装载别的对话，不写；新对话拿到 id 时它的消息已经发出，也无需搬家。
  void _saveOutbox(ChatState? prev, ChatState next) {
    if (prev == null || prev.activeId != next.activeId) return;
    String sig(ChatState s) => [for (final m in s.messages) if (m.unsent) '${m.id}:${m.outbox.name}'].join(',');
    if (sig(prev) == sig(next)) return;
    unawaited(_cache.putOutbox(projectId, next.activeId, [for (final m in next.messages) if (m.unsent) m]));
  }

  /// 对话列表（置顶在前，后端排好序）；[query] 不为空时按标题和内容搜索。返回服务器原样 JSON。
  Future<List<dynamic>> _list([String query = '']) async {
    final params = {if (projectId.isNotEmpty) 'project_id': projectId, if (query.isNotEmpty) 'q': query};
    final path = Uri(path: '/api/conversations', queryParameters: params.isEmpty ? null : params).toString();
    return await _api.get(path) as List;
  }

  static List<ConversationSummary> _summaries(List<dynamic> raw) =>
      [for (final j in raw) ConversationSummary.fromJson(j as Map<String, dynamic>)];

  static List<Message> _messages(List<dynamic> raw) => [for (final m in raw) Message.fromJson(m as Map<String, dynamic>)];

  /// 刷新列表并写缓存；断网时保留现有列表、标记离线（不抛错，后台调用没人接）。
  Future<void> refreshList() async {
    try {
      final raw = await _list(); // 先等结果再读 state：写成 state.copyWith(await …) 会用到等待前的旧 state
      state = state.copyWith(conversations: _summaries(raw), offline: false);
      unawaited(_cache.putConversations(projectId, raw));
    } on ApiError catch (e) {
      if (!e.isNetwork) rethrow;
      state = state.copyWith(offline: true);
    }
  }

  /// 搜索结果不进 state，也不进缓存（只是临时视图）；离线时搜不了，由界面显示错误。
  Future<List<ConversationSummary>> search(String query) async => _summaries(await _list(query.trim()));

  /// “离线”条上的重试：列表和当前对话一起重新同步。
  Future<void> sync() async {
    _socket.reconnectNow();
    await refreshList();
    final id = state.activeId;
    if (id != null && !state.streaming) await _fetch(id, _openSeq);
  }

  /// 服务器在当前对话里自己说了话（后台任务结束后接着说的一轮）：静默拿一次服务器版本。正在生成时不打断。
  Future<void> refreshActive() async {
    final id = state.activeId;
    if (id != null && !state.streaming) await _fetch(id, _openSeq);
  }

  /// 只改正在生成的那条。
  void _patchPending(Message Function(Message) fn) {
    final ms = state.messages;
    if (ms.isEmpty || !ms.last.pending) return;
    state = state.copyWith(messages: [...ms.sublist(0, ms.length - 1), fn(ms.last)]);
  }

  List<Block> _setAt(List<Block> blocks, int i, Block b) {
    final out = [...blocks];
    if (i < out.length) {
      out[i] = b;
    } else {
      out.add(b);
    }
    return out;
  }

  void _onEvent(Map<String, dynamic> e) {
    // 续传去重：同一轮里编号不大于已收到的，是重连补发的重复（message.start / 快照在各自分支里认领新一轮）
    // turn.resumed 是对续传请求的答复（它的 seq = 服务器当前进度），不是这一轮的事件，不参与
    final tid = e['turn_id'], seq = e['seq'];
    if (tid is String && seq is int && tid == _turnId && e['type'] != 'turn.resumed') {
      if (seq <= _seq) return;
      if (e['type'] != 'turn.snapshot') _seq = seq;
    }
    // 模型又开始产出：普通重试的提示收起（换备用模型的提示留到这一轮结束）
    if (RetryNotice.clearsOn.contains(e['type'])) {
      final last = state.messages.lastOrNull;
      if (last != null && last.pending && last.retry != null && !last.retry!.isFallback) _patchPending((m) => m.copyWith(retry: () => null));
    }
    switch (e['type']) {
      case 'message.start':
        if (state.activeId != null && state.activeId != e['conversation_id']) return; // 别的会话的事件
        _started = true;
        if (tid is String && tid != _turnId) {
          _turnId = tid;
          _seq = seq is int ? seq : 0;
        }
        _turnConv = e['conversation_id'] as String?;
        // 旁观（另一台设备发起的重新生成）：被替换的旧回复本机还在，按服务器说的撤掉
        final replaced = {...?(e['replaced'] as List?)?.whereType<String>()};
        final ms = [for (final m in state.messages) if (!replaced.contains(m.id) && !m.pending) m];
        // 想插进上一轮却排成了新一轮的那句（client_id）：挪到末尾、不再标“补充”
        if (e['client_id'] case final String local) {
          final i = ms.indexWhere((m) => m.id == local);
          if (i >= 0) ms.add(ms.removeAt(i).copyWith(steer: false, outbox: Outbox.sent));
        }
        // 编辑：用服务器规整后的版本覆盖本地乐观改写（保留本地 id，气泡不重建）
        if (e['user_message'] case final Map<String, dynamic> um) {
          final i = ms.lastIndexWhere((m) => m.isUser);
          if (i >= 0) ms[i] = ms[i].copyWith(blocks: Message.fromJson(um).blocks);
        }
        state = state.copyWith(
          activeId: () => e['conversation_id'] as String,
          streaming: true,
          messages: [...ms, const Message(id: 'pending', role: 'assistant', blocks: [], pending: true)],
        );
      case 'turn.resumed':
        _onResumed(e);
      case 'turn.snapshot':
        // 游标落在服务器已丢弃的日志里：拿折叠好的“到目前为止”整份替换生成中的那条，再接实时事件
        if (state.activeId != null && e['conversation_id'] != null && state.activeId != e['conversation_id']) return;
        _turnId = tid as String?;
        _seq = seq is int ? seq : 0;
        _started = true;
        final snap = e['message'] as Map<String, dynamic>? ?? const {};
        // 途中补充以快照为准：本机还没认领的乐观气泡先撤掉，服务器收下的按 id 补上（没收到的之后由 turn.steered 补）
        var ms = [for (final m in state.messages) if (!m.pending && !(m.steer && m.id.startsWith(localPrefix))) m];
        for (final raw in (e['steered'] as List? ?? const []).whereType<Map<String, dynamic>>()) {
          final m = Message.fromJson(raw);
          if (!ms.any((x) => x.id == m.id)) ms = [...ms, m];
        }
        final prev = state.messages.where((m) => m.pending).lastOrNull;
        var pending = const Message(id: 'pending', role: 'assistant', blocks: [], pending: true)
            .copyWith(blocks: blocksFrom(snap['blocks']), steps: stepsFrom(snap['steps']));
        if (prev != null) pending = pending.withThoughtOf(prev);
        state = state.copyWith(streaming: true, messages: [...ms, pending]);
      case 'turn.steered':
        if (state.activeId != null && e['conversation_id'] != null && state.activeId != e['conversation_id']) return;
        if (e['message'] is! Map<String, dynamic>) return;
        final m = Message.fromJson(e['message'] as Map<String, dynamic>);
        final ms = [...state.messages];
        final i = e['client_id'] is String ? ms.indexWhere((x) => x.id == e['client_id']) : -1;
        if (i >= 0) {
          ms[i] = ms[i].copyWith(steer: true, outbox: Outbox.sent); // 本机发的：认领（保留本地 id，气泡不重建）
          state = state.copyWith(messages: ms);
        } else if (!ms.any((x) => x.id == m.id)) {
          state = state.copyWith(messages: beforePending(ms, m)); // 别的设备补充的
        }
      case 'block.start' || 'block.update':
        final block = Block.fromJson(e['block'] as Map<String, dynamic>);
        _patchPending((m) => m.copyWith(blocks: _setAt(m.blocks, e['index'] as int, block)));
        // 助手改了记忆：记忆列表（记忆页、记忆卡的撤销状态都读它）过期，重拉一次
        if (block is MemoryBlock) ref.invalidate(memoriesProvider);
        // 助手发布了网页 / 分享了这段对话：Pages 列表过期（分享面板是 autoDispose，打开时自己会重拉）
        if (block is PageBlock) ref.invalidate(pagesProvider);
      case 'block.delta':
        _patchPending((m) {
          final i = e['index'] as int;
          final cur = i < m.blocks.length ? m.blocks[i] : const TextBlock('');
          return m.copyWith(blocks: _setAt(m.blocks, i, cur is TextBlock ? cur.append(e['text'] as String) : cur));
        });
      case 'turn.retry':
        final n = RetryNotice.fromJson(e);
        // 已经换过备用模型：之后的普通重试不盖掉“改用了哪个模型”（文字里照样能看出在重试）
        _patchPending((m) => m.copyWith(retry: () => m.retry?.isFallback == true && !n.isFallback
            ? RetryNotice(attempt: n.attempt, max: n.max, delayMs: n.delayMs, reason: n.reason, code: n.code, fallback: m.retry!.fallback, fallbackLabel: m.retry!.fallbackLabel)
            : n));
      case 'turn.model':
        // 选了“自动”：服务器这一轮挑的模型（v1.70 model_router）；模型钮换成“自动 · 快速”
        final m = e['model'];
        if (m is String && m.isNotEmpty) state = state.copyWith(routed: () => m);
      case 'thinking.delta':
        _patchPending((m) => m.think(e['text'] as String? ?? ''));
      case 'tool.status':
        _patchPending((m) => m.copyWith(steps: mergeStep(m.steps, ActivityStep.fromStatus(e))));
      case 'message.done':
        final pending = state.messages.where((m) => m.pending).lastOrNull;
        var done = Message.fromJson(e['message'] as Map<String, dynamic>);
        if (pending != null) done = done.withThoughtOf(pending);
        state = state.copyWith(messages: [...state.messages.where((m) => !m.pending), done], streaming: false, offline: false);
        refreshList();
        final id = state.activeId;
        if (id != null) unawaited(_persist(id));
        _regenerating = false;
        _reattach = false;
        _flush(); // 期间点了“重发”的，轮到它了
      case 'conversation.mode':
        // 方案被批准、服务器已退出计划模式（v1.71）：“计划”钮关掉；列表里的这个对话一起改
        final cid = e['conversation_id'];
        if (cid is String && cid == state.activeId && !_modelDirty) state = state.copyWith(planMode: e['mode'] == 'plan');
        if (cid is String) unawaited(refreshList().catchError((_) {}));
      case 'conversation.title':
        // 第一轮回复后服务器在后台起好了短标题（v1.67）：列表和顶栏原地换字（顶栏的 AnimatedSwitcher 淡入），再同步一次缓存
        final cid = e['conversation_id'], title = e['title'];
        if (cid is String && title is String && title.isNotEmpty) {
          state = state.copyWith(conversations: [for (final c in state.conversations) c.id == cid ? c.withTitle(title) : c]);
          refreshList();
        }
      case 'message.stopped':
        // 还没吐字就停了：撤掉思考占位；用户消息留着（服务器上也在），可以“重试”
        _regenerating = false;
        _reattach = false;
        state = state.copyWith(messages: [for (final m in state.messages) if (!m.pending) m], streaming: false);
        refreshList();
        final id = state.activeId;
        if (id != null) unawaited(_persist(id));
        _flush();
      case 'error':
        // 重新生成被拒（另一台设备已接着聊）或没跑完：本地撤掉的旧回复可能还在服务器上，以服务器为准
        final id = state.activeId;
        if (_regenerating && id != null) unawaited(_fetch(id, _openSeq)); // 下面同步把 streaming 置回 false，拉回来时不会被挡
        _regenerating = false;
        _reattach = false;
        state = state.copyWith(
          messages: [for (final m in state.messages) if (!(m.pending && m.blocks.isEmpty)) m.copyWith(pending: false)],
          streaming: false,
          error: () => e['message'] as String?,
        );
        _flush();
    }
  }

  void _onLink(LinkStatus s) {
    if (s == LinkStatus.down) {
      if (state.streaming && _started && _turnId != null) {
        // 服务器支持续传：回答在那边接着写，这里什么都不丢，连上后补
        _reattach = true;
      } else if (state.streaming) {
        // 回复还没开始：服务器可能没收到，最后一条用户消息标失败让用户决定；已经开始：丢掉半截，连上后从服务器拿完整的
        final ms = [for (final m in state.messages) if (!m.pending) m];
        final lastUser = ms.lastIndexWhere((m) => m.isUser);
        if (!_started && !_regenerating && lastUser >= 0) {
          ms[lastUser] = ms[lastUser].copyWith(outbox: Outbox.failed);
          _probe = state.activeId;
        }
        state = state.copyWith(messages: ms, streaming: false);
        _resync = _started || _regenerating;
        _regenerating = false;
      }
      state = state.copyWith(linkDown: true);
    } else if (s == LinkStatus.open) {
      state = state.copyWith(linkDown: false);
      final id = state.activeId;
      if (_reattach && _turnId != null) {
        _socket.send({'type': 'turn.resume', 'turn_id': _turnId, 'conversation_id': _turnConv ?? id, 'after': _seq});
      } else if (id != null && !state.streaming) {
        _watch(id); // 断线期间别处发起的、或刚才没确认送达的那条，服务器可能正在答
      }
      if (_resync && id != null) unawaited(_fetch(id, _openSeq));
      _resync = false;
      _flush();
    }
  }

  /// 问服务器这个对话有没有正在写的回答（有就接着看，turn.resumed + 补发从 message.start 起的事件）。
  void _watch(String id) => _socket.send({'type': 'turn.resume', 'conversation_id': id});

  void _onResumed(Map<String, dynamic> e) {
    final cid = e['conversation_id'] as String?;
    if (cid != null && state.activeId != null && cid != state.activeId) return; // 别的对话（已切走）
    final probed = _probe != null && _probe == cid;
    _probe = null;
    if (e['live'] != true) {
      final id = state.activeId;
      if (_reattach) {
        // 服务器没这轮了（重启 / 断太久过了保留期）：丢掉半截，以服务器落库的为准
        _reattach = false;
        state = state.copyWith(messages: [for (final m in state.messages) if (!m.pending) m], streaming: false);
        if (id != null) unawaited(_fetch(id, _openSeq));
        _flush();
      } else if (probed && id != null && !state.streaming) {
        unawaited(_fetch(id, _openSeq)); // 那条可能已经送到并答完了
      }
      return;
    }
    _reattach = false;
    final tid = e['turn_id'] as String?;
    if (tid != _turnId) {
      _turnId = tid;
      _seq = 0;
      _started = false;
    }
    _turnConv = cid ?? _turnConv;
    if (!state.streaming) {
      // 接上一轮正在写的回答：发送失败的那条其实已经送到了（服务器正在答它）
      final ms = [...state.messages];
      final i = ms.lastIndexWhere((m) => m.isUser);
      if (probed && i == ms.length - 1 && ms[i].outbox == Outbox.failed) ms[i] = ms[i].copyWith(outbox: Outbox.sent);
      state = state.copyWith(streaming: true, messages: ms);
    }
  }

  /// 把排在最前的待发送消息交给长连接；线不通就启动放弃计时。
  void _flush() {
    if (state.streaming) return;
    final i = state.messages.indexWhere((m) => m.outbox == Outbox.queued);
    if (i < 0) {
      _giveUp?.cancel();
      return;
    }
    final m = state.messages[i];
    final ok = _socket.send({
      'type': 'user.message',
      'conversation_id': state.activeId,
      if (projectId.isNotEmpty) 'project_id': projectId,
      'text': plainText(m.blocks),
      ..._wireFiles(m.blocks),
      ..._wireFollow(m.blocks),
      if (m.quote != null) 'reply_to': m.quote!.id,
      'client_id': m.id,
      ..._modelField(),
    });
    if (!ok) {
      _giveUp ??= Timer(Timing.outboxGiveUp, _expire);
      return;
    }
    _giveUp?.cancel();
    _giveUp = null;
    _started = false;
    _modelDirty = false;
    state = state.copyWith(streaming: true, messages: [for (final x in state.messages) x.id == m.id ? x.copyWith(outbox: Outbox.sent) : x]);
  }

  /// 改过还没送到的模型选择，随消息带上。
  Map<String, dynamic> _modelField() =>
      _modelDirty ? {'model': state.model ?? '', 'reasoning': state.effort ?? '', 'mode': state.planMode ? 'plan' : 'default'} : const {};

  void _expire() {
    _giveUp = null;
    state = state.copyWith(messages: [
      for (final m in state.messages) m.outbox == Outbox.queued ? m.copyWith(outbox: Outbox.failed) : m,
    ]);
  }

  /// 失败的消息重新排队：挪到末尾（回复会接在它后面），线通就发。
  void resend(String id) {
    final i = state.messages.indexWhere((m) => m.id == id && m.outbox == Outbox.failed);
    if (i < 0 || state.messages.any((m) => m.outbox == Outbox.queued)) return;
    final m = state.messages[i].copyWith(outbox: Outbox.queued);
    state = state.copyWith(error: () => null, messages: [...state.messages.where((x) => x.id != id), m]);
    _flush();
  }

  /// 放弃一条没发出去的消息。
  void discard(String id) {
    state = state.copyWith(messages: [for (final m in state.messages) if (!(m.id == id && m.unsent)) m]);
    _flush();
  }

  /// 打开对话：有缓存就同一帧摆出来（不闪空白页），再拿服务器的新内容替换。
  /// 这个对话上次没发出的消息从发件箱接回末尾（发送失败状态）。
  /// [focus]：打开后要定位的消息（搜索命中）。
  Future<void> open(String? id, {String? focus}) async {
    final seq = ++_openSeq;
    final cached = id == null ? null : await _cache.messages(id);
    final unsent = await _cache.outbox(projectId, id);
    if (seq != _openSeq) return;
    _giveUp?.cancel(); // 原对话没发出的消息已在发件箱里，随它一起换走
    _giveUp = null;
    _modelDirty = false;
    _reattach = false;
    _probe = null;
    state = state.copyWith(
        activeId: () => id,
        model: () => _summaryOf(id)?.model,
        effort: () => _summaryOf(id)?.reasoning,
        routed: () => _summaryOf(id)?.routedModel,
        planMode: _summaryOf(id)?.planMode ?? false,
        messages: [if (cached != null) ..._messages(cached), ...unsent],
        error: () => null,
        focus: () => id == null ? null : focus);
    if (id != null) await _fetch(id, seq, hasCache: cached != null);
    if (id != null && seq == _openSeq && state.activeId == id && !state.streaming) _watch(id);
    // 以服务器为准仍找不到那条消息：作废，免得以后某次刷新时突然跳走
    final f = state.focus;
    if (seq == _openSeq && f != null && !state.messages.any((m) => m.id == f)) state = state.copyWith(focus: () => null);
  }

  ConversationSummary? _summaryOf(String? id) {
    for (final c in state.conversations) {
      if (c.id == id) return c;
    }
    return null;
  }

  /// 定位到当前对话里的某条消息（/diff 跳到改动卡，v1.89）：和搜索命中同一条 focus 路，ChatView 滚过去并闪一下。
  void seek(String messageId) {
    if (state.messages.any((m) => m.id == messageId)) state = state.copyWith(focus: () => messageId);
  }

  /// 取走待定位的消息（只给一次）：那条消息已在列表里才给，否则返回 null、请求留着等服务器版本。
  String? takeFocus() {
    final f = state.focus;
    if (f == null || !state.messages.any((m) => m.id == f)) return null;
    state = state.copyWith(focus: () => null);
    return f;
  }

  Future<void> _fetch(String id, int seq, {bool hasCache = true}) async {
    try {
      final detail = await _api.get('/api/conversations/$id') as Map<String, dynamic>;
      final raw = detail['messages'] as List;
      unawaited(_cache.putMessages(id, raw));
      if (seq == _openSeq && state.activeId == id && !_modelDirty) state = state.copyWith(model: () => detail['model'] as String?, effort: () => detail['reasoning'] as String?, planMode: detail['mode'] == 'plan');
      if (seq == _openSeq && state.activeId == id) state = state.copyWith(routed: () => detail['routed_model'] as String?);
      // 等待期间用户换了对话或已经开始发消息：不覆盖眼前的内容
      if (seq != _openSeq || state.activeId != id || state.streaming) return;
      // 本机还没发出的消息接在服务器版本后面，不能被刷新冲掉
      state = state.copyWith(messages: [..._messages(raw), ...state.messages.where((m) => m.unsent)], offline: false);
    } on ApiError catch (e) {
      if (seq != _openSeq || state.activeId != id) return;
      state = e.isNetwork && hasCache ? state.copyWith(offline: true) : state.copyWith(error: () => e.message, offline: e.isNetwork);
    }
  }

  /// 一轮回复结束后把服务器版本存进缓存（不改界面：本地这条用户消息的 id 和服务器不同，替换会让列表重建）。
  Future<void> _persist(String id) async {
    try {
      final raw = (await _api.get('/api/conversations/$id') as Map<String, dynamic>)['messages'] as List;
      await _cache.putMessages(id, raw);
    } catch (_) {}
  }

  /// [quote] = 引用回复（§J）：随消息带 reply_to，气泡顶上画引用行；生成中发出的引用回复服务器排成下一轮（不插进这一轮）。
  void send(String text, {List<FileBlock> files = const [], MessageQuote? quote}) {
    if (text.trim().isEmpty && files.isEmpty) return;
    if (state.busy) {
      if (state.canSteer) _steer(text.trim(), files, quote);
      return;
    }
    final blocks = <Block>[if (text.trim().isNotEmpty) TextBlock(text.trim()), ...files];
    final m = Message(
        id: '$localPrefix${DateTime.now().microsecondsSinceEpoch}', role: 'user', blocks: blocks, outbox: Outbox.queued, createdAt: DateTime.now(), quote: quote);
    state = state.copyWith(error: () => null, messages: [...state.messages, m]);
    _flush();
  }

  /// 接着问某个子助手（v1.97，子任务卡上的“追问”）：气泡带一枚“追问 · 标题”标签；正在回答时排队等这一轮结束
  /// （不插进正在进行的那一轮——那是新的一件事，服务器 steering 也不收）。
  void followUp(String id, String title, String text) {
    final t = text.trim();
    if (t.isEmpty || id.isEmpty) return;
    final m = Message(
        id: '$localPrefix${DateTime.now().microsecondsSinceEpoch}',
        role: 'user',
        blocks: [TextBlock(t), AgentBlock(target: id, title: title)],
        outbox: Outbox.queued,
        createdAt: DateTime.now());
    state = state.copyWith(error: () => null, messages: [...state.messages, m]);
    _flush();
  }

  /// 消息里的追问标签 → user.message 的 follow / follow_title（服务器以库里的标题为准）。
  static Map<String, String> _wireFollow(List<Block> blocks) {
    final a = blocks.whereType<AgentBlock>().where((a) => a.target != null).firstOrNull;
    return a == null ? const {} : {'follow': a.target!, if (a.title != null) 'follow_title': a.title!};
  }

  /// 消息里的附件 → user.message 的线格式：上传的进 attachments，工作区文件进 project_files。
  static Map<String, List<String>> _wireFiles(List<Block> blocks) => {
        'attachments': [for (final f in blocks.whereType<FileBlock>()) if (f.source != 'project') f.id],
        'project_files': [for (final f in blocks.whereType<FileBlock>()) if (f.source == 'project') f.id],
      };

  /// 本机还没拿到服务器 id 的消息的 id 前缀。
  static const localPrefix = 'local-';

  /// 生成中补一句（文字和 / 或附件，v1.93 服务器 steering 也收附件）：立刻插在生成中那条前面；
  /// 线不通就标失败（“重发”= 挪到末尾排成下一轮）。附件和普通发送同一个线格式（_wireFiles）。
  void _steer(String text, List<FileBlock> files, [MessageQuote? quote]) {
    final blocks = <Block>[if (text.isNotEmpty) TextBlock(text), ...files];
    final m = Message(
        id: '$localPrefix${DateTime.now().microsecondsSinceEpoch}', role: 'user', blocks: blocks, steer: true, createdAt: DateTime.now(), quote: quote);
    final ok = _socket.send({
      'type': 'user.message',
      'conversation_id': state.activeId,
      if (projectId.isNotEmpty) 'project_id': projectId,
      'text': text,
      ..._wireFiles(blocks),
      if (quote != null) 'reply_to': quote.id,
      'steer': true,
      'client_id': m.id,
    });
    state = state.copyWith(error: () => null, messages: beforePending(state.messages, ok ? m : m.copyWith(steer: false, outbox: Outbox.failed)));
  }

  /// 重新生成最后一条回复；最后一条是用户消息时 = 重试（不带 message_id）。
  void regenerate() => _rewind();

  /// 评价一条回复（v2.64，规则在后端 app/feedback.py）：[kind] = good / 👎 的原因，null = 取消。
  /// 先在本机换上（图标立刻变实心），服务器没收下就换回原样再抛出，由界面提示。
  Future<void> rate(String id, String? kind, {String? note}) async {
    final old = state.messages.where((m) => m.id == id).firstOrNull;
    if (old == null) return;
    void put(String? k) => state = state.copyWith(messages: [for (final m in state.messages) m.id == id ? m.copyWith(feedback: () => k) : m]);
    put(kind);
    try {
      if (kind == null) {
        await _api.delete('/api/messages/$id/feedback');
      } else {
        await _api.post('/api/messages/$id/feedback', {'kind': kind, if (note != null && note.isNotEmpty) 'note': note});
      }
    } catch (_) {
      put(old.feedback);
      rethrow;
    }
  }

  /// 改写最后一条用户消息并重答。附件、“追问”标签保留（服务器 runner.rewind 同规则）；文字清空且没有附件 = 不发。
  void edit(String text) {
    final id = state.editableId;
    if (id == null) return;
    final old = state.messages.lastWhere((m) => m.id == id);
    final files = old.blocks.whereType<FileBlock>();
    final follow = old.blocks.whereType<AgentBlock>().where((a) => a.target != null);
    final t = text.trim();
    if (t.isEmpty && files.isEmpty) return;
    _rewind(edited: old.copyWith(blocks: [if (t.isNotEmpty) TextBlock(t), ...files, ...follow]));
  }

  /// 重新生成与编辑的共同流程：发请求 → 本地撤掉最后一条用户消息之后的回复（编辑时顺带换上新气泡）→ 等新一轮。
  void _rewind({Message? edited}) {
    if (!state.canRegenerate) return;
    final last = state.messages.last;
    final ok = _socket.send({
      'type': 'message.regenerate',
      'conversation_id': state.activeId,
      if (!last.isUser) 'message_id': last.id,
      if (edited != null) 'text': plainText(edited.blocks),
      ..._modelField(),
    });
    if (!ok) {
      state = state.copyWith(error: () => '连接已断开，连上后再试');
      return;
    }
    final lastUser = state.messages.lastIndexWhere((m) => m.isUser);
    _started = false;
    _regenerating = true;
    _modelDirty = false;
    state = state.copyWith(streaming: true, error: () => null, messages: [
      ...state.messages.sublist(0, edited == null ? lastUser + 1 : lastUser),
      ?edited,
    ]);
  }

  /// 停止生成。不排队：线断了就提示，连上后再点（回答在服务器上接着写，重连后续传，停止键还在）。
  void stop() {
    if (!state.canStop) return;
    if (!_socket.send({'type': 'message.cancel', 'conversation_id': state.activeId})) {
      state = state.copyWith(error: () => '连接已断开，连上后再试');
      return;
    }
    state = state.copyWith(stopping: true);
  }

  /// 审批必须实时送达（服务器那一轮在等它），断线时不排队，直接提示。
  /// option = 卡上选的批准范围（主机命令卡：once / session / rule；没有就是普通批准）。
  void replyApproval(String id, bool approved, [String? option]) {
    if (!_socket.send({'type': 'approval.reply', 'id': id, 'approved': approved, 'option': ?option})) {
      state = state.copyWith(error: () => '连接已断开，连上后再点一次');
    }
  }

  /// 改动卡的整轮撤销（v1.68，后端 turn_changes.py）：找到带这个 token 的回复，POST 撤销，成功后换成服务器回的版本。
  /// 返回 null = 成功；否则是给用户看的原因（文件之后又被改过 / 记录过期 / 正在回复 / 断网）。
  Future<String?> undoChanges(String token) async {
    final cid = state.activeId;
    final m = state.messages.where((m) => m.blocks.any((b) => b is ChangesBlock && b.token == token)).firstOrNull;
    if (cid == null || m == null) return '找不到这条回复';
    try {
      final j = await ref.read(apiProvider).post('/api/conversations/$cid/messages/${m.id}/changes/undo') as Map<String, dynamic>;
      final next = Message.fromJson(j);
      state = state.copyWith(messages: [for (final x in state.messages) x.id == m.id ? next.withThoughtOf(x) : x]);
      unawaited(_persist(cid));
      return null;
    } on ApiError catch (e) {
      return e.isNetwork ? '连不上服务器，稍后再试' : e.message;
    }
  }

  /// 表单卡（登录、验证码）的答复。values = null 表示取消。值只走这一条线，不进本地状态和缓存。
  bool replyForm(String id, Map<String, String>? values, bool remember) {
    final ok = _socket.send({'type': 'form.reply', 'id': id, 'values': values, 'remember': remember});
    if (!ok) state = state.copyWith(error: () => '连接已断开，连上后再点一次');
    return ok;
  }

  /// 换这个对话的模型（null = 默认）。界面立刻变；服务器那边见文件头“模型”。
  Future<void> setModel(String? alias) async {
    if (alias == state.model) return;
    state = state.copyWith(model: () => alias);
    await _pushChoice();
  }

  /// 换这个对话的思考强度（null = 模型默认）。和模型同一条路。
  Future<void> setEffort(String? effort) async {
    if (effort == state.effort) return;
    state = state.copyWith(effort: () => effort);
    await _pushChoice();
  }

  /// 开 / 关计划模式（v1.71）。和模型同一条路：已有对话立刻 PATCH，新对话随第一条消息带上；这一轮正在跑时从下一轮起生效。
  Future<void> setPlanMode(bool on) async {
    if (on == state.planMode) return;
    state = state.copyWith(planMode: on);
    await _pushChoice();
  }

  /// 模型选择（模型 + 思考强度 + 计划模式）送到服务器：已有对话立刻 PATCH；新对话 / 没成功就留着 dirty，随下一条消息带上。
  Future<void> _pushChoice() async {
    _modelDirty = true;
    final id = state.activeId;
    if (id == null) return; // 新对话：随第一条消息带上
    final sent = (state.model, state.effort, state.planMode);
    try {
      await _api.patch('/api/conversations/$id', _modelField());
      if (state.activeId == id && (state.model, state.effort, state.planMode) == sent) _modelDirty = false;
      unawaited(refreshList().catchError((_) {}));
    } on ApiError catch (e) {
      if (!e.isNetwork && state.activeId == id) state = state.copyWith(error: () => e.message);
    }
  }

  Future<void> rename(String id, String title) => _patch(id, {'title': title});

  Future<void> setPinned(String id, bool pinned) => _patch(id, {'pinned': pinned});

  Future<void> _patch(String id, Map<String, dynamic> body) async {
    await _api.patch('/api/conversations/$id', body);
    await refreshList(); // 置顶会改变顺序，以服务器排序为准
  }

  /// 导出整段对话（Markdown）。以服务器为准；连不上时用离线缓存，两者都没有才报错。
  /// 正打开的对话也重新拉：眼前的列表里可能有本地临时 id 的消息，服务器版本最完整。
  Future<String> exportMarkdown(String id, String title) async {
    List<dynamic>? raw;
    try {
      raw = (await _api.get('/api/conversations/$id') as Map<String, dynamic>)['messages'] as List;
      unawaited(_cache.putMessages(id, raw));
    } on ApiError catch (e) {
      if (!e.isNetwork) rethrow;
      raw = await _cache.messages(id);
      if (raw == null) throw ApiError('没连上服务器，这段对话也没有离线副本');
    }
    return conversationMarkdown(title, _messages(raw));
  }

  Future<void> remove(String id) async {
    await _api.delete('/api/conversations/$id');
    unawaited(_cache.forget(id));
    if (state.activeId == id) await open(null);
    await refreshList();
  }
}

final chatProvider = NotifierProvider.family<ChatController, ChatState, String>(ChatController.new);
