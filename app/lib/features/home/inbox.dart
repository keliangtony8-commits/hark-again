// 收件箱未读：没有推送（FCM）时的“有新的吗”。
// 数据流：InboxNotifier 是未读数的唯一来源（Home 角标、横幅、“全部已读”都读它）；
// 摘要一变就让 cardsProvider 重新拉，Home 列表自然跟上，页面不各自轮询。
// 节奏由 InboxWatcher（挂在外壳上）决定：回到前台立刻问一次，前台时每 Timing.inboxPoll 问一次，后台不问。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../chat/open_conversation.dart';

class InboxNotifier extends Notifier<InboxSummary> {
  bool _loaded = false;

  @override
  InboxSummary build() => const InboxSummary();

  /// 拉一次摘要。返回“新来的那条”（首次加载只当基线，不算新）。网络失败静默——下次再问。
  Future<InboxItem?> refresh() async {
    try {
      final next = InboxSummary.fromJson(await ref.read(apiProvider).get('/api/inbox') as Map<String, dynamic>);
      return _apply(next);
    } catch (_) {
      return null;
    }
  }

  /// 全部已读（ids 为空）或只读掉几条。
  Future<void> markRead([List<String>? ids]) async {
    final next = InboxSummary.fromJson(
        await ref.read(apiProvider).post('/api/inbox/read', {'ids': ?ids}) as Map<String, dynamic>);
    _apply(next);
  }

  InboxItem? _apply(InboxSummary next) {
    final prev = state;
    final first = !_loaded;
    _loaded = true;
    if (next.sameAs(prev)) return null;
    state = next;
    if (!first) ref.read(cardsProvider.notifier).reload();
    return !first && next.hasNewSince(prev) ? next.latest : null;
  }
}

final inboxProvider = NotifierProvider<InboxNotifier, InboxSummary>(InboxNotifier.new);

/// 打开一条收件箱内容：报告 → 它的对话（后端顺带标已读）；建议 → Home。
Future<void> openInboxItem(BuildContext context, WidgetRef ref, {required String? conversationId}) async {
  if (conversationId == null) {
    context.go('/home');
    return;
  }
  await openConversation(context, ref, conversationId);
  await ref.read(inboxProvider.notifier).refresh();
}

/// 挂在外壳上：决定什么时候问，并在来了新的时候从顶部滑下一条横幅。
class InboxWatcher extends ConsumerStatefulWidget {
  const InboxWatcher({super.key, required this.child});
  final Widget child;

  @override
  ConsumerState<InboxWatcher> createState() => _InboxWatcherState();
}

class _InboxWatcherState extends ConsumerState<InboxWatcher> {
  late final AppLifecycleListener _life;
  Timer? _poll, _hide;
  InboxItem? _banner;

  @override
  void initState() {
    super.initState();
    _life = AppLifecycleListener(onResume: _start, onHide: _stop);
    _start();
  }

  @override
  void dispose() {
    _life.dispose();
    _stop();
    _hide?.cancel();
    super.dispose();
  }

  void _start() {
    _check();
    _poll ??= Timer.periodic(Timing.inboxPoll, (_) => _check());
  }

  void _stop() {
    _poll?.cancel();
    _poll = null;
  }

  Future<void> _check() async {
    final item = await ref.read(inboxProvider.notifier).refresh();
    if (item == null || !mounted) return;
    setState(() => _banner = item);
    _hide?.cancel();
    _hide = Timer(Timing.bannerHold, _dismiss);
  }

  void _dismiss() {
    if (mounted) setState(() => _banner = null);
  }

  @override
  Widget build(BuildContext context) => Stack(children: [
        widget.child,
        Positioned(
          left: Sp.x3,
          right: Sp.x3,
          top: 0,
          child: SafeArea(
            child: SlideDownSwitcher(
              child: _banner == null
                  ? null
                  : InboxBanner(
                      key: ValueKey(_banner!.id),
                      item: _banner!,
                      onDismiss: _dismiss,
                      onOpen: () {
                        final item = _banner!;
                        _dismiss();
                        openInboxItem(context, ref, conversationId: item.conversationId);
                      },
                    ),
            ),
          ),
        ),
      ]);
}

class InboxBanner extends StatelessWidget {
  const InboxBanner({super.key, required this.item, required this.onOpen, required this.onDismiss});
  final InboxItem item;
  final VoidCallback onOpen, onDismiss;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final report = item.kind == 'report';
    return Dismissible(
      key: ValueKey('banner-${item.id}'),
      direction: DismissDirection.up,
      onDismissed: (_) => onDismiss(),
      child: Pressable(
        onTap: onOpen,
        semanticLabel: [report ? '新报告' : '新建议', item.title, ?item.glance].join('，'),
        // 浮在内容上的通知条 = 浮层：真模糊玻璃 + 统一的淡浮层投影（v2.1：不再手写重投影和实色底）
        child: GlassSurface(
          blur: true,
          radius: Radii.lg,
          padding: const EdgeInsets.all(Sp.x3),
          child: Row(children: [
            IconBadge(report ? Icons.inbox_rounded : Icons.auto_awesome_rounded),
            const SizedBox(width: Sp.x3),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(report ? '新报告' : '新建议', style: context.text.labelSmall?.copyWith(color: p.text2)),
                Text(item.title, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                // 报告的“一眼”（摘要标题 · 一句话）：不点开就知道要不要现在看
                if (item.glance case final g?)
                  Text(g, style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 2, overflow: TextOverflow.ellipsis),
              ]),
            ),
            Icon(Icons.chevron_right_rounded, color: p.text3),
          ]),
        ),
      ),
    );
  }
}
