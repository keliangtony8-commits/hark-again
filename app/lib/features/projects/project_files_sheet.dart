// 项目文件：项目文件夹里的资料（我和沙箱共用）。上传、打开、删除。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/links.dart';
import '../../core/media.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 文件图标（按 mime 大类）——项目首屏和文件抽屉共用。
IconData projectFileIcon(String mime) => switch (mime.split('/').first) {
  'image' => Icons.image_outlined,
  'audio' => Icons.audiotrack_outlined,
  'video' => Icons.movie_outlined,
  'text' => Icons.description_outlined,
  _ => mime.contains('pdf') ? Icons.picture_as_pdf_outlined : Icons.insert_drive_file_outlined,
};

/// 打开项目文件（带 token 的下载地址，交给系统）——唯一入口。
Future<void> openProjectFile(WidgetRef ref, String projectId, ProjectFile f) {
  final path = f.path.split('/').map(Uri.encodeComponent).join('/');
  return openUrl(ref.read(apiProvider).fileUrl('/api/projects/$projectId/files/$path'));
}

Future<void> showProjectFiles(BuildContext context, String projectId) => showAppScrollSheet<void>(
  context,
  initial: 0.7,
  builder: (_, scroll) => _ProjectFiles(projectId: projectId, scroll: scroll),
);

class _ProjectFiles extends ConsumerStatefulWidget {
  const _ProjectFiles({required this.projectId, required this.scroll});
  final String projectId;
  final ScrollController scroll;

  @override
  ConsumerState<_ProjectFiles> createState() => _ProjectFilesState();
}

class _ProjectFilesState extends ConsumerState<_ProjectFiles> {
  int _uploading = 0;

  Future<void> _upload() async {
    final media = ref.read(mediaProvider);
    final files = await media.pick(PickSource.file);
    if (files.isEmpty) return;
    setState(() => _uploading += files.length);
    try {
      for (final f in files) {
        await media.uploadToProject(widget.projectId, f);
        if (mounted) setState(() => _uploading--);
      }
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _uploading = 0);
      await ref.read(projectFilesProvider(widget.projectId).notifier).reload();
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = projectFilesProvider(widget.projectId);
    final files = ref.watch(provider);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x3, Sp.x2),
          child: Row(
            children: [
              Expanded(child: Text('项目文件', style: context.text.titleLarge)),
              AnimatedSwitcher(
                duration: Motion.base,
                child: _uploading > 0
                    ? Padding(
                        key: const ValueKey('up'),
                        padding: const EdgeInsets.symmetric(horizontal: Sp.x3),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            PulseDot(color: context.palette.accent),
                            const SizedBox(width: Sp.x2),
                            Text('上传中 $_uploading', style: context.text.labelSmall),
                          ],
                        ),
                      )
                    : TextButton.icon(
                        key: const ValueKey('btn'),
                        onPressed: _upload,
                        icon: const Icon(Icons.upload_rounded, size: 18),
                        label: const Text('上传'),
                      ),
              ),
            ],
          ),
        ),
        Expanded(
          child: switch (files) {
            AsyncData(:final value) when value.isEmpty => const EmptyHint(
              icon: Icons.folder_open_rounded,
              title: '文件夹是空的',
              text: '上传资料后，在这个项目里聊天时我可以直接读它们，也能在沙箱里跑代码处理。',
            ),
            AsyncData(:final value) => ListView(
              controller: widget.scroll,
              padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x5),
              children: [
                ListGroup(
                  children: [
                    for (final (i, f) in value.indexed)
                      SwipeToDelete(
                        id: f.path,
                        confirm: () => confirmDanger(context, title: '删除 ${f.name}？'),
                        onDelete: () => ref.read(provider.notifier).remove(f.path),
                        child: FadeSlideIn(
                          delay: Motion.stagger(i),
                          child: RowTile(
                            icon: projectFileIcon(f.mime),
                            title: f.path,
                            subtitle: formatSize(f.size),
                            trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                            onTap: () => openProjectFile(ref, widget.projectId, f),
                          ),
                        ),
                      ),
                  ],
                ),
              ],
            ),
            AsyncError(:final error) => EmptyHint(icon: Icons.cloud_off_rounded, title: '加载失败', text: '$error'),
            _ => const Padding(padding: EdgeInsets.all(Sp.x4), child: SkeletonList()),
          },
        ),
      ],
    );
  }
}
