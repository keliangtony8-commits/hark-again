// 把一条回复存成文件（v1.15；v1.21 主聊天可存进“我的文件”）——App 里唯一入口（服务器 reply_files.py：Markdown、
// 文件名取标题、同名不覆盖）。项目对话 → 直接存进本项目；主聊天 → 选“我的文件”或某个项目（我的文件在最前，
// 项目按最近活跃）；一个项目都没有 → 不用选，直接存进我的文件。
// 存好：提示条“已存进「我的文件 / 项目」· 文件名”，并刷新那个工作区的文件列表（首页“文件”一节、引用选择器立刻看到）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../core/workspace.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 操作键的文字（App / 网页同一句）。
const saveReplyLabel = '存成文件';

/// 选项目时的顺序：最近活跃的在前，没有时间的排后，其余保持原顺序。
List<Project> saveTargets(List<Project> projects) {
  final list = [...projects];
  final at = {for (final (i, p) in list.indexed) p.id: i};
  list.sort((a, b) {
    final x = a.activeAt, y = b.activeAt;
    if (x == null || y == null) return x == y ? at[a.id]!.compareTo(at[b.id]!) : (x == null ? 1 : -1);
    final c = y.compareTo(x);
    return c != 0 ? c : at[a.id]!.compareTo(at[b.id]!);
  });
  return list;
}

/// 存好后提示条上的那句话。
String savedReplyText(String projectName, String fileName) => '已存进「$projectName」· $fileName';

/// 把 [messageId] 这条回复存成文件。[projectId] 为空 = 主聊天：选我的文件或某个项目（没有项目就直接存进我的文件）。
Future<void> saveReplyToProject(BuildContext context, WidgetRef ref, {required String messageId, String projectId = ''}) async {
  var pid = projectId;
  if (pid.isEmpty) {
    List<Project> projects;
    try {
      projects = await ref.read(projectsProvider.future);
    } catch (_) {
      projects = const []; // 项目列表拿不到也能存进我的文件
    }
    if (!context.mounted) return;
    final chosen = projects.isEmpty
        ? personalWorkspace
        : await showAppScrollSheet<String>(context, title: '存到哪里', builder: (_) => _ProjectPicker(projects: saveTargets(projects)));
    if (chosen == null) return;
    pid = chosen;
  }
  try {
    final r = await ref.read(apiProvider).post('/api/messages/$messageId/save-to-project', {'project_id': pid}) as Map<String, dynamic>;
    final saved = r['project_id'] as String? ?? pid;
    if (context.mounted) showToast(context, savedReplyText(r['project_name'] as String? ?? '项目', r['name'] as String? ?? ''));
    // 打开过这个项目的文件列表才需要刷新；没打开过下次进去自然是新的
    if (ref.exists(projectFilesProvider(saved))) await ref.read(projectFilesProvider(saved).notifier).reload();
  } catch (e) {
    if (context.mounted) showToast(context, e is ApiError ? e.message : '没存上，稍后再试');
  }
}

class _ProjectPicker extends StatelessWidget {
  const _ProjectPicker({required this.projects});
  final List<Project> projects;

  @override
  Widget build(BuildContext context) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x3),
          child: Text('存成一份 Markdown，之后的对话都能引用。', style: context.text.bodySmall),
        ),
        SheetList(
            children: [
              ListGroup(children: [
                FadeSlideIn(
                  child: ListRow(
                    icon: Icons.folder_outlined,
                    title: workspaceFilesTitle(personalWorkspace),
                    subtitle: '主聊天的云端电脑',
                    onTap: () => Navigator.pop(context, personalWorkspace),
                  ),
                ),
                for (final (i, p) in projects.indexed)
                  FadeSlideIn(
                    delay: Motion.stagger(i + 1),
                    child: ListRow(
                      leading: SizedBox.square(
                        dimension: Layout.rowIcon,
                        child: Center(child: Text(p.emoji, style: context.text.titleMedium?.copyWith(fontSize: Fs.lg))),
                      ),
                      title: p.name,
                      trailing: p.activeAt == null ? null : RowHint(formatAgo(p.activeAt!)),
                      onTap: () => Navigator.pop(context, p.id),
                    ),
                  ),
              ]),
            ],
        ),
      ]);
}
