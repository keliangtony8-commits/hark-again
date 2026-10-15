// 本对话全部文件（v1.33）：服务器 app/conversation_files.py 收拢一段对话里出现过的所有文件，这里只有展示规则——
// 来源叫什么、一行副标题怎么写、点开去哪、能不能打包。网页 lib/conversationFiles.ts 同义。
import '../core/workspace.dart';
import '../ui/format.dart';

/// 来源（服务器 origin）→ 用户看到的叫法，顺序 = 筛选条里的顺序。
const fileOrigins = <String, String>{
  'delivered': '交给你的',
  'sent': '你发的',
  'downloaded': '网页下载',
  'to_web': '传到网页',
  'written': '助手写的',
};

String fileOriginLabel(String origin) => fileOrigins[origin] ?? '文件';

class ConversationFile {
  const ConversationFile({
    required this.key,
    required this.name,
    required this.mime,
    required this.size,
    required this.source,
    required this.id,
    required this.origin,
    this.projectId,
    this.messageId,
    this.at,
    this.gone = false,
  });

  factory ConversationFile.fromJson(Map<String, dynamic> j) => ConversationFile(
        key: j['key'] as String? ?? '${j['source']}:${j['id']}',
        name: j['name'] as String? ?? '文件',
        mime: j['mime'] as String? ?? 'application/octet-stream',
        size: (j['size'] as num?)?.toInt() ?? 0,
        source: j['source'] as String? ?? 'upload',
        id: j['id'] as String? ?? '',
        origin: j['origin'] as String? ?? 'delivered',
        projectId: j['project_id'] as String?,
        messageId: j['message_id'] as String?,
        at: DateTime.tryParse(j['at'] as String? ?? '')?.toLocal(),
        gone: j['gone'] == true,
      );

  final String key, name, mime, source, id, origin;
  final int size;
  final String? projectId, messageId;
  final DateTime? at;

  /// 文件已经不在了（工作区里删掉/挪走）：照样列出，但打不开、不进 zip。
  final bool gone;

  bool get isWorkspace => source == 'project';
}

class ConversationFiles {
  const ConversationFiles({required this.files, required this.available, required this.size, required this.zipMax});

  factory ConversationFiles.fromJson(Map<String, dynamic> j) => ConversationFiles(
        files: [for (final f in (j['files'] as List? ?? const [])) ConversationFile.fromJson((f as Map).cast<String, dynamic>())],
        available: (j['available'] as num?)?.toInt() ?? 0,
        size: (j['size'] as num?)?.toInt() ?? 0,
        zipMax: (j['zip_max'] as num?)?.toInt() ?? 0,
      );

  final List<ConversationFile> files;
  final int available, size, zipMax;

  /// 列表里出现过的来源（按 fileOrigins 顺序）及数量；只有一种来源时不显示筛选条。
  List<(String, int)> get origins => [
        for (final o in fileOrigins.keys)
          if (files.where((f) => f.origin == o).length case final n when n > 0) (o, n),
      ];

  /// 打包下载能不能点：有还在的文件、且总大小不超过服务器的打包上限（0 = 老服务器没给，按能点）。
  bool get canZip => available > 0 && (zipMax <= 0 || size <= zipMax);

  /// 打包按钮下那一行（不能点时说为什么）。
  String get zipNote {
    if (available == 0) return '文件均已删除，无法打包';
    if (!canZip) return '一共 ${formatSize(size)}，超过打包上限 ${formatSize(zipMax)}，请逐个下载';
    return '$available 个文件 · ${formatSize(size)}';
  }
}

/// 一行副标题：来源 · 种类 · 大小（不在了 → 由 ListRow.problem 显示“已不在”，这里只给来源）。
String conversationFileLine(ConversationFile f) => f.gone
    ? '${fileOriginLabel(f.origin)} · ${f.isWorkspace ? '已从工作区删除或挪走' : '存储里已清掉'}'
    : [fileOriginLabel(f.origin), fileKind(f.name, f.mime), formatSize(f.size)].where((s) => s.isNotEmpty).join(' · ');

/// 下载路径（未带 token，由 Api.fileUrl 补上）：上传快照 / 工作区文件，和文件卡同一套接口。
String conversationFilePath(ConversationFile f) =>
    f.isWorkspace ? workspaceFilePath(f.projectId ?? personalWorkspace, f.id) : '/api/uploads/${Uri.encodeComponent(f.id)}';

String conversationFilesPath(String conversationId) => '/api/conversations/$conversationId/files';

String conversationZipPath(String conversationId) => '/api/conversations/$conversationId/files.zip';

String conversationFileSemantics(ConversationFile f) =>
    '${f.name}，${conversationFileLine(f)}${f.gone ? '，已不在，打不开' : ''}';
