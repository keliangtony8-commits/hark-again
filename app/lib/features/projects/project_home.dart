// 项目首屏（v2.93 §Q 按 Hark 重做）：项目里还没打开对话时显示，也就是“在本项目开新对话”的空白态。
// 只做一件事：列出本项目的全部对话（置顶在前，再按更新时间），行尾是状态胶囊（v2.91，没有状态写相对时间），点开续聊；
// 底下的输入框（ChatView 那一个）= 在本项目开新对话。项目名在顶栏下的 header 行，这里不重复。
// 文件、电脑、规则与档案都在 header 行 ⋯ 里（showProjectMenu），首屏不再分节画。
// 双栏时对话列表已常驻左侧，这里只留一行提示，不重复列。入场 FadeSlideIn 错峰。
// 排序规则是纯函数 projectConversations，测试直接测。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/adaptive.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../chat/chat_controller.dart';
import '../chat/status_capsule.dart';

/// 首屏的对话顺序：置顶优先，其余按更新时间新→旧（没有时间的排后，顺序稳定）。
List<ConversationSummary> projectConversations(List<ConversationSummary> list) {
  final epoch = DateTime.fromMillisecondsSinceEpoch(0);
  final indexed = list.indexed.toList()
    ..sort((a, b) {
      if (a.$2.pinned != b.$2.pinned) return a.$2.pinned ? -1 : 1;
      final t = (b.$2.updatedAt ?? epoch).compareTo(a.$2.updatedAt ?? epoch);
      return t != 0 ? t : a.$1.compareTo(b.$1);
    });
  return [for (final e in indexed) e.$2];
}

class ProjectHome extends ConsumerWidget {
  const ProjectHome({super.key, required this.projectId});
  final String projectId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final chat = ref.watch(chatProvider(projectId));
    final twoPane = context.window.twoPane; // 双栏：对话列表已在左边
    final all = projectConversations(chat.conversations);
    final Widget content;
    if (twoPane || all.isEmpty) {
      content = Padding(
        key: const ValueKey('hint'),
        padding: const EdgeInsets.only(top: Sp.x2),
        child: Text(
          all.isEmpty ? '这个项目还没有对话。在下方输入，开始第一段。' : '从左侧选择一段对话继续，或在下方开始新的对话。',
          style: context.text.bodyMedium?.copyWith(color: p.text2),
        ),
      );
    } else {
      content = GlassGroup(key: const ValueKey('list'), children: [
        for (final c in all)
          RowTile(
            key: ValueKey('conv-${c.id}'),
            icon: c.pinned ? Icons.push_pin_outlined : Icons.forum_outlined,
            title: c.title,
            // 有状态画胶囊（代替时间），没有才写“几分钟前”
            trailing: c.status != null ? StatusCapsule(c.status!) : c.updatedAt == null ? null : RowHint(formatAgo(c.updatedAt)),
            onTap: () => ref.read(chatProvider(projectId).notifier).open(c.id),
          ),
      ]);
    }

    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Layout.contentMax),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, 0, Layout.gutter, Sp.x5), // 上方让位已由 ChatView 按 header 行算好
          children: [
            FadeSlideIn(child: SectionTitle(all.isEmpty ? '对话' : '对话 · ${all.length}')),
            FadeSlideIn(delay: Motion.stagger(1), child: content),
          ],
        ),
      ),
    );
  }
}
