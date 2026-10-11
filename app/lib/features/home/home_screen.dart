// Home：一屏看完今天要紧的事。从上到下：问候 → 为你准备（+ 稍后提醒一行）→ 面板（+ 创建一个新面板）→ 收件箱 → 今天（日程）。输入在底部全局胶囊。
// 全部是玻璃卡（ui/glass.dart），卡间距 Layout.cardGap，左右留白 Layout.gutter。
// 与网页版 HomeScreen 同一套信息架构。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../blocks/block_view.dart';
import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/block.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../shell/shell_page.dart';
import '../../ui/glass.dart';
import '../../ui/format.dart';
import '../../shell/launch_composer.dart';
import '../chat/open_conversation.dart';
import 'action_card.dart';
import 'card_snooze.dart';
import 'inbox.dart';
import '../me/task_form.dart';
import 'new_panel.dart';
import 'today_agenda.dart';

String hm(DateTime? t) => t == null ? '' : '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  Timer? _poll;

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  /// 建议卡上的“去做”：开一段新对话发出去，然后切到聊天。
  void _send(String text) => askInNewChat(context, ref, text);

  void _openOffer(String id, String? send) => openConversation(context, ref, id, send: send);

  void _openReport(HomeCard c) {
    if (c.conversationId != null) openInboxItem(context, ref, conversationId: c.conversationId);
  }

  Future<void> _refreshAll() async {
    await Future.wait([
      ref.read(cardsProvider.notifier).reload(),
      ref.read(tasksProvider.notifier).reload(),
      ref.read(inboxProvider.notifier).refresh(),
    ]);
  }

  /// 有面板在刷新时每 5 秒拉一次，刷完自动停。
  void _syncPolling(bool anyRefreshing) {
    if (anyRefreshing && _poll == null) {
      _poll = Timer.periodic(const Duration(seconds: 5), (_) => _refreshAll());
    } else if (!anyRefreshing && _poll != null) {
      _poll!.cancel();
      _poll = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final cards = ref.watch(cardsProvider);
    final tasks = ref.watch(tasksProvider).value ?? const <ScheduledTask>[];
    final refreshing = {for (final t in tasks) if (t.runRequested) t.id};
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncPolling(refreshing.isNotEmpty));

    final all = (cards.value ?? const <HomeCard>[]).where((c) => !c.dismissed);
    final snoozed = all.where((c) => c.snoozed && c.kind == 'action').toList(); // 稍后提醒中：只显示一行入口
    final items = all.where((c) => !c.snoozed).toList();
    final actions = items.where((c) => c.kind == 'action').toList();
    final panels = items.where((c) => c.kind == 'panel').toList();
    final reports = items.where((c) => c.kind == 'report').take(5).toList();
    final unread = ref.watch(inboxProvider.select((s) => s.unread));

    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      body: ShellPage(
        lead: GlassIconButton(icon: Icons.add_rounded, tooltip: '新建面板', onTap: () => createPanel(context, ref)),
        // 底部输入胶囊（设计 v2）代替了原来问候下面的输入框
        child: LaunchComposer(
          child: PullRefresh(
          onRefresh: _refreshAll,
          child: PageBody(children: [
            const _Hero(),
            const SectionTitle('为你准备'),
            // 每一段都是“骨架 → 内容 / 空状态”交叉淡化（FadeSwitcher），同一态里的更新不再过渡；卡片错峰浮上来
            FadeSwitcher(
              child: cards.isLoading
                  ? const SkeletonList(key: ValueKey('loading'), rows: 2)
                  : actions.isEmpty && snoozed.isEmpty
                      ? const _Onboarding(key: ValueKey('empty'))
                      : Column(key: const ValueKey('list'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                          for (var i = 0; i < actions.length; i++)
                            FadeSlideIn(delay: Motion.stagger(i), child: ActionCard(card: actions[i], onDo: _send, onOpen: _openOffer)),
                        ]),
            ),
            SnoozedCards(cards: snoozed),
            const SectionTitle('面板'),
            FadeSwitcher(
              child: cards.isLoading
                  ? const SkeletonList(key: ValueKey('loading'), rows: 1)
                  : panels.isEmpty
                      ? _PanelIdeas(key: const ValueKey('empty'), onPick: (idea) => _send(newPanelPrompt(idea)))
                      : Column(key: const ValueKey('list'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                          for (var i = 0; i < panels.length; i++)
                            FadeSlideIn(
                              delay: Motion.stagger(i),
                              child: _PanelCard(
                                  card: panels[i], refreshing: panels[i].taskId != null && refreshing.contains(panels[i].taskId)),
                            ),
                        ]),
            ),
            FadeSlideIn(
              delay: Motion.stagger(panels.length),
              child: WidePill(icon: Icons.add_rounded, label: '创建一个新面板', onTap: () => createPanel(context, ref)),
            ),
            if (reports.isNotEmpty) ...[
              SectionTitle('收件箱',
                  trailing: unread > 0
                      ? TextButton(onPressed: () => ref.read(inboxProvider.notifier).markRead(), child: const Text('全部已读'))
                      : null),
              FadeSlideIn(
                delay: Motion.stagger(1),
                child: GlassGroup(children: [
                  for (final r in reports)
                    RowTile(
                      leading: _UnreadBadge(unread: r.unread),
                      title: r.title,
                      subtitle: _preview(r),
                      trailing: Text(hm(r.updatedAt), style: context.text.labelSmall),
                      onTap: () => _openReport(r),
                    ),
                ]),
              ),
            ],
            TodaySection(tasks: tasks, loading: ref.watch(tasksProvider).isLoading),
          ]),
          ),
        ),
      ),
    );
  }

  String _preview(HomeCard c) {
    final t = plainText(c.blocks).replaceAll(RegExp(r'[#*_`>|-]'), '').replaceAll(RegExp(r'\s+'), ' ').trim();
    return t.isEmpty ? '点开查看结果' : (t.length > 80 ? '${t.substring(0, 80)}…' : t);
  }
}

/// “今天”：今天排着的任务按钟点一行一件（today_agenda.dart 定规则）。行首等宽钟点列，下一个用正文色加粗、
/// 跑完的整行变淡（失败不淡）；失败/暂停只把那两个字染警示色；点行进任务详情。没有任务时一行引导去定时任务页。
class TodaySection extends StatelessWidget {
  const TodaySection({super.key, required this.tasks, required this.loading});
  final List<ScheduledTask> tasks;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final items = todayAgenda(tasks, DateTime.now());
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SectionTitle('今天',
          trailing: loading ? null : SwapSwitcher(child: Text(agendaSummary(items), key: ValueKey(agendaSummary(items)), style: context.text.labelSmall))),
      FadeSwitcher(
        child: loading
            ? const SkeletonList(key: ValueKey('loading'), rows: 1)
            : items.isEmpty
                ? GlassGroup(key: const ValueKey('empty'), children: [
                    RowTile(
                        icon: Icons.event_available_outlined,
                        title: '今天没有排定的任务',
                        subtitle: '每天的简报、提醒放进定时任务，会排在这里',
                        onTap: () => context.push('/me/tasks')),
                  ])
                : GlassGroup(key: const ValueKey('list'), children: [
                    for (var i = 0; i < items.length; i++)
                      FadeSlideIn(delay: Motion.stagger(i, from: 1), child: _AgendaRow(item: items[i])),
                  ]),
      ),
    ]);
  }
}

class _AgendaRow extends StatelessWidget {
  const _AgendaRow({required this.item});
  final AgendaItem item;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final next = item.state == AgendaState.next;
    final hint = agendaHint(item);
    return Dimmed(
      dimmed: item.faded,
      child: RowTile(
        leading: SizedBox(
          width: Layout.agendaTime,
          child: Text(item.time,
              style: context.text.titleSmall?.copyWith(color: next ? p.text : p.text2, fontWeight: next ? Weights.title : null)),
        ),
        title: item.task.name,
        subtitle: agendaDetail(item),
        problem: agendaProblem(item),
        trailing: hint.isEmpty ? const SizedBox.shrink() : SwapSwitcher(child: RowHint(hint, key: ValueKey(hint))),
        onTap: () => context.push('/me/tasks/${item.task.id}'),
      ),
    );
  }
}

/// 收件箱行首图标；未读时右上角一个强调色小点，读过后缩没。
class _UnreadBadge extends StatelessWidget {
  const _UnreadBadge({required this.unread});
  final bool unread;

  @override
  Widget build(BuildContext context) =>
      DotBadge(visible: unread, color: context.palette.accent, child: const IconBadge(Icons.inbox_outlined));
}

/// 问候：日期 + 早上好。输入框在底部的全局胶囊里（LaunchComposer）。
class _Hero extends StatelessWidget {
  const _Hero();

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final greet = now.hour < 6 ? '夜深了' : now.hour < 12 ? '早上好' : now.hour < 18 ? '下午好' : '晚上好';
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.only(top: Layout.headTop - Sp.x3), // 内容让位线已含顶栏下 12
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(formatDate(now), style: context.text.labelSmall),
          const SizedBox(height: Sp.x2),
          Text(greet, style: context.text.displayMedium),
        ]),
      ),
    );
  }
}

/// 还没有要处理的事时的引导卡：衬线大标题 + 一句话 + 去连接（设计 v2：引导卡标题用衬线点缀）。
class _Onboarding extends StatelessWidget {
  const _Onboarding({super.key});

  @override
  Widget build(BuildContext context) => GlassCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('我还能做更多', style: context.text.headlineMedium),
          const SizedBox(height: Sp.x1),
          Text('连接邮箱和日历后，我会在这里主动提醒你要处理的事。', style: context.text.bodyMedium?.copyWith(color: context.palette.text2)),
          const SizedBox(height: Sp.x4),
          PillButton(label: '去连接', icon: Icons.hub_outlined, onTap: () => context.push('/me/connectors')),
        ]),
      );
}

/// 还没有面板：一句话说清面板是什么 + 几个起点胶囊（点了就开新对话去搭），下面仍是“创建一个新面板”。
class _PanelIdeas extends StatelessWidget {
  const _PanelIdeas({super.key, required this.onPick});
  final ValueChanged<String> onPick;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: Layout.cardGap),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
            child: Text('面板会按时替你盯着一件事，打开主页一眼就看到。',
                style: context.text.bodyMedium?.copyWith(color: context.palette.text2)),
          ),
          const SizedBox(height: Sp.x3),
          Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
            for (var i = 0; i < panelIdeas.length; i++)
              FadeSlideIn(delay: Motion.stagger(i, from: 1), child: GlassChip(label: panelIdeas[i], onTap: () => onPick(panelIdeas[i]))),
          ]),
        ]),
      );
}

class _PanelCard extends ConsumerWidget {
  const _PanelCard({required this.card, required this.refreshing});
  final HomeCard card;
  final bool refreshing;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    Future<void> refresh() async {
      await ref.read(apiProvider).post('/api/tasks/${card.taskId}/run');
      await ref.read(tasksProvider.notifier).reload();
    }

    Future<void> remove() async {
      if (!await confirmDanger(context, title: '移除「${card.title}」？', text: '它不会再刷新。', action: '移除')) return;
      if (card.taskId != null) await ref.read(tasksProvider.notifier).remove(card.taskId!); // 后端会连卡一起删
      await ref.read(cardsProvider.notifier).reload();
    }

    // 改标题/刷新指令/频率：和任务详情同一张表单；改名由服务端同步到卡片，所以之后重拉一次卡片
    Future<void> edit() async {
      final task = ref.read(tasksProvider).value?.where((t) => t.id == card.taskId).firstOrNull;
      if (task == null) return;
      final changes = await showTaskForm(context, task: task);
      if (changes == null || changes.isEmpty) return;
      await ref.read(tasksProvider.notifier).patch(task.id, changes);
      await ref.read(cardsProvider.notifier).reload();
    }

    void menu() => showActionSheet<void>(context, title: card.title, actions: [
          if (card.taskId != null) ...[
            SheetAction(Icons.edit_outlined, '编辑面板', onTap: edit),
            SheetAction(Icons.history_rounded, '刷新记录', onTap: () => context.push('/me/tasks/${card.taskId}')),
          ],
          SheetAction(Icons.delete_outline_rounded, '移除', onTap: remove, danger: true),
        ]);

    // 内容区刷完从 Dimmed 恢复，关键数字（ValueTile → CountUp）从旧值滚到新值。
    // 头一行：标题 + 更新时间 + 刷新/更多（编辑、刷新记录、移除；小图标，可点区域仍 ≥ A11y.minTap）；下面是内容块（关键数字是一块块 ValueTile）
    return Padding(
      padding: const EdgeInsets.only(bottom: Layout.cardGap),
      child: GlassCard(
        padding: const EdgeInsets.fromLTRB(Layout.cardPad, Sp.x2, Sp.x2, Layout.cardPad),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text(card.title, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
            // 刷新中 ↔ 新时间：旧字上滑淡出、新字浮上来（刷完那一下看得见“更新了”）
            SwapSwitcher(child: Text(refreshing ? '刷新中…' : hm(card.updatedAt), key: ValueKey(refreshing ? '' : hm(card.updatedAt)), style: context.text.labelSmall)),
            if (card.taskId != null)
              IconButton(
                onPressed: refreshing ? null : refresh,
                tooltip: '刷新',
                icon: AnimatedRotation(
                  turns: refreshing ? 1 : 0,
                  duration: refreshing ? context.motion(Motion.spin) : Duration.zero,
                  child: Icon(Icons.refresh_rounded, size: Fs.lg, color: p.text3),
                ),
              ),
            IconButton(onPressed: menu, tooltip: '更多', icon: Icon(Icons.more_horiz_rounded, size: Fs.lg, color: p.text3)),
          ]),
          Padding(
            padding: const EdgeInsets.only(right: Sp.x2),
            child: Dimmed(dimmed: refreshing, child: BlockList(card.blocks)),
          ),
        ]),
      ),
    );
  }
}
