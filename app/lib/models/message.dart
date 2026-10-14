import 'activity.dart';
import 'block.dart';
import 'reply_end.dart';
import 'retry_notice.dart';

/// 用户消息的发送状态（只存在于本机；服务器来的消息都是 sent）。
/// queued：没连上，连上自动发；failed：等太久或发出后断线没回音，要用户点“重发”。
enum Outbox { sent, queued, failed }

class Message {
  const Message(
      {required this.id,
      required this.role,
      required this.blocks,
      this.steps = const [],
      this.pending = false,
      this.outbox = Outbox.sent,
      this.end = ReplyEnd.done,
      this.steer = false,
      this.createdAt,
      this.thought = '',
      this.thinkFrom,
      this.thinkTo,
      this.retry,
      this.feedback,
      this.quote,
      this.serverId});

  factory Message.fromJson(Map<String, dynamic> j) => Message(
      id: j['id'] as String,
      role: j['role'] as String,
      blocks: blocksFrom(j['blocks']),
      steps: stepsFrom(j['steps']),
      end: ReplyEnd.parse(j['status']),
      steer: j['role'] == 'user' && j['status'] == steerStatus,
      createdAt: DateTime.tryParse(j['created_at'] as String? ?? '')?.toLocal(),
      feedback: j['feedback'] as String?,
      quote: MessageQuote.fromJson(j['quote']));

  final String id, role;
  final List<Block> blocks;
  /// 活动时间线（models/activity.dart）：生成中由 tool.status 实时合并，完成后以服务器落库的为准。
  final List<ActivityStep> steps;
  final bool pending; // 正在生成
  final Outbox outbox;

  /// 这一轮怎么结束的（服务器 status，models/reply_end.dart）：停止 / 被打断 / 预算用完 / 原地打转。
  final ReplyEnd end;

  /// 用户消息：助手回答途中发来的（服务器 status = steer，后端 message_intake.py 决定并进这一轮还是另回）。
  /// 只影响位置（插在生成中那条前面），不另标字：v2.90 起服务器自己判断是补充还是另一件事，用户不用管。
  final bool steer;
  static const steerStatus = 'steer';

  bool get stopped => end == ReplyEnd.stopped;
  bool get interrupted => end == ReplyEnd.interrupted;

  /// 内容不完整：停止或被打断，重新生成就能补全。
  bool get cutShort => end.cutShort;

  /// 没正常说完时行尾的说明（[ReplyEnd.label]）；done → null。
  String? get endLabel => end.label;

  /// 本地时间；老服务器不给、正在生成的占位消息没有 → null（日期分隔把它算进上一条的那天）。
  final DateTime? createdAt;

  /// 推理模型的思考（WS thinking.delta 累积，只留尾部 [thoughtKeep] 字）。生成中给用户看进度，
  /// 生成完由控制器接到正式消息上（[withThoughtOf]），回复上方可展开回看；服务器不存，重新打开对话就没了。
  final String thought;
  static const thoughtKeep = 2000;

  /// 第一段 / 最近一段思考到达的本机时间：算“已思考 N 秒”。同样只活在本次会话里。
  final DateTime? thinkFrom, thinkTo;

  /// 模型调用失败、服务器正在自动重试 / 已换备用模型（WS turn.retry，models/retry_notice.dart）：只挂在生成中的占位消息上。
  final RetryNotice? retry;

  bool get isUser => role == 'user';

  /// 用户对这条回复的评价（v2.64，models/feedback.dart）：good = 👍，其余是 👎 的原因；null = 没评。
  final String? feedback;

  /// 引用（§J / §C，后端 app/reply_quote.py）：用户消息 = 用户点“回复”引用的那条；助手消息 = 它回应的那句（v2.90 每条回复都带）。
  /// 画不画由 [showsQuote] 决定。
  final MessageQuote? quote;

  /// 本机发出的消息被服务器认领后的服务器 id（本地 id 不换，免得列表重建）：回复的引用 / 跳回原话按它对得上（[isId]）。
  final String? serverId;

  /// 这条是不是 [other]：本地 id 或认领后的服务器 id。
  bool isId(String? other) => other != null && (id == other || serverId == other);

  /// 追加一段思考，超长只留尾部（思考可能有几万字，界面只看最近的）。[at] = 到达时间（测试可注入）。
  Message think(String delta, {DateTime? at}) {
    final t = thought + delta;
    final now = at ?? DateTime.now();
    return copyWith(
        thought: t.length > thoughtKeep ? t.substring(t.length - thoughtKeep) : t, thinkFrom: thinkFrom ?? now, thinkTo: now);
  }

  /// 思考用了多久（第一段到最后一段）；没思考过 → null。
  Duration? get thinkTime => thinkFrom == null ? null : thinkTo!.difference(thinkFrom!);

  /// message.done 换上正式消息时，把本机才有的思考（内容 + 计时）接过去：回复下方能展开“已思考 N 秒”。
  Message withThoughtOf(Message pending) =>
      pending.thought.isEmpty ? this : copyWith(thought: pending.thought, thinkFrom: pending.thinkFrom, thinkTo: pending.thinkTo);

  /// 还在本机、没进服务器的消息（待发送或发送失败）。
  bool get unsent => outbox != Outbox.sent;

  Message copyWith(
          {List<Block>? blocks,
          List<ActivityStep>? steps,
          bool? pending,
          Outbox? outbox,
          bool? steer,
          String? thought,
          DateTime? thinkFrom,
          DateTime? thinkTo,
          RetryNotice? Function()? retry,
          String? Function()? feedback,
          String? serverId}) =>
      Message(
      id: id,
      role: role,
      blocks: blocks ?? this.blocks,
      steps: steps ?? this.steps,
      pending: pending ?? this.pending,
      outbox: outbox ?? this.outbox,
      end: end,
      steer: steer ?? this.steer,
      createdAt: createdAt,
      thought: thought ?? this.thought,
      thinkFrom: thinkFrom ?? this.thinkFrom,
      thinkTo: thinkTo ?? this.thinkTo,
      retry: retry != null ? retry() : this.retry,
      feedback: feedback != null ? feedback() : this.feedback,
      quote: quote,
      serverId: serverId ?? this.serverId);
}

/// 被引用的那条：id + 角色 + 一行原文（服务器截断，≤120 字）；missing = 原消息已删除（不报错，显示“原消息已删除”）。
class MessageQuote {
  const MessageQuote({required this.id, this.role = 'assistant', this.text = '', this.missing = false});

  /// 从界面上的一条消息取引用（点“回复”时）：纯文字，没有文字就用附件名，压成一行。
  factory MessageQuote.of(Message m) {
    var t = plainText(m.blocks);
    final names = m.blocks.whereType<FileBlock>().map((f) => f.name).where((n) => n.isNotEmpty).join('、');
    if (t.isEmpty && names.isNotEmpty) t = '[附件] $names';
    if (t.isEmpty) t = copyText(m.blocks);
    t = t.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).join(' ');
    return MessageQuote(id: m.id, role: m.role, text: t.length > snippet ? '${t.substring(0, snippet - 1)}…' : t);
  }

  static MessageQuote? fromJson(Object? j) {
    if (j is! Map || j['id'] is! String) return null;
    return MessageQuote(
        id: j['id'] as String, role: j['role'] as String? ?? 'assistant', text: j['text'] as String? ?? '', missing: j['missing'] == true);
  }

  static const snippet = 120; // = 后端 reply_quote.SNIPPET
  static const missingText = '原消息已删除';

  final String id, role, text;
  final bool missing;

  /// 引用条上显示的那行字。
  String get line => missing ? missingText : text;
}

/// 把 [m] 放到生成中的那条前面（没有生成中的就接在末尾）：回答途中补充的话排在这一轮回复之前，
/// 和服务器落库的顺序（提问 → 补充 → 回复，后端 steering.py）一致。
List<Message> beforePending(List<Message> ms, Message m) {
  final i = ms.lastIndexWhere((x) => x.pending);
  return i < 0 ? [...ms, m] : [...ms.sublist(0, i), m, ...ms.sublist(i)];
}

/// 第 i 条消息顶上画不画引用行（§C）：用户自己引用的一定画；助手回复只在原话不“紧挨着”时画——
/// 往上一串连续的用户消息（一口气发的、途中补充的）里有原话 = 紧挨着，不画；中间隔了别的回复（问进度、并行回答）才画。
bool showsQuote(List<Message> ms, int i) {
  final q = ms[i].quote;
  if (q == null) return false;
  if (ms[i].isUser) return true;
  for (var j = i - 1; j >= 0 && ms[j].isUser; j--) {
    if (ms[j].isId(q.id)) return false;
  }
  return true;
}

/// 第 i 条消息前要不要画日期分隔：第一条有时间的消息、或与上一条有时间的消息不在同一个本地日。
/// 没有时间的消息从不开新的一天（老服务器的整段对话就一条分隔也没有，不会乱画）。
bool startsNewDay(List<Message> ms, int i) {
  final t = ms[i].createdAt;
  if (t == null) return false;
  for (var j = i - 1; j >= 0; j--) {
    final prev = ms[j].createdAt;
    if (prev != null) return prev.year != t.year || prev.month != t.month || prev.day != t.day;
  }
  return true;
}
