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
      this.createdAt,
      this.thought = '',
      this.thinkFrom,
      this.thinkTo,
      this.retry});

  factory Message.fromJson(Map<String, dynamic> j) => Message(
      id: j['id'] as String,
      role: j['role'] as String,
      blocks: blocksFrom(j['blocks']),
      steps: stepsFrom(j['steps']),
      end: ReplyEnd.parse(j['status']),
      createdAt: DateTime.tryParse(j['created_at'] as String? ?? '')?.toLocal());

  final String id, role;
  final List<Block> blocks;
  /// 活动时间线（models/activity.dart）：生成中由 tool.status 实时合并，完成后以服务器落库的为准。
  final List<ActivityStep> steps;
  final bool pending; // 正在生成
  final Outbox outbox;

  /// 这一轮怎么结束的（服务器 status，models/reply_end.dart）：停止 / 被打断 / 预算用完 / 原地打转。
  final ReplyEnd end;

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
          String? thought,
          DateTime? thinkFrom,
          DateTime? thinkTo,
          RetryNotice? Function()? retry}) =>
      Message(
      id: id,
      role: role,
      blocks: blocks ?? this.blocks,
      steps: steps ?? this.steps,
      pending: pending ?? this.pending,
      outbox: outbox ?? this.outbox,
      end: end,
      createdAt: createdAt,
      thought: thought ?? this.thought,
      thinkFrom: thinkFrom ?? this.thinkFrom,
      thinkTo: thinkTo ?? this.thinkTo,
      retry: retry != null ? retry() : this.retry);
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
