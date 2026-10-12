// 项目文件：项目文件夹里的资料（我和沙箱共用）。上传、打开、删除；聊天输入框“引用项目文件”的选择器也在这里。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/links.dart';
import '../../core/media.dart';
import '../../core/resource.dart';
import '../../models/block.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
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

/// 文件行副标题：所在文件夹（根目录不写）· 大小——项目首屏、文件抽屉、引用选择器共用，标题一律用文件名。
String projectFileLine(ProjectFile f) {
  final slash = f.path.lastIndexOf('/');
  return [if (slash > 0) f.path.substring(0, slash), formatSize(f.size)].join(' · ');
}

/// 打开项目文件（带 token 的下载地址，交给系统）——唯一入口。
Future<void> openProjectFile(WidgetRef ref, String projectId, ProjectFile f) {
  final path = f.path.split('/').map(Uri.encodeComponent).join('/');
  return openUrl(ref.read(apiProvider).fileUrl('/api/projects/$projectId/files/$path'));
}

/// 项目文件在消息里的样子：source=project 的文件块（id = 相对路径）。服务器只认这个对话所在项目里真实存在的文件。
FileBlock projectFileBlock(String projectId, ProjectFile f) =>
    FileBlock(source: 'project', id: f.path, name: f.name, mime: f.mime, size: f.size, projectId: projectId);

/// 一条消息最多带几个文件（上传 + 引用合计，和服务器 ws.MAX_FILES 一致）。
const maxMessageFiles = 10;

/// 选几个项目文件引用到这条消息里——唯一入口。taken = 已经在托盘里的相对路径（显示为已选、不能重复加）；
/// room = 还能加几个。取消 → null；确认 → 新选的（按文件列表顺序）。
Future<List<FileBlock>?> pickProjectFiles(BuildContext context, String projectId,
        {Set<String> taken = const {}, int room = maxMessageFiles}) =>
    showAppScrollSheet<List<FileBlock>>(
      context,
      initial: 0.7,
      builder: (_, scroll) => _FilePicker(projectId: projectId, scroll: scroll, taken: taken, room: room),
    );

class _FilePicker extends ConsumerStatefulWidget {
  const _FilePicker({required this.projectId, required this.scroll, required this.taken, required this.room});
  final String projectId;
  final ScrollController scroll;
  final Set<String> taken;
  final int room;

  @override
  ConsumerState<_FilePicker> createState() => _FilePickerState();
}

class _FilePickerState extends ConsumerState<_FilePicker> {
  final _chosen = <String>{};

  void _toggle(ProjectFile f) {
    if (widget.taken.contains(f.path)) return;
    setState(() {
      if (!_chosen.remove(f.path)) {
        if (_chosen.length >= widget.room) {
          showToast(context, '一条消息最多带 $maxMessageFiles 个文件');
          return;
        }
        _chosen.add(f.path);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final files = ref.watch(projectFilesProvider(widget.projectId));
    final list = files.value ?? const <ProjectFile>[];
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x1),
        child: Row(children: [
          Expanded(child: Text('引用项目文件', style: context.text.titleLarge)),
          SwapSwitcher(
            child: Text(_chosen.isEmpty ? '可多选' : '已选 ${_chosen.length}',
                key: ValueKey(_chosen.length), style: context.text.labelSmall),
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x3),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text('我读的是文件当前的内容，之后改了也会读到新的。', style: context.text.bodySmall),
        ),
      ),
      Expanded(
        child: switch (files) {
          AsyncData(:final value) when value.isEmpty => const EmptyHint(
            icon: Icons.folder_open_rounded,
            title: '文件夹是空的',
            text: '先在项目的“文件”里上传资料，再回来引用。',
          ),
          AsyncData() => ListView(
            controller: widget.scroll,
            padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x3),
            children: [
              ListGroup(children: [
                for (final (i, f) in list.indexed)
                  FadeSlideIn(
                    delay: Motion.stagger(i),
                    child: _PickRow(
                      file: f,
                      taken: widget.taken.contains(f.path),
                      chosen: _chosen.contains(f.path),
                      onTap: () => _toggle(f),
                    ),
                  ),
              ]),
            ],
          ),
          AsyncError(:final error) => EmptyHint(icon: Icons.cloud_off_rounded, title: '加载失败', text: '$error'),
          _ => const Padding(padding: EdgeInsets.all(Sp.x4), child: SkeletonList()),
        },
      ),
      SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, Sp.x4),
          child: SizedBox(
            width: double.infinity,
            child: PillButton(
              primary: true,
              icon: Icons.attach_file_rounded,
              label: _chosen.isEmpty ? '选几个文件' : '引用 ${_chosen.length} 个文件',
              onTap: _chosen.isEmpty
                  ? null
                  : () => Navigator.pop(context, [
                        for (final f in list)
                          if (_chosen.contains(f.path)) projectFileBlock(widget.projectId, f),
                      ]),
            ),
          ),
        ),
      ),
    ]);
  }
}

class _PickRow extends StatelessWidget {
  const _PickRow({required this.file, required this.taken, required this.chosen, required this.onTap});
  final ProjectFile file;
  final bool taken, chosen;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final on = taken || chosen;
    return Semantics(
      checked: on,
      enabled: !taken,
      child: RowTile(
        icon: projectFileIcon(file.mime),
        title: file.name,
        subtitle: taken ? '已在这条消息里' : [projectFileLine(file), if (file.modified != null) formatAgo(file.modified!)].join(' · '),
        dimmed: taken,
        onTap: taken ? null : onTap,
        trailing: SwapSwitcher(
          child: Icon(
            on ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
            key: ValueKey(on),
            size: 22,
            color: on ? p.ink : p.text3,
          ),
        ),
      ),
    );
  }
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
                            title: f.name,
                            subtitle: projectFileLine(f),
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
