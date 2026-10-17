// Home（v2.78 重做，docs/home-redesign.md）：一列同款卡，没有小节标题、解释文字、空状态和问候。
// 本文件只排顺序，每种卡一个文件：要你处理的建议卡（action_card.dart；一张都没有时是连接引导卡 ConnectCard）
// → 今天（today_card.dart，仅当今天有任务）→ 面板们（panel_card.dart）→ 收件箱（report_actions.dart InboxCard）
// → 一行“N 条稍后提醒”（card_snooze.dart，仅有时）→ “创建一个新面板”胶囊（和顶栏 + 一样：输入胶囊进新建面板模式，new_panel.dart）。
// 输入在底部全局胶囊（LaunchComposer），聚焦时第一个建议是“帮我准备今天”。网页版 HomeScreen.tsx 同一顺序。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../shell/launch_composer.dart';
import '../../theme/tokens.dart';
import '../../shell/shell_page.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../chat/open_conversation.dart';
import 'action_card.dart';
import 'card_snooze.dart';
import 'inbox.dart';
import 'new_panel.dart';
import 'panel_card.dart';
import 'report_actions.dart';
import 'today_agenda.dart' show prepDayPrompt;
import 'today_card.dart';

/// 主页输入框聚焦时的建议：第一个是“帮我准备今天”（原来主页上的一颗胶囊，本来就是一句话，属于输入框）。
const homePrompts = [prepDayPrompt, '查一下今天的新闻', '帮我规划这周的学习', '把这段话翻译成英文'];

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  Timer? _poll;

  /// 底部输入胶囊的模式：+ / “创建一个新面板”设成 newPanelMode（进入发起态），收起时 LaunchComposer 清回 null。
  final _launch = ValueNotifier<LaunchMode?>(null);

  void _newPanel() => _launch.value = newPanelMode;

  @override
  void dispose() {
    _poll?.cancel();
    _launch.dispose();
    super.dispose();
  }

  /// 建议卡上的“去做”：开一段新对话发出去，然后切到聊天。
  void _send(String text) => askInNewChat(context, ref, text);

  void _openOffer(String id, String? send, {String? projectId}) => openConversation(context, ref, id, send: send, projectId: projectId);

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
    final snoozed = all.where((c) => c.snoozed && (c.kind == 'action' || c.kind == 'report')).toList(); // 稍后提醒/稍后再看：合成一行
    final items = all.where((c) => !c.snoozed).toList();
    final actions = items.where((c) => c.kind == 'action').toList();
    final panels = items.where((c) => c.kind == 'panel').toList();
    final reports = items.where((c) => c.kind == 'report').take(5).toList();

    // 卡片栈：每张卡错峰浮上来；加载中整栈一块骨架（换成内容时交叉淡化），不再每段各自一块
    final stack = <Widget>[
      if (actions.isEmpty) const ConnectCard(),
      for (final a in actions) ActionCard(card: a, onDo: _send, onOpen: _openOffer),
      TodayCard(tasks: tasks),
      for (final p in panels)
        PanelCard(
            card: p,
            task: tasks.where((t) => t.id == p.taskId).firstOrNull,
            refreshing: p.taskId != null && refreshing.contains(p.taskId)),
      InboxCard(reports: reports, onOpen: _openReport),
      SnoozedCards(cards: snoozed),
      WidePill(icon: Icons.add_rounded, label: newPanelCaption, onTap: _newPanel),
    ];

    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      body: ShellPage(
        lead: GlassIconButton(icon: Icons.add_rounded, tooltip: '新建面板', onTap: _newPanel),
        child: LaunchComposer(
          suggestions: homePrompts,
          mode: _launch,
          child: PullRefresh(
            onRefresh: _refreshAll,
            child: PageBody(children: [
              FadeSwitcher(
                child: !cards.hasValue // 只有第一次没数据才骨架；下拉刷新、后台重取时照常显示（core/swr.dart）
                    ? const SkeletonList(key: ValueKey('loading'), rows: 3)
                    : Column(key: const ValueKey('stack'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        for (var i = 0; i < stack.length; i++) FadeSlideIn(delay: Motion.stagger(i), child: stack[i]),
                      ]),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
