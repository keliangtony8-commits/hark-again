// 消息块：与后端 backend/app/blocks.py、docs/protocol.md 一一对应。
// 新增块类型 = 这里加一个类 + blocks/ 里加一个组件 + registry 登记。认不出的类型变成 UnknownBlock，不崩。
sealed class Block {
  const Block();

  factory Block.fromJson(Map<String, dynamic> j) => switch (j['type']) {
        'text' => TextBlock(j['text'] as String? ?? ''),
        'links' => LinksBlock([for (final i in (j['items'] as List? ?? [])) LinkItem.fromJson(i as Map<String, dynamic>)]),
        'table' => TableBlock(
            title: j['title'] as String?,
            columns: [for (final c in j['columns'] as List? ?? []) '$c'],
            rows: [for (final r in j['rows'] as List? ?? []) [for (final c in r as List) '$c']],
            note: j['note'] as String?),
        'code' => CodeBlock(language: j['language'] as String? ?? '', title: j['title'] as String?, source: j['source'] as String? ?? ''),
        'file' => FileBlock(
            source: j['source'] as String? ?? 'upload',
            id: j['id'] as String,
            name: j['name'] as String? ?? '',
            mime: j['mime'] as String? ?? 'application/octet-stream',
            size: (j['size'] as num?)?.toInt() ?? 0,
            projectId: j['project_id'] as String?),
        'approval' => ApprovalBlock(
            id: j['id'] as String, title: j['title'] as String? ?? '', detail: j['detail'] as String? ?? '', state: j['state'] as String? ?? 'pending'),
        'browser' => BrowserBlock(j['session'] as String? ?? 'main'),
        'page' => PageBlock(slug: j['slug'] as String, title: j['title'] as String? ?? '', url: j['url'] as String? ?? ''),
        'stats' => StatsBlock([for (final i in (j['items'] as List? ?? [])) StatItem.fromJson(i as Map<String, dynamic>)]),
        _ => UnknownBlock('${j['type']}'),
      };
}

class TextBlock extends Block {
  const TextBlock(this.text);
  final String text;
  TextBlock append(String more) => TextBlock(text + more);
}

class LinkItem {
  const LinkItem({required this.url, this.label, this.title});
  factory LinkItem.fromJson(Map<String, dynamic> j) =>
      LinkItem(url: j['url'] as String, label: j['label'] as String?, title: j['title'] as String?);
  final String url;
  final String? label, title;
}

class LinksBlock extends Block {
  const LinksBlock(this.items);
  final List<LinkItem> items;
}

class TableBlock extends Block {
  const TableBlock({this.title, required this.columns, required this.rows, this.note});
  final String? title, note;
  final List<String> columns;
  final List<List<String>> rows;
}

class CodeBlock extends Block {
  const CodeBlock({required this.language, this.title, required this.source});
  final String language, source;
  final String? title;
}

class FileBlock extends Block {
  const FileBlock({required this.source, required this.id, required this.name, required this.mime, required this.size, this.projectId});
  final String source, id, name, mime;
  final int size;
  final String? projectId;
  bool get isImage => mime.startsWith('image/');

  /// 下载路径（未带 token，由 Api.fileUrl 补上）。
  String get path => source == 'project' ? '/api/projects/$projectId/files/$id' : '/api/uploads/$id';
}

class ApprovalBlock extends Block {
  const ApprovalBlock({required this.id, required this.title, required this.detail, required this.state});
  final String id, title, detail, state;
  bool get pending => state == 'pending';
}

class BrowserBlock extends Block {
  const BrowserBlock(this.session);
  final String session;
}

class PageBlock extends Block {
  const PageBlock({required this.slug, required this.title, required this.url});
  final String slug, title, url;
}

class StatItem {
  const StatItem({required this.label, required this.value, this.note});
  factory StatItem.fromJson(Map<String, dynamic> j) =>
      StatItem(label: j['label'] as String? ?? '', value: j['value'] as String? ?? '', note: j['note'] as String?);
  final String label, value;
  final String? note;
}

/// 几个关键数字（面板、简报）：每项一块 标签 + 大数字 的小卡片。
class StatsBlock extends Block {
  const StatsBlock(this.items);
  final List<StatItem> items;
}

class UnknownBlock extends Block {
  const UnknownBlock(this.type);
  final String type;
}

List<Block> blocksFrom(dynamic list) => [for (final b in (list as List? ?? [])) Block.fromJson(b as Map<String, dynamic>)];

String plainText(List<Block> blocks) => blocks.whereType<TextBlock>().map((b) => b.text).join('\n').trim();

/// “复制”一条回复得到的 Markdown（和后端 blocks.py 的 blocks_to_text 同一套规则，表格转成 Markdown 表）。
/// 只复制内容：审批卡、浏览器画面这类过程卡片不进剪贴板。
String copyText(List<Block> blocks) => [
      for (final b in blocks)
        switch (b) {
          TextBlock(:final text) => text.trim(),
          CodeBlock(:final language, :final source) => '```$language\n$source\n```',
          TableBlock(:final title, :final columns, :final rows, :final note) => [
              if (title != null && title.isNotEmpty) '**$title**',
              '| ${columns.join(' | ')} |',
              '|${List.filled(columns.length, ' --- ').join('|')}|',
              for (final r in rows) '| ${r.join(' | ')} |',
              if (note != null && note.isNotEmpty) note,
            ].join('\n'),
          LinksBlock(:final items) => [for (final i in items) '- ${i.title ?? i.label ?? i.url} ${i.url}'].join('\n'),
          PageBlock(:final title, :final url) => '$title $url',
          FileBlock(:final name) => '[文件：$name]',
          StatsBlock(:final items) => [for (final i in items) '${i.label}：${i.value}${i.note != null && i.note!.isNotEmpty ? '（${i.note}）' : ''}'].join('\n'),
          _ => '',
        },
    ].where((s) => s.isNotEmpty).join('\n\n');
