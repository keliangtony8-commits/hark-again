// 聊天状态的唯一归属地（对应网页版 useChat）。
// 把服务器事件流折叠成消息列表；界面只读 ChatState、只调 open/send/replyApproval/replyForm。
// family 参数：'' = 主聊天；项目 id = 该项目里的聊天。
// 离线：先显示 chat_cache 里的上次内容（瞬开），再向服务器要新的；连不上就留着缓存并标 offline，界面给“离线”条。
// 发件箱：发出的消息先作为 Outbox.queued 进列表；线通了就真正发出（sent），一次只在飞一条。
//   没连上等太久 → failed；发出后、回复开始前断线 → failed（服务器可能没收到）；回复中途断线 → 连上后重新同步。
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
      this.model});
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

  /// 输入框是否该等：在生成，或有一条在排队（一次只排一条，避免新对话被拆成几段）。
  bool get busy => streaming || messages.any((m) => m.outbox == Outbox.queued);

  /// 停止键可点：在生成且还没请求过停止。
  bool get canStop => streaming && !stopping;

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
          String? Function()? model}) =>
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
  bool _modelDirty = false; // 本机改了模型还没送到服务器（新对话 / PATCH 没成功）
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
    switch (e['type']) {
      case 'message.start':
        if (state.activeId != null && state.activeId != e['conversation_id']) return; // 别的会话的事件
        _started = true;
        final ms = [...state.messages];
        // 编辑：用服务器规整后的版本覆盖本地乐观改写（保留本地 id，气泡不重建）
        if (e['user_message'] case final Map<String, dynamic> um) {
          final i = ms.lastIndexWhere((m) => m.isUser);
          if (i >= 0) ms[i] = ms[i].copyWith(blocks: Message.fromJson(um).blocks);
        }
        state = state.copyWith(
          activeId: () => e['conversation_id'] as String,
          messages: [...ms, const Message(id: 'pending', role: 'assistant', blocks: [], pending: true)],
        );
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
        _flush(); // 期间点了“重发”的，轮到它了
      case 'message.stopped':
        // 还没吐字就停了：撤掉思考占位；用户消息留着（服务器上也在），可以“重试”
        _regenerating = false;
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
      if (state.streaming) {
        // 回复还没开始：服务器可能没收到，最后一条用户消息标失败让用户决定；已经开始：丢掉半截，连上后从服务器拿完整的
        final ms = [for (final m in state.messages) if (!m.pending) m];
        final lastUser = ms.lastIndexWhere((m) => m.isUser);
        if (!_started && !_regenerating && lastUser >= 0) ms[lastUser] = ms[lastUser].copyWith(outbox: Outbox.failed);
        state = state.copyWith(messages: ms, streaming: false);
        _resync = _started || _regenerating;
        _regenerating = false;
      }
      state = state.copyWith(linkDown: true);
    } else if (s == LinkStatus.open) {
      state = state.copyWith(linkDown: false);
      final id = state.activeId;
      if (_resync && id != null) unawaited(_fetch(id, _openSeq));
      _resync = false;
      _flush();
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
      'attachments': [for (final f in m.blocks.whereType<FileBlock>()) if (f.source != 'project') f.id],
      'project_files': [for (final f in m.blocks.whereType<FileBlock>()) if (f.source == 'project') f.id],
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
  Map<String, dynamic> _modelField() => _modelDirty ? {'model': state.model ?? ''} : const {};

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
    state = state.copyWith(
        activeId: () => id,
        model: () => _summaryOf(id)?.model,
        messages: [if (cached != null) ..._messages(cached), ...unsent],
        error: () => null,
        focus: () => id == null ? null : focus);
    if (id != null) await _fetch(id, seq, hasCache: cached != null);
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
      if (seq == _openSeq && state.activeId == id && !_modelDirty) state = state.copyWith(model: () => detail['model'] as String?);
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

  void send(String text, {List<FileBlock> files = const []}) {
    if ((text.trim().isEmpty && files.isEmpty) || state.busy) return;
    final blocks = <Block>[if (text.trim().isNotEmpty) TextBlock(text.trim()), ...files];
    final m = Message(id: 'local-${DateTime.now().microsecondsSinceEpoch}', role: 'user', blocks: blocks, outbox: Outbox.queued, createdAt: DateTime.now());
    state = state.copyWith(error: () => null, messages: [...state.messages, m]);
    _flush();
  }

  /// 重新生成最后一条回复；最后一条是用户消息时 = 重试（不带 message_id）。
  void regenerate() => _rewind();

  /// 改写最后一条用户消息并重答。附件保留；文字清空且没有附件 = 不发。
  void edit(String text) {
    final id = state.editableId;
    if (id == null) return;
    final old = state.messages.lastWhere((m) => m.id == id);
    final files = old.blocks.whereType<FileBlock>();
    final t = text.trim();
    if (t.isEmpty && files.isEmpty) return;
    _rewind(edited: old.copyWith(blocks: [if (t.isNotEmpty) TextBlock(t), ...files]));
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

  /// 停止生成。不排队：线断了这一轮本来就会在服务器上被停下（断线即停、半截落库），重连后同步即可。
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
    _modelDirty = true;
    final id = state.activeId;
    if (id == null) return; // 新对话：随第一条消息带上
    try {
      await _api.patch('/api/conversations/$id', {'model': alias ?? ''});
      if (state.activeId == id && state.model == alias) _modelDirty = false;
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
