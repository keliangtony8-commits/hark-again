// 新面板弹层：主页上“往主页加东西”的唯一入口（顶栏左侧 + 和栈底“创建一个新面板”胶囊都开它）。
// 面板由助手按你的描述去搭（选数据源、定刷新节奏），所以输入框只问“想看什么”，然后交给聊天。
// v2.78 Home 重做：原来散在主页上的几样都收进这里，主页只剩卡片——
//   · 起点胶囊（panelIdeas）：点一个直接交给聊天去搭；
//   · “每天早上的简报”：还没排早间简报时出现，点了打开预填好的定时任务表单（每天 07:00，可改）；
//   · 最近移除的面板（removed_panels.dart 的规则，30 天内）：点一个放回主页。
// 网页版 features/home/NewPanelSheet.tsx 同一组内容、同一顺序。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../chat/open_conversation.dart';
import '../me/tasks_screen.dart' show createTask;
import 'removed_panels.dart';
import 'today_agenda.dart' show briefTaskOf, morningBrief;

String newPanelPrompt(String what) => '帮我在主页做一个面板：$what';

/// 起点（点一下就交给聊天去搭）。网页版 NewPanelSheet.tsx panelIdeas 同一组。
const panelIdeas = ['明天的天气', '美元兑人民币汇率', '我的快递到哪了', '今天的课表和作业'];

/// 弹层里“排早间简报”那颗胶囊的字（还没排时才出现）。
const briefIdeaLabel = '每天早上的简报';

Future<void> createPanel(BuildContext context, WidgetRef ref) async {
  final tasks = ref.read(tasksProvider).value ?? const <ScheduledTask>[];
  final removed = removedPanels(ref.read(cardsProvider).value ?? const <HomeCard>[]);
  // 弹层里点了胶囊/找回：先关弹层，回到主页的 context 再做（表单、聊天、提示都挂在主页上）
  Future<void> Function()? after;
  void close(BuildContext sheet, Future<void> Function() then) {
    after = then;
    Navigator.pop(sheet);
  }

  final v = await showFormSheet(
    context,
    title: '新面板',
    subtitle: '描述想在主页查看的内容，我会查找数据并设定刷新频率。',
    submit: '开始做',
    fields: const [FieldSpec('what', '想看什么', hint: '比如：每天早上的天气和课表', lines: 2)],
    extra: Builder(
      builder: (sheet) => NewPanelExtras(
        briefMissing: briefTaskOf(tasks) == null,
        removed: removed,
        onIdea: (what) => close(sheet, () async => askInNewChat(context, ref, newPanelPrompt(what))),
        onBrief: () => close(sheet, () => createTask(context, ref, starter: morningBrief)),
        onRevive: (c) => close(sheet, () async => revivePanel(context, ref, c)),
      ),
    ),
  );
  if (!context.mounted) return;
  final then = after;
  if (then != null) return then();
  if (v == null) return;
  askInNewChat(context, ref, newPanelPrompt(v['what']!));
}

/// 弹层输入框下面的几样（纯展示 + 回调，测试直接 pump）。回调由 createPanel 接：先关弹层，再在主页上做。
class NewPanelExtras extends StatelessWidget {
  const NewPanelExtras(
      {super.key, required this.briefMissing, required this.removed, required this.onIdea, required this.onBrief, required this.onRevive, this.now});
  final bool briefMissing;
  final List<HomeCard> removed;
  final ValueChanged<String> onIdea;
  final VoidCallback onBrief;
  final ValueChanged<HomeCard> onRevive;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
        for (var i = 0; i < panelIdeas.length; i++)
          FadeSlideIn(
              delay: Motion.stagger(i, from: 1),
              child: GlassChip(label: panelIdeas[i], onTap: () => onIdea(panelIdeas[i]))),
        if (briefMissing)
          FadeSlideIn(
              delay: Motion.stagger(panelIdeas.length, from: 1),
              child: GlassChip(label: briefIdeaLabel, onTap: onBrief)),
      ]),
      if (removed.isNotEmpty) ...[
        const SizedBox(height: Sp.x4),
        Text('最近移除 · 30 天内可放回', style: context.text.labelSmall),
        const SizedBox(height: Sp.x1),
        for (final c in removed)
          Pressable(
            onTap: () => onRevive(c),
            semanticLabel: '放回「${c.title}」',
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: A11y.minTap),
              child: Row(children: [
                Icon(Icons.restore_rounded, size: Fs.md, color: p.text3),
                const SizedBox(width: Sp.x2),
                Expanded(child: Text(c.title, style: context.text.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
                if (c.removedAt != null) Text('移除于 ${formatWhen(c.removedAt, now: now)}', style: context.text.labelSmall),
              ]),
            ),
          ),
      ],
    ]);
  }
}
