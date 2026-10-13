// 记忆笔记（v2.21）的纯逻辑：一个主题一篇 Markdown（一个人、一个地方、一个项目）。
// 规则以后端 app/memory_notes.py 为准；这里只做显示用的名字、类别、筛选和第一行，不碰界面，测试直接调。
import 'package:flutter/material.dart' show IconData, Icons;

DateTime? _date(dynamic v) => v is String ? DateTime.tryParse(v)?.toLocal() : null;

class MemoryNote {
  const MemoryNote({required this.id, required this.path, required this.title, this.kind = 'misc', this.body = '', this.updatedAt});
  factory MemoryNote.fromJson(Map<String, dynamic> j) => MemoryNote(
        id: j['id'] as String,
        path: j['path'] as String? ?? '',
        title: j['title'] as String? ?? '',
        kind: j['kind'] as String? ?? 'misc',
        body: j['body'] as String? ?? '',
        updatedAt: _date(j['updated_at']),
      );
  final String id, path, title, kind, body;
  final DateTime? updatedAt;

  /// 路径最后一段（“people/张三” → “张三”）。
  String get name => path.split('/').last;

  /// 路径里的文件夹（没有 → null）。
  String? get folder => path.contains('/') ? path.substring(0, path.lastIndexOf('/')) : null;
}

/// 类别：后端 memory_notes.KINDS 的同一份（顺序即显示顺序）。
const noteKinds = {
  'contact': '人',
  'place': '地方',
  'project': '项目',
  'organization': '组织',
  'interest': '兴趣',
  'event': '事件',
  'misc': '其他',
};

String noteKindLabel(String k) => noteKinds[k] ?? noteKinds['misc']!;

IconData noteKindIcon(String k) => switch (k) {
      'contact' => Icons.person_outline_rounded,
      'place' => Icons.place_outlined,
      'project' => Icons.flag_outlined,
      'organization' => Icons.apartment_rounded,
      'interest' => Icons.favorite_border_rounded,
      'event' => Icons.event_outlined,
      _ => Icons.description_outlined,
    };

/// 第一行非空文字，去掉 Markdown 标题 / 列表符号（和后端 first_line 一致，长度交给界面省略）。
String noteFirstLine(String body) {
  for (final line in body.split('\n')) {
    var t = line.trim();
    while (t.startsWith('#')) {
      t = t.substring(1);
    }
    t = t.trim();
    while (t.startsWith('-') || t.startsWith('*')) {
      t = t.substring(1);
    }
    t = t.trim();
    if (t.isNotEmpty) return t;
  }
  return '';
}

/// 列表行的副标题：类别 · 第一行（和标题重复的第一行跳过，换成“空”或路径）。
String noteSubtitle(MemoryNote n) {
  final first = noteFirstLine(n.body);
  final line = first.isEmpty || first == n.title ? (n.body.trim().isEmpty ? '还没写内容' : n.path) : first;
  return '${noteKindLabel(n.kind)} · $line';
}

/// 搜索：空格分开的词都要在 路径 / 标题 / 正文 / 类别名 里出现（不分大小写）。
List<MemoryNote> filterNotes(List<MemoryNote> list, String query) {
  final words = query.toLowerCase().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  if (words.isEmpty) return list;
  return [
    for (final n in list)
      if (words.every('${n.path}\n${n.title}\n${n.body}\n${noteKindLabel(n.kind)}'.toLowerCase().contains)) n,
  ];
}

/// 新建时：只填了名字、类别有默认文件夹 → 预览会存成的路径（和后端 normalize 一致：人 → people/，地方 → locations/）。
String notePathPreview(String input, String kind) {
  var p = input.trim().replaceAll('\\', '/');
  while (p.startsWith('/')) {
    p = p.substring(1);
  }
  if (p.toLowerCase().endsWith('.md')) p = p.substring(0, p.length - 3);
  p = p.split('/').map((s) => s.trim()).join('/');
  if (p.isEmpty || p.contains('/')) return p;
  final folder = switch (kind) { 'contact' => 'people', 'place' => 'locations', _ => '' };
  return folder.isEmpty ? p : '$folder/$p';
}

/// 读屏：“笔记 张三，人，本科室友”。
String noteSemantics(MemoryNote n) {
  final first = noteFirstLine(n.body);
  return '笔记 ${n.title}，${noteKindLabel(n.kind)}${first.isEmpty || first == n.title ? '' : '，$first'}';
}

/// 记忆页“主题笔记”一节的计数说明。
String notesSummary(int n) => n == 0 ? '还没有笔记' : '$n 篇笔记';
