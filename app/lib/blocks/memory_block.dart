// 记忆卡：助手这轮回复记住/改了/忘掉了什么。安静的一条“便签”，不抢回复正文：
//   [记忆图标] 已记住                     撤销  ›
//   不吃香菜
//   （改动时下面一行灰色删除线：原来的说法）
// 状态（可撤销 / 已撤销 / 对不上了）不存在块里，由 memoryCardState 对照 memoriesProvider 推算；
// 撤销直接走记忆资源（删 / 改回 / 重建），列表一变卡片就跟着变，记忆页也同步。点 › 去记忆页。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/resource.dart';
import '../models/block.dart';
import '../models/memory.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';

class MemoryBlockView extends ConsumerStatefulWidget {
  const MemoryBlockView(this.block, {super.key});
  final MemoryBlock block;

  @override
  ConsumerState<MemoryBlockView> createState() => _MemoryBlockViewState();
}

class _MemoryBlockViewState extends ConsumerState<MemoryBlockView> {
  bool _busy = false;

  static String _title(String action, MemoryCardState s) => switch ((action, s)) {
        ('saved', MemoryCardState.undone) => '已撤销记住',
        ('updated', MemoryCardState.undone) => '已改回原来的说法',
        ('forgotten', MemoryCardState.undone) => '已恢复',
        ('saved', _) => '已记住',
        ('updated', _) => '已更新记忆',
        ('forgotten', _) => '已忘掉',
        _ => '记忆',
      };

  Future<void> _undo() async {
    final n = ref.read(memoriesProvider.notifier);
    setState(() => _busy = true);
    try {
      for (final i in widget.block.items) {
        switch (widget.block.action) {
          case 'saved':
            await n.remove(i.id);
          case 'updated':
            await n.patch(i.id, {'content': i.previous});
          case 'forgotten':
            await n.create({'content': i.content, 'category': i.category});
        }
      }
    } catch (_) {
      if (mounted) showToast(context, '没撤销成功，稍后再试');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = widget.block;
    final state = memoryCardState(b, ref.watch(memoriesProvider).value);
    final undone = state == MemoryCardState.undone;
    final strike = undone && b.action != 'forgotten' || !undone && b.action == 'forgotten'; // 不再生效的那句划掉
    final body = context.text.bodyMedium?.copyWith(
        color: strike ? p.text3 : p.text,
        decoration: strike ? TextDecoration.lineThrough : null,
        decorationColor: p.text3);
    return Semantics(
      container: true,
      label: '${_title(b.action, state)}：${b.items.map((i) => i.content).join('；')}',
      child: Container(
        padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x2, Sp.x1, Sp.x3),
        decoration: BoxDecoration(
          color: context.tileFill,
          borderRadius: BorderRadius.circular(Radii.inner),
          border: Border.all(color: context.hairline),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            PopSwitcher(
              child: Icon(undone ? Icons.undo_rounded : Icons.psychology_outlined,
                  key: ValueKey(undone), size: QuietAction.iconSize, color: p.text2),
            ),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: FadeSwitcher(
                alignment: AlignmentDirectional.topStart,
                child: Text(_title(b.action, state), key: ValueKey(state), style: context.text.labelMedium?.copyWith(color: p.text2)),
              ),
            ),
            FadeSwitcher(
              child: state == MemoryCardState.active
                  ? TextButton(
                      key: const ValueKey('undo'),
                      onPressed: _busy ? null : _undo,
                      style: TextButton.styleFrom(visualDensity: VisualDensity.compact, foregroundColor: p.text2),
                      child: Text(b.action == 'forgotten' ? '恢复' : '撤销'),
                    )
                  : const SizedBox(key: ValueKey('none'), height: A11y.minTap - Sp.x3),
            ),
            QuietAction(
              icon: const Icon(Icons.chevron_right_rounded),
              tooltip: '管理记忆',
              onPressed: () => context.push('/me/memory'),
            ),
          ]),
          for (final i in b.items) ...[
            Padding(
              padding: const EdgeInsets.only(right: Sp.x3, top: Sp.x1),
              child: FadeSwitcher(alignment: AlignmentDirectional.topStart, child: Text(i.content, key: ValueKey(strike), style: body)),
            ),
            if (i.previous != null && i.previous!.isNotEmpty && state != MemoryCardState.undone)
              Padding(
                padding: const EdgeInsets.only(right: Sp.x3, top: Sp.x1 / 2),
                child: Text('原来：${i.previous}',
                    style: context.text.bodySmall?.copyWith(color: p.text3, decoration: TextDecoration.lineThrough, decorationColor: p.text3)),
              ),
          ],
        ]),
      ),
    );
  }
}
