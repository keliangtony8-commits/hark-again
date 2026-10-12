// 对话记忆卡（本对话用量 Sheet 里，用量总数下面）：下一轮发给模型的原文占预算多少（MeterBar）、
// 较早多少条已压成滚动摘要（可展开看摘要原文）、“整理上文”键 = 手动把最后一问之前的原文并进摘要
// （Codex /compact、Gemini /compress 的对应物；规则在后端 agent/context.py，这里只展示 + 发请求）。
// 正在回复时后端 409，提示条原样转述；整理完卡片原地换新值（MeterBar 平滑缩短、数字 SwapSwitcher）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../models/conversation_context.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass_mode.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';

final conversationContextProvider = FutureProvider.autoDispose.family<ConversationContext, String>((ref, id) async =>
    ConversationContext.fromJson((await ref.read(apiProvider).get('/api/conversations/$id/context') as Map).cast<String, dynamic>()));

/// 卡片第二行：原文条数 / 字数 / 上限。
String contextLine(ConversationContext c) =>
    '最近 ${c.raw} 条原文 · 约 ${formatChars(c.rawChars)}，上限 ${formatChars(c.budget)}';

/// 卡片第三行：摘要覆盖了多少（没有摘要 → null）。
String? summaryLine(ConversationContext c) => c.summarized > 0 ? '更早的 ${c.summarized} 条已压成摘要' : null;

/// 整理完的提示条。[before] = 整理前的状态（算这次并进去几条）。
String compactToast(ConversationContext before, CompactResult r) => switch (r.status) {
      'compressed' => '已把 ${r.state.summarized - before.summarized} 条较早消息压成摘要（约 ${formatChars(r.before)} → ${formatChars(r.after)}）',
      'inflated' => '摘要反而比原文长，保持原样',
      _ => '已经很精简，没有可整理的',
    };

class ConversationMemoryCard extends ConsumerStatefulWidget {
  const ConversationMemoryCard({super.key, required this.id});
  final String id;

  @override
  ConsumerState<ConversationMemoryCard> createState() => _ConversationMemoryCardState();
}

class _ConversationMemoryCardState extends ConsumerState<ConversationMemoryCard> {
  bool _busy = false;
  bool _open = false;
  ConversationContext? _fresh; // 整理后后端回的新状态：不必再 GET 一次

  Future<void> _compact(ConversationContext before) async {
    setState(() => _busy = true);
    String text;
    try {
      final r = CompactResult.fromJson(
          (await ref.read(apiProvider).post('/api/conversations/${widget.id}/compact') as Map).cast<String, dynamic>());
      if (mounted) setState(() => _fresh = r.state);
      text = compactToast(before, r);
    } on ApiError catch (e) {
      text = e.message;
    } catch (_) {
      text = '整理失败，稍后再试';
    }
    if (!mounted) return;
    setState(() => _busy = false);
    showToast(context, text);
  }

  @override
  Widget build(BuildContext context) {
    final value = ref.watch(conversationContextProvider(widget.id));
    final c = _fresh ?? value.value;
    if (c == null || c.messages == 0) return const SizedBox.shrink(); // 加载中 / 出错 / 空对话：不占位
    final p = context.palette;
    final summary = summaryLine(c);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: Text('对话记忆', style: context.text.titleSmall)),
          SwapSwitcher(
            child: Text('${(c.fill * 100).clamp(0, 999).round()}%',
                key: ValueKey(c.rawChars), style: context.text.labelMedium?.copyWith(color: c.tight ? p.warning : p.text2)),
          ),
        ]),
        const SizedBox(height: Sp.x2),
        Semantics(
          label: '原文占上限 ${(c.fill * 100).round()}%',
          excludeSemantics: true,
          child: MeterBar(value: c.fill, height: Sp.x1, color: c.tight ? p.warning : p.text2),
        ),
        const SizedBox(height: Sp.x2),
        SwapSwitcher(child: Text(contextLine(c), key: ValueKey(contextLine(c)), style: context.text.bodySmall)),
        if (summary != null)
          Row(children: [
            Expanded(child: Text(summary, style: context.text.bodySmall)),
            TextButton(
              onPressed: () => setState(() => _open = !_open),
              child: Text(_open ? '收起摘要' : '查看摘要'),
            ),
          ]),
        RiseSwitcher(
          child: _open && c.summary.isNotEmpty
              ? Container(
                  key: ValueKey('summary-${c.summary.hashCode}'),
                  margin: const EdgeInsets.only(top: Sp.x1),
                  padding: const EdgeInsets.all(Sp.x3),
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.md)),
                  child: SelectableText(c.summary, style: context.text.bodySmall?.copyWith(color: p.text)),
                )
              : null,
        ),
        const SizedBox(height: Sp.x2),
        Row(children: [
          Expanded(
            child: Text(
              c.compactable > 0 ? '把最后一问之前的 ${c.compactable} 条并进摘要，之后每轮更省 token' : '已经很精简',
              style: context.text.bodySmall?.copyWith(color: p.text3),
            ),
          ),
          const SizedBox(width: Sp.x2),
          FilledButton.tonalIcon(
            onPressed: _busy || c.compactable == 0 ? null : () => _compact(c),
            icon: PopSwitcher(
              child: _busy
                  ? const SizedBox.square(
                      key: ValueKey('busy'), dimension: Sp.x4, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.compress_rounded, key: ValueKey('idle')),
            ),
            label: Text(_busy ? '整理中' : '整理上文'),
          ),
        ]),
      ]),
    );
  }
}
