// 反馈（v2.64，对标 Hark 设置 → Feedback）：“报告问题” + 回看你在回复下点过 👍 / 👎 的报告。
// 版式和 Pages / 保险箱同一套：页头摘要 + 一句说明 → 空时起步卡 → 待处理 / 有用的回复 / 已解决 分组（带数量），左滑删除。
// 点一行进详情：整份报告（提问、回复、每一步、工具轨迹）就是“复制报告”出去的那段 Markdown，所见即所贴；
// 底下一排：复制报告 · 打开对话 · 标为已解决 / 重新打开。报告里存什么只在后端 app/feedback.py，文字规则在 models/feedback.dart。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../models/feedback.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/markdown.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/sub_page.dart';
import '../chat/open_conversation.dart';

class FeedbackNotifier extends AsyncNotifier<FeedbackList?> {
  @override
  Future<FeedbackList?> build() async {
    final s = await ref.watch(sessionProvider.future);
    if (!s.signedIn) return null;
    return FeedbackList.fromJson(await ref.read(apiProvider).get('/api/feedback'));
  }

  Future<void> reload() async => state = AsyncData(FeedbackList.fromJson(await ref.read(apiProvider).get('/api/feedback')));

  Future<void> report(String note) async {
    await ref.read(apiProvider).post('/api/feedback', {'note': note});
    await reload();
  }

  Future<void> setResolved(String id, bool resolved) async {
    await ref.read(apiProvider).patch('/api/feedback/$id', {'status': resolved ? 'resolved' : 'open'});
    ref.invalidate(feedbackDetailProvider(id));
    await reload();
  }

  /// 删报告：先从列表拿掉（左滑的那行不能再回来），失败再刷新回来。
  Future<void> remove(String id) async {
    final l = state.value;
    if (l != null) {
      state = AsyncData(FeedbackList(items: [for (final x in l.items) if (x.id != id) x], open: l.open));
    }
    try {
      await ref.read(apiProvider).delete('/api/feedback/$id');
    } finally {
      await reload();
    }
  }
}

final feedbackProvider = AsyncNotifierProvider.autoDispose<FeedbackNotifier, FeedbackList?>(FeedbackNotifier.new);

final feedbackDetailProvider = FutureProvider.autoDispose.family<FeedbackItem, String>((ref, id) async {
  final j = await ref.read(apiProvider).get('/api/feedback/$id');
  return FeedbackItem.fromJson(Map<String, dynamic>.from(j as Map));
});

/// “报告问题”：一段话就够，必填。成功后列表刷新、提示一句。
Future<void> reportProblem(BuildContext context, WidgetRef ref) async {
  final v = await showFormSheet(context,
      title: '报告问题',
      subtitle: '请描述问题及出现步骤，便于排查。',
      submit: '提交',
      fields: const [FieldSpec('note', '遇到了什么问题', hint: '比如：安卓上按住说话没反应', lines: 4)]);
  if (v == null || !context.mounted) return;
  try {
    await ref.read(feedbackProvider.notifier).report(v['note']!);
    if (context.mounted) showToast(context, '已记下');
  } on ApiError catch (e) {
    if (context.mounted) showToast(context, e.isNetwork ? '无法连接服务器，提交失败' : e.message);
  }
}

IconData feedbackIcon(FeedbackItem f) => switch (f.kind) {
      feedbackGood => Icons.thumb_up_alt_outlined,
      'problem' => Icons.bug_report_outlined,
      _ => Icons.thumb_down_alt_outlined,
    };

class FeedbackScreen extends ConsumerWidget {
  const FeedbackScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final value = ref.watch(feedbackProvider);
    return SubPage(
      title: const Text('反馈'),
      actions: [IconButton(tooltip: '报告问题', icon: const Icon(Icons.add_comment_outlined), onPressed: () => reportProblem(context, ref))],
      body: AsyncBody<FeedbackItem>(
        value: value.whenData((l) => l?.items ?? const []),
        onRetry: () => ref.invalidate(feedbackProvider),
        builder: (list) {
          final todo = [for (final f in list) if (!f.resolved && !f.good) f];
          final good = [for (final f in list) if (!f.resolved && f.good) f];
          final done = [for (final f in list) if (f.resolved) f];
          var i = 0; // 整页错峰序号
          Widget rows(List<FeedbackItem> items) => ListGroup(children: [
                for (final f in items)
                  SwipeToDelete(
                    id: f.id,
                    confirm: () => confirmDanger(context, title: '删除这份反馈？', text: f.messageId == null ? null : '那条回复上的评价也会一起取消。'),
                    onDelete: () => ref.read(feedbackProvider.notifier).remove(f.id),
                    child: FadeSlideIn(delay: Motion.stagger(i++, from: 1), child: _Row(f)),
                  ),
              ]);
          return PullRefresh(
            onRefresh: () => ref.read(feedbackProvider.notifier).reload(),
            child: PageBody(children: [
              PageIntro(
                summary: todo.isEmpty ? '没有待处理的' : '${todo.length} 条待处理',
                line: '回复下点 👎 会连同提问、回复和每一步记录存一份报告；在这里回看、复制给要修它的人，修好了标成已解决。',
              ),
              if (list.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: Sp.x4),
                  child: StarterCard(
                    title: '还没有反馈',
                    text: '哪里用着不顺，直接告诉我；对某条回复不满意，就在它下面点 👎。',
                    starters: [PillButton(label: '报告问题', icon: Icons.add_comment_outlined, primary: true, onTap: () => reportProblem(context, ref))],
                  ),
                ),
              if (todo.isNotEmpty) ...[SectionTitle('待处理', count: todo.length), rows(todo)],
              if (good.isNotEmpty) ...[SectionTitle('有用的回复', count: good.length), rows(good)],
              if (done.isNotEmpty) ...[SectionTitle('已解决', count: done.length), rows(done)],
            ]),
          );
        },
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row(this.f);
  final FeedbackItem f;

  @override
  Widget build(BuildContext context) => Dimmed(
        dimmed: f.resolved,
        child: RowTile(
          icon: feedbackIcon(f),
          title: f.excerpt.isEmpty ? f.kindLabel : f.excerpt,
          subtitle: feedbackLine(f),
          onTap: () => context.push('/me/feedback/${f.id}'),
        ),
      );
}

class FeedbackDetailScreen extends ConsumerStatefulWidget {
  const FeedbackDetailScreen({super.key, required this.id});
  final String id;

  @override
  ConsumerState<FeedbackDetailScreen> createState() => _FeedbackDetailScreenState();
}

class _FeedbackDetailScreenState extends ConsumerState<FeedbackDetailScreen> {
  bool _busy = false;

  Future<void> _run(Future<void> Function() job) async {
    setState(() => _busy = true);
    try {
      await job();
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器' : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete(FeedbackItem f) async {
    if (!await confirmDanger(context, title: '删除这份反馈？', text: f.messageId == null ? null : '那条回复上的评价也会一起取消。')) return;
    await _run(() async {
      await ref.read(feedbackProvider.notifier).remove(f.id);
      if (mounted) Navigator.of(context).maybePop();
    });
  }

  @override
  Widget build(BuildContext context) {
    // 详情和列表同一个来源：深链直接进详情时也让列表活着，标已解决 / 删除之后返回列表就是新的
    ref.watch(feedbackProvider);
    final value = ref.watch(feedbackDetailProvider(widget.id));
    final f = value.value;
    return SubPage(
      title: const Text('反馈详情'),
      actions: [
        if (f != null) IconButton(tooltip: '删除', icon: const Icon(Icons.delete_outline_rounded), onPressed: _busy ? null : () => _delete(f)),
      ],
      body: PageBody(children: [
        FadeSwitcher(
          child: switch (value) {
            AsyncData(value: final f) => _Detail(key: ValueKey('d-${f.resolved}'), f: f, busy: _busy, onResolve: (v) => _run(() => ref.read(feedbackProvider.notifier).setResolved(f.id, v))),
            AsyncError() => EmptyHint(key: const ValueKey('err'), icon: Icons.cloud_off_rounded, title: '读不到这份反馈', text: '可能已经删了，或者网络断了',
                action: TextButton(onPressed: () => ref.invalidate(feedbackDetailProvider(widget.id)), child: const Text('重试'))),
            _ => const SkeletonList(key: ValueKey('loading'), rows: 3),
          },
        ),
      ]),
    );
  }
}

class _Detail extends ConsumerWidget {
  const _Detail({super.key, required this.f, required this.busy, required this.onResolve});
  final FeedbackItem f;
  final bool busy;
  final void Function(bool resolved) onResolve;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cid = f.conversationId;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageIntro(summary: [f.kindLabel, if (f.createdAt != null) formatAgo(f.createdAt)].join(' · '), line: f.resolved ? '已解决' : '还没解决'),
      const SizedBox(height: Sp.x4),
      FadeSlideIn(
        delay: Motion.stagger(1),
        child: Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
          PillButton(
            label: '复制报告',
            icon: Icons.content_copy_rounded,
            primary: true,
            onTap: () {
              Clipboard.setData(ClipboardData(text: f.markdown));
              HapticFeedback.selectionClick();
              showToast(context, '已复制，可以直接贴给要修它的人');
            },
          ),
          if (cid != null) PillButton(label: '打开对话', icon: Icons.chat_bubble_outline_rounded, onTap: () => openConversation(context, ref, cid, focus: f.messageId, projectId: f.projectId)),
          PillButton(
            label: f.resolved ? '重新打开' : '标为已解决',
            icon: f.resolved ? Icons.replay_rounded : Icons.check_circle_outline_rounded,
            onTap: busy ? null : () => onResolve(!f.resolved),
          ),
        ]),
      ),
      const SizedBox(height: Sp.x4),
      FadeSlideIn(delay: Motion.stagger(2), child: AppCard(child: AppMarkdown(f.markdown))),
    ]);
  }
}
