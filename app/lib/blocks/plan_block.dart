// 计划清单卡（v1.47）：助手开工前列出步骤，边做边勾。
//   [☰] 计划                                    2/5  ⌄
//   ━━━━━━━━━━━──────────────  （进度条，墨色）
//   改用 vite（最近一次改计划的原因，可无）
//   ✓ 装依赖                    （完成：淡色 + 删除线）
//   ● 写页面                    （进行中：脉冲点 + 加粗；这一轮结束后定格成实心环）
//   ○ 跑起来                    （待做）
// 状态变了：标记 SwapSwitcher 换、文字颜色 AnimatedDefaultTextStyle 过渡；新步骤 FadeSlideIn 进场；清单长短 AnimatedSize。
// 全做完且这一轮结束：默认收起成标题一行，点标题展开。items 为空（助手清掉了计划）：不画。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../models/plan.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/motion.dart';
import 'block_frame.dart';

class PlanBlockView extends StatefulWidget {
  const PlanBlockView(this.block, {super.key});
  final PlanBlock block;

  @override
  State<PlanBlockView> createState() => _PlanBlockViewState();
}

class _PlanBlockViewState extends State<PlanBlockView> {
  late bool _open = !planCollapsedByDefault(widget.block);

  @override
  void didUpdateWidget(PlanBlockView old) {
    super.didUpdateWidget(old);
    // 实时看着它做完：这一轮结束时自动收起（用户自己点开过的不管）
    if (!old.block.settled && planCollapsedByDefault(widget.block)) _open = false;
  }

  @override
  Widget build(BuildContext context) {
    final b = widget.block;
    if (b.items.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    final small = context.text.labelSmall;
    final collapsible = planFinished(b);
    final open = _open || !collapsible;
    return Semantics(
      container: true,
      label: planSemantics(b),
      child: BlockFrame(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
        child: ExcludeSemantics(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Pressable(
              onTap: collapsible ? () => setState(() => _open = !_open) : null,
              child: Row(children: [
                Icon(Icons.checklist_rounded, size: 18, color: p.text2),
                const SizedBox(width: Sp.x2),
                Expanded(child: Text('计划', style: context.text.labelLarge)),
                SwapSwitcher(
                  child: Text(planProgress(b), key: ValueKey(planProgress(b)), style: small?.copyWith(color: p.text3)),
                ),
                if (collapsible) ...[
                  const SizedBox(width: Sp.x1),
                  TurnIcon(open: open, turns: 0.5, child: Icon(Icons.expand_more_rounded, size: 18, color: p.text3)),
                ],
              ]),
            ),
            AnimatedSize(
              duration: context.motion(Motion.base),
              curve: Motion.ease,
              alignment: Alignment.topCenter,
              child: open
                  ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      const SizedBox(height: Sp.x2),
                      MeterBar(value: planRatio(b), color: p.text2, height: Sp.x1),
                      RiseSwitcher(
                        child: (b.explanation?.isNotEmpty ?? false)
                            ? Padding(
                                key: ValueKey(b.explanation),
                                padding: const EdgeInsets.only(top: Sp.x2),
                                child: Text(b.explanation!, style: small?.copyWith(color: p.text2), maxLines: 2, overflow: TextOverflow.ellipsis),
                              )
                            : null,
                      ),
                      const SizedBox(height: Sp.x1),
                      for (final (n, item) in b.items.indexed)
                        FadeSlideIn(
                          key: ValueKey(item.content),
                          delay: Motion.stagger(n),
                          child: _Step(item, settled: b.settled),
                        ),
                    ])
                  : const SizedBox(width: double.infinity),
            ),
          ]),
        ),
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step(this.item, {required this.settled});
  final PlanItem item;
  final bool settled;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final base = context.text.bodyMedium ?? const TextStyle();
    final style = switch (item.status) {
      PlanStatus.completed => base.copyWith(color: p.text3, decoration: TextDecoration.lineThrough, decorationColor: p.text3),
      PlanStatus.inProgress => base.copyWith(color: p.text, fontWeight: Weights.title),
      PlanStatus.pending => base.copyWith(color: p.text2),
    };
    final live = item.status == PlanStatus.inProgress && !settled;
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox.square(
          dimension: 20,
          child: Center(
            child: SwapSwitcher(
              child: KeyedSubtree(
                key: ValueKey('${item.status}$live'),
                child: switch (item.status) {
                  PlanStatus.completed => Icon(Icons.check_circle_rounded, size: 18, color: p.text2),
                  PlanStatus.inProgress when live => PulseDot(color: p.accent, size: 8),
                  PlanStatus.inProgress => Icon(Icons.adjust_rounded, size: 18, color: p.text2),
                  PlanStatus.pending => Icon(Icons.radio_button_unchecked_rounded, size: 18, color: p.text3),
                },
              ),
            ),
          ),
        ),
        const SizedBox(width: Sp.x2),
        Expanded(
          child: AnimatedDefaultTextStyle(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            style: style,
            child: Text(item.content),
          ),
        ),
      ]),
    );
  }
}
