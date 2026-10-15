// 本对话全部文件（v1.33，对标 Manus“查看本任务全部文件”）：一张长列表弹层，列出这段对话里出现过的所有文件——
// 交给你的成果、你发的附件、浏览器下载/上传的、助手写的——最新在前，可按来源筛选，一键打包下载。
// 入口两个，都只调 showConversationFiles：顶栏标题弹出的本对话用量页右上角、历史面板长按菜单“全部文件”。
// 数据只读：GET /api/conversations/{id}/files；规则全在 models/conversation_files.dart。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/links.dart';
import '../../models/conversation_files.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../projects/project_files_sheet.dart' show projectFileIcon;

final conversationFilesProvider = FutureProvider.autoDispose.family<ConversationFiles, String>(
  (ref, id) async =>
      ConversationFiles.fromJson((await ref.read(apiProvider).get(conversationFilesPath(id)) as Map).cast<String, dynamic>()),
);

Future<void> showConversationFiles(BuildContext context, String id) =>
    showAppScrollSheet<void>(context, builder: (_) => ConversationFilesSheet(id: id));

class ConversationFilesSheet extends ConsumerStatefulWidget {
  const ConversationFilesSheet({super.key, required this.id});
  final String id;

  @override
  ConsumerState<ConversationFilesSheet> createState() => _ConversationFilesSheetState();
}

class _ConversationFilesSheetState extends ConsumerState<ConversationFilesSheet> {
  String? _origin; // 筛选：null = 全部

  void _open(ConversationFile f) {
    if (f.gone) return;
    openUrl(ref.read(apiProvider).fileUrl(conversationFilePath(f)));
  }

  @override
  Widget build(BuildContext context) {
    final value = ref.watch(conversationFilesProvider(widget.id));
    final data = value.value;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x3, Sp.x1),
          child: Row(
            children: [
              Expanded(child: Text('本对话全部文件', style: context.text.titleLarge)),
              FadeSwitcher(
                child: data == null || data.files.isEmpty
                    ? const SizedBox(key: ValueKey('no-zip'), height: A11y.minTap)
                    : TextButton.icon(
                        key: const ValueKey('zip'),
                        onPressed: data.canZip ? () => openUrl(ref.read(apiProvider).fileUrl(conversationZipPath(widget.id))) : null,
                        icon: const Icon(Icons.folder_zip_outlined, size: 18),
                        label: const Text('打包下载'),
                      ),
              ),
            ],
          ),
        ),
        // 不套切换动画：数据态是 Flexible（SheetList 要直接挂在 Column 下）；行自己 FadeSlideIn 交错进场
        switch (value) {
          AsyncData(:final value) when value.files.isEmpty => const EmptyHint(
            key: ValueKey('empty'),
            icon: Icons.folder_open_rounded,
            title: '这个对话还没有文件',
            text: '你发的附件、我交给你的成果、浏览器下载的文件和我写出来的文件，都会收在这里。',
          ),
          AsyncData(:final value) => _Body(
            key: const ValueKey('data'),
            data: value,
            origin: _origin,
            onOrigin: (o) => setState(() => _origin = o),
            onOpen: _open,
          ),
          AsyncError(:final error) => EmptyHint(
            key: const ValueKey('error'),
            icon: Icons.cloud_off_rounded,
            title: '加载失败',
            text: '$error',
            action: OutlinedButton(onPressed: () => ref.invalidate(conversationFilesProvider(widget.id)), child: const Text('重试')),
          ),
          _ => const Padding(key: ValueKey('loading'), padding: EdgeInsets.all(Sp.x4), child: SkeletonList()),
        },
      ],
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({super.key, required this.data, required this.origin, required this.onOrigin, required this.onOpen});
  final ConversationFiles data;
  final String? origin;
  final ValueChanged<String?> onOrigin;
  final ValueChanged<ConversationFile> onOpen;

  @override
  Widget build(BuildContext context) {
    final origins = data.origins;
    final shown = origin == null ? data.files : data.files.where((f) => f.origin == origin).toList();
    return Flexible(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x3),
            child: Text(data.zipNote, style: context.text.bodySmall),
          ),
          if (origins.length > 1)
            Padding(
              padding: const EdgeInsets.only(bottom: Sp.x3),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: Sp.x4),
                child: Row(
                  children: [
                    _chip('全部 ${data.files.length}', origin == null, () => onOrigin(null)),
                    for (final (o, n) in origins) _chip('${fileOriginLabel(o)} $n', origin == o, () => onOrigin(origin == o ? null : o)),
                  ],
                ),
              ),
            ),
          SheetList(
            padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x5),
            children: [
              AnimatedSize(
                duration: context.motion(Motion.base),
                curve: Motion.ease,
                alignment: Alignment.topCenter,
                child: ListGroup(
                  key: ValueKey(origin),
                  children: [
                    for (final (i, f) in shown.indexed)
                      FadeSlideIn(
                        key: ValueKey(f.key),
                        delay: Motion.stagger(i),
                        child: Semantics(
                          label: conversationFileSemantics(f),
                          button: !f.gone,
                          excludeSemantics: true,
                          child: ListRow(
                            icon: projectFileIcon(f.mime),
                            title: f.name,
                            problem: f.gone ? '已不在' : null,
                            subtitle: conversationFileLine(f),
                            dimmed: f.gone,
                            trailing: f.gone ? null : const Icon(Icons.open_in_new_rounded, size: 18),
                            onTap: f.gone ? null : () => onOpen(f),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _chip(String label, bool on, VoidCallback onTap) => Padding(
    padding: const EdgeInsets.only(right: Sp.x2),
    child: ChoiceChip(label: Text(label), selected: on, onSelected: (_) => onTap(), showCheckmark: false),
  );
}
