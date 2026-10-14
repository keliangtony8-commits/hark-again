// 整个对话导出成 Markdown（App 用系统分享、网页版下载同一份文本；网页版的 lib/export.ts 是同一套规则）。
// 每条消息的正文复用 copyText（块 → Markdown），所以“复制一条”和“导出整段”的写法永远一致。
// 只导出已进服务器的消息：本机没发出的、正在生成的都不算。
import '../brand.dart';
import 'block.dart';
import 'message.dart';

String conversationMarkdown(String title, List<Message> messages, {DateTime? at}) {
  final t = at ?? DateTime.now();
  final kept = [
    for (final m in messages)
      if (!m.pending && !m.unsent) (m, copyText(m.blocks)),
  ].where((e) => e.$2.isNotEmpty).toList();
  final parts = [
    '# ${title.trim().isEmpty ? '新对话' : title.trim()}',
    '> 导出于 ${_stamp(t)} · ${kept.length} 条消息',
    for (final (m, body) in kept) ...[
      m.isUser ? '## 我' : '## $appName',
      m.endLabel != null ? '$body\n\n*（${m.endLabel}）*' : body,
    ],
  ];
  return '${parts.join('\n\n')}\n';
}

/// 导出文件名：标题里文件系统不认的字符换成下划线，太长截断。
String exportFileName(String title) {
  var name = title.trim().replaceAll(RegExp(r'[\\/:*?"<>|\x00-\x1F]'), '_').replaceAll(RegExp(r'\s+'), ' ');
  if (name.isEmpty) name = '对话';
  if (name.runes.length > 60) name = String.fromCharCodes(name.runes.take(60));
  return '$name.md';
}

String _stamp(DateTime t) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${t.year}-${two(t.month)}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}';
}
