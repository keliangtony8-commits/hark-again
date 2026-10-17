// 新建面板：主页上“往主页加东西”的唯一入口（顶栏左侧 + 和栈底“创建一个新面板”胶囊都开它）。
// v3.5.1 照 Hark：不再是白底弹层，而是主页底部输入胶囊的一种发起态模式（shell/launch_composer.dart LaunchMode）——
// 整页磨砂、键盘弹出，输入框上方一行“创建一个新面板”，占位词在面板示例之间轮播，发出 = newPanelPrompt 交给新对话。
// 面板由助手按你的描述去搭（选数据源、定刷新节奏），所以输入只问“想看什么”。原来建议问题那一格换成：
//   · 起点胶囊（panelIdeas）：点一个直接交给聊天去搭；
//   · “每天早上的简报”：还没排早间简报时出现，点了打开预填好的定时任务表单（每天 07:00，可改）；
//   · 最近移除的面板（removed_panels.dart 的规则，30 天内）：点一个放回主页。
// 网页版 features/home/newPanel.tsx 同一组内容、同一顺序、同一文案。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../shell/launch_composer.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../me/tasks_screen.dart' show createTask;
import 'removed_panels.dart';
import 'today_agenda.dart' show briefTaskOf, morningBrief;

String newPanelPrompt(String what) => '帮我在主页做一个面板：$what';

/// 起点（点一下就交给聊天去搭；也是输入框占位词轮播的那几句）。网页版 newPanel.tsx panelIdeas 同一组。
const panelIdeas = ['明天的天气', '美元兑人民币汇率', '我的快递到哪了', '今天的课表和作业'];

/// 示例胶囊的图标（Hark 示例前带图标），和 panelIdeas 一一对应；网页 newPanel.tsx IDEA_ICONS 同形。
const _ideaIcons = [Icons.wb_sunny_outlined, Icons.swap_horiz_rounded, Icons.shopping_bag_outlined, Icons.description_outlined];

/// “排早间简报”那颗胶囊的字（还没排时才出现）。
const briefIdeaLabel = '每天早上的简报';

/// 输入框上方的小字。
const newPanelCaption = '创建一个新面板';

/// 主页的新建面板模式：+ / “创建一个新面板”把主页 LaunchComposer 的 mode 设成它。
final newPanelMode = LaunchMode(
  caption: newPanelCaption,
  hints: panelIdeas,
  hintIcons: _ideaIcons,
  wrap: newPanelPrompt,
  extras: (context, go) => _LiveExtras(go: go),
);

/// 读当前的任务 / 卡片，交给 NewPanelExtras；点了先收起输入框，再在主页的 context 上做。
class _LiveExtras extends ConsumerWidget {
  const _LiveExtras({required this.go});
  final LaunchActions go;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(tasksProvider).value ?? const <ScheduledTask>[];
    final removed = removedPanels(ref.watch(cardsProvider).value ?? const <HomeCard>[]);
    return NewPanelExtras(
      briefMissing: briefTaskOf(tasks) == null,
      removed: removed,
      onIdea: go.ask,
      onBrief: () => go.then((context, ref) => createTask(context, ref, starter: morningBrief)),
      onRevive: (c) => go.then((context, ref) async => revivePanel(context, ref, c)),
    );
  }
}

/// 输入框上方的胶囊们（纯展示 + 回调，测试直接 pump）：最近移除（有才出，在上）→ 示例 + 早间简报（贴着小字）。
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
    final ideas = [
      for (var i = 0; i < panelIdeas.length; i++) GlassChip(label: panelIdeas[i], icon: _ideaIcons[i], onTap: () => onIdea(panelIdeas[i])),
      if (briefMissing) GlassChip(label: briefIdeaLabel, icon: Icons.alarm_rounded, onTap: onBrief),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (removed.isNotEmpty) ...[
        Padding(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, Sp.x2, Layout.gutter, 0),
          child: Text('最近移除 · 30 天内可放回', style: context.text.labelSmall?.copyWith(color: context.palette.text3)),
        ),
        LaunchChipRow(children: [
          for (final c in removed)
            GlassChip(
              label: c.title,
              icon: Icons.history_rounded,
              detail: c.removedAt == null ? null : formatWhen(c.removedAt, now: now),
              semanticLabel: '放回「${c.title}」${c.removedAt == null ? '' : '，移除于 ${formatWhen(c.removedAt, now: now)}'}',
              onTap: () => onRevive(c),
            ),
        ]),
      ],
      LaunchChipRow(from: removed.isEmpty ? 0 : removed.length, children: ideas),
    ]);
  }
}
