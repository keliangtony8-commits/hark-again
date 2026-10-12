// 子助手卡（v1.48）：主助手把几件独立的事并行交给子助手，聊天里一张卡实时看它们各自做到哪。
//   [⑂] 子助手                                  1/2 完成
//   ● 查竞品定价                                          （在做：脉冲点）
//     第 3 步 · 正在搜索
//   ✓ 整理用户评论                                   ⌄   （完成：点开看交回的结论）
//     7 步 · 42 秒
// 状态变了：标记 SwapSwitcher 换、副标题 SwapSwitcher 淡换；结论 AnimatedSize 展开 + TurnIcon；行入场 FadeSlideIn 错开。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../models/delegate.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import 'block_frame.dart';

class DelegateBlockView extends StatelessWidget {
  const DelegateBlockView(this.block, {super.key});
  final DelegateBlock block;

  @override
  Widget build(BuildContext context) {
    final b = block;
    if (b.tasks.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    return Semantics(
      container: true,
      label: delegateSemantics(b),
      child: BlockFrame(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
        child: ExcludeSemantics(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Icon(Icons.call_split_rounded, size: 18, color: p.text2),
              const SizedBox(width: Sp.x2),
              Expanded(child: Text('子助手', style: context.text.labelLarge)),
              SwapSwitcher(
                child: Text(delegateProgress(b),
                    key: ValueKey(delegateProgress(b)), style: context.text.labelSmall?.copyWith(color: p.text3)),
              ),
            ]),
            const SizedBox(height: Sp.x1),
            for (final (n, t) in b.tasks.indexed)
              FadeSlideIn(key: ValueKey(t.title), delay: Motion.stagger(n), child: _Task(t, live: b.live)),
          ]),
        ),
      ),
    );
  }
}

class _Task extends StatefulWidget {
  const _Task(this.task, {required this.live});
  final DelegateTask task;
  final bool live;

  @override
  State<_Task> createState() => _TaskState();
}

class _TaskState extends State<_Task> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final t = widget.task;
    final p = context.palette;
    final canOpen = delegateCanOpen(t);
    final open = _open && canOpen;
    final line = delegateTaskLine(t);
    final bad = t.state == DelegateState.failed;
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Pressable(
          onTap: canOpen ? () => setState(() => _open = !_open) : null,
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox.square(
              dimension: 20,
              child: Center(
                child: SwapSwitcher(
                  child: KeyedSubtree(
                    key: ValueKey('${t.state}${widget.live}'),
                    child: switch (t.state) {
                      DelegateState.running when widget.live => PulseDot(color: p.accent, size: 8),
                      DelegateState.running => Icon(Icons.adjust_rounded, size: 18, color: p.text3),
                      DelegateState.done => Icon(Icons.check_circle_rounded, size: 18, color: p.text2),
                      DelegateState.partial => Icon(Icons.timelapse_rounded, size: 18, color: p.warning),
                      DelegateState.failed => Icon(Icons.error_outline_rounded, size: 18, color: p.danger),
                      DelegateState.stopped => Icon(Icons.stop_circle_outlined, size: 18, color: p.text3),
                    },
                  ),
                ),
              ),
            ),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t.title, style: context.text.bodyMedium?.copyWith(fontWeight: Weights.title), maxLines: 1, overflow: TextOverflow.ellipsis),
                SwapSwitcher(
                  child: Text(line,
                      key: ValueKey(line),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: context.text.labelSmall?.copyWith(color: bad ? p.danger : p.text3)),
                ),
              ]),
            ),
            if (canOpen)
              TurnIcon(open: open, turns: 0.5, child: Icon(Icons.expand_more_rounded, size: 18, color: p.text3)),
          ]),
        ),
        AnimatedSize(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          alignment: Alignment.topCenter,
          child: open
              ? Container(
                  margin: const EdgeInsets.only(top: Sp.x2, left: 20 + Sp.x2),
                  padding: const EdgeInsets.all(Sp.x3),
                  constraints: const BoxConstraints(maxHeight: 240),
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
                  child: SingleChildScrollView(
                    child: SelectableText(t.result!, style: context.text.bodySmall?.copyWith(color: p.text2)),
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}
