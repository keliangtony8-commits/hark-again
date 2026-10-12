// 本对话用量：顶栏标题下一行小字（“¥0.012 · 3.4K token”），点标题弹出按模型拆分的明细。
// 数据只读，来自 GET /api/conversations/{id}/usage；钱由后端在记账时算好，客户端不算。
// 刷新时机只有两个：打开/切换到某个对话（provider 以对话 id 为键），以及一轮回复结束（streaming true→false）。
// 刷新期间沿用旧值（不闪），文字变化用 SwapSwitcher；离线或出错时这行直接不显示，不打扰聊天。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../models/usage.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../me/usage_screen.dart' show ModelUsageList;
import '../../ui/sheets.dart';
import 'chat_controller.dart';
import 'conversation_files.dart';
import 'conversation_share.dart';

final conversationUsageProvider = FutureProvider.autoDispose.family<UsageTotal, String>((ref, id) async =>
    UsageTotal.fromJson((await ref.read(apiProvider).get('/api/conversations/$id/usage') as Map).cast<String, dynamic>()));

/// 标题下那一行；还没调用过模型 → null（不显示）。
String? usageLine(UsageTotal u) {
  if (u.total.calls == 0) return null;
  final tokens = '${formatTokens(u.total.tokens)} token';
  return u.money ? '${formatMoney(u.total.cost, u.currency)} · $tokens' : tokens;
}

/// 聊天顶栏标题：[child] 是页面给的标题，下面挂本对话用量；有对话时整块可点开明细。
/// [scope] = chatProvider 的 family 参数（'' 主聊天 / 项目 id）。
class ChatTitle extends ConsumerWidget {
  const ChatTitle({super.key, required this.scope, required this.child, this.dense = false});
  final String scope;
  final Widget child;

  /// 紧凑：两行行高收紧、居中（主聊天顶栏下的标题胶囊里用）
  final bool dense;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = ref.watch(chatProvider(scope).select((s) => s.activeId));
    ref.listen(chatProvider(scope).select((s) => s.streaming), (prev, next) {
      final cur = ref.read(chatProvider(scope)).activeId;
      if (prev == true && !next && cur != null) ref.invalidate(conversationUsageProvider(cur));
    });
    final usage = id == null ? null : ref.watch(conversationUsageProvider(id)).value;
    final line = usage == null ? null : usageLine(usage);
    final small = dense ? context.text.labelSmall?.copyWith(height: 1.2) : context.text.labelSmall;
    final body = Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: dense ? CrossAxisAlignment.center : CrossAxisAlignment.start,
        children: [
          child,
          SwapSwitcher(
            child: line == null
                ? SizedBox(key: const ValueKey('no-usage'), width: dense ? 0 : double.infinity)
                : Text(line, key: ValueKey(line), style: small, maxLines: 1),
          ),
        ]);
    if (id == null) return body;
    return Pressable(
      semanticLabel: '本对话用量',
      onTap: () => showConversationUsage(context, id),
      child: body,
    );
  }
}

Future<void> showConversationUsage(BuildContext context, String id) => showAppSheet<void>(
      context,
      builder: (_) => ConversationUsageSheet(id: id),
    );

class ConversationUsageSheet extends ConsumerWidget {
  const ConversationUsageSheet({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final value = ref.watch(conversationUsageProvider(id));
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.75),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x5),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.only(left: Sp.x1),
              child: Row(children: [
                Expanded(child: Text('本对话用量', style: context.text.titleLarge)),
                // 当前对话的文件 / 分享入口：从用量页换到对应 Sheet（同一位置，不叠两层）
                IconButton(
                  tooltip: '本对话全部文件',
                  icon: const Icon(Icons.folder_copy_outlined),
                  onPressed: () {
                    final nav = Navigator.of(context);
                    final root = nav.context;
                    nav.pop();
                    showConversationFiles(root, id);
                  },
                ),
                IconButton(
                  tooltip: '分享为网页',
                  icon: const Icon(Icons.public_rounded),
                  onPressed: () {
                    final nav = Navigator.of(context);
                    final root = nav.context;
                    nav.pop();
                    showConversationShare(root, id);
                  },
                ),
              ]),
            ),
            const SizedBox(height: Sp.x3),
            SwapSwitcher(
              child: value.when(
                skipLoadingOnReload: true,
                loading: () => const Shimmer(key: ValueKey('loading'), height: 96),
                error: (e, _) => Column(key: const ValueKey('error'), children: [
                  Text('加载失败：$e', style: context.text.bodySmall),
                  const SizedBox(height: Sp.x2),
                  OutlinedButton(onPressed: () => ref.invalidate(conversationUsageProvider(id)), child: const Text('重试')),
                ]),
                data: (u) => _Detail(u, key: const ValueKey('data')),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

class _Detail extends StatelessWidget {
  const _Detail(this.u, {super.key});
  final UsageTotal u;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = u.total;
    if (t.calls == 0) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x1, vertical: Sp.x3),
        child: Text('这个对话还没有调用过模型。', style: context.text.bodyMedium?.copyWith(color: p.text2)),
      );
    }
    final prompt = t.models.fold(0, (s, m) => s + m.promptTokens);
    final completion = t.models.fold(0, (s, m) => s + m.completionTokens);
    final hero = u.money ? formatMoney(t.cost, u.currency) : '${formatTokens(t.tokens)} token';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      FadeSlideIn(
        child: AppCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Semantics(
              label: '本对话累计 $hero',
              excludeSemantics: true,
              child: Text(hero, style: context.text.headlineMedium?.copyWith(color: p.text)),
            ),
            const SizedBox(height: Sp.x1),
            Text('${t.calls} 次调用 · 输入 ${formatTokens(prompt)} · 输出 ${formatTokens(completion)}', style: context.text.bodySmall),
          ]),
        ),
      ),
      const SizedBox(height: Sp.x3),
      FadeSlideIn(delay: Motion.stagger(1), child: ModelUsageList(models: t.models, priced: u.priced, currency: u.currency)),
      Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x3, Sp.x1, 0),
        child: Text(
          [
            '包含这个对话里的回复、滚动摘要等所有模型调用。',
            if (!u.money) '服务器还没配置 MODEL_PRICES，只统计 token。' else if (u.hasUnpriced) '“未定价”的模型只统计 token。',
          ].join(''),
          style: context.text.bodySmall,
        ),
      ),
    ]);
  }
}
