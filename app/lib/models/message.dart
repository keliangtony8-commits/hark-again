import 'block.dart';

class ToolRun {
  const ToolRun({required this.id, required this.label, required this.running});
  final String id, label;
  final bool running;
}

/// 用户消息的发送状态（只存在于本机；服务器来的消息都是 sent）。
/// queued：没连上，连上自动发；failed：等太久或发出后断线没回音，要用户点“重发”。
enum Outbox { sent, queued, failed }

class Message {
  const Message(
      {required this.id,
      required this.role,
      required this.blocks,
      this.tools = const [],
      this.pending = false,
      this.outbox = Outbox.sent,
      this.stopped = false,
      this.createdAt});

  factory Message.fromJson(Map<String, dynamic> j) => Message(
      id: j['id'] as String,
      role: j['role'] as String,
      blocks: blocksFrom(j['blocks']),
      stopped: j['status'] == 'stopped',
      createdAt: DateTime.tryParse(j['created_at'] as String? ?? '')?.toLocal());

  final String id, role;
  final List<Block> blocks;
  final List<ToolRun> tools;
  final bool pending; // 正在生成
  final Outbox outbox;

  /// 用户中途点了停止，内容是半截的（服务器 status=stopped）。
  final bool stopped;

  /// 本地时间；老服务器不给、正在生成的占位消息没有 → null（日期分隔把它算进上一条的那天）。
  final DateTime? createdAt;

  bool get isUser => role == 'user';

  /// 还在本机、没进服务器的消息（待发送或发送失败）。
  bool get unsent => outbox != Outbox.sent;

  Message copyWith({List<Block>? blocks, List<ToolRun>? tools, bool? pending, Outbox? outbox}) => Message(
      id: id,
      role: role,
      blocks: blocks ?? this.blocks,
      tools: tools ?? this.tools,
      pending: pending ?? this.pending,
      outbox: outbox ?? this.outbox,
      stopped: stopped,
      createdAt: createdAt);
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
