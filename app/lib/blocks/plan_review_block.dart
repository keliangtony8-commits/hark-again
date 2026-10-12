// 方案卡（v1.71 计划模式）：助手只看不改，把方案交给你批准。
//   [🗺] 改 a.txt                              等你批准
//        计划模式 · 批准后它才开始动手
//   ┌ 方案正文（Markdown；太长先露一截，“展开全部”）┐
//   [ 再改改 ]  [ 批准，开始执行 ]
// 批准 / 再改改走 BlockActions.onApproval（和审批卡同一条 approval.reply）。有了结果：状态字 SwapSwitcher 换、按钮 AnimatedSize 收起，
// 卡片默认收成一行（TurnIcon 箭头，点卡头展开）。规则在 models/plan_review.dart。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../models/plan_review.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/markdown.dart';
import '../ui/motion.dart';
import 'block_actions.dart';
import 'block_frame.dart';

const _peek = 260.0; // 长方案先露这么高

class PlanReviewBlockView extends StatefulWidget {
  const PlanReviewBlockView(this.block, {super.key});
  final PlanReviewBlock block;

  @override
  State<PlanReviewBlockView> createState() => _PlanReviewBlockViewState();
}

class _PlanReviewBlockViewState extends State<PlanReviewBlockView> {
  late bool _open = !planReviewCollapsedByDefault(widget.block);
  bool _full = false;

  @override
  void didUpdateWidget(PlanReviewBlockView old) {
    super.didUpdateWidget(old);
    if (old.block.pending && !widget.block.pending) _open = false; // 刚有结果：收起，聊天流不被长方案占住
  }

  @override
  Widget build(BuildContext context) {
    final b = widget.block;
    final p = context.palette;
    final small = context.text.labelSmall;
    final onReply = BlockActions.of(context)?.onApproval;
    final collapsible = !b.pending;
    final open = _open || !collapsible;
    final long = planReviewLong(b);
    final color = b.pending ? p.warning : p.text2;
    return Semantics(
      container: true,
      label: planReviewSemantics(b),
      child: BlockFrame(
        tone: b.pending ? FrameTone.waiting : FrameTone.calm,
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Pressable(
            onTap: collapsible ? () => setState(() => _open = !_open) : null,
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: PopSwitcher(
                  child: Icon(b.state == 'approved' ? Icons.task_alt_rounded : Icons.map_outlined,
                      key: ValueKey(b.state == 'approved'), size: 18, color: color),
                ),
              ),
              const SizedBox(width: Sp.x2),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(b.title, style: context.text.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
                  FadeSwitcher(
                    alignment: AlignmentDirectional.centerStart,
                    child: Text(planReviewHint(b), key: ValueKey(b.state), style: small?.copyWith(color: p.text3)),
                  ),
                ]),
              ),
              const SizedBox(width: Sp.x2),
              SwapSwitcher(
                child: Text(planReviewLabel(b),
                    key: ValueKey(b.state), style: small?.copyWith(color: color, fontWeight: Weights.title)),
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
                ? Padding(
                    padding: const EdgeInsets.only(top: Sp.x3),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Container(
                        padding: const EdgeInsets.all(Sp.x3),
                        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
                        child: ConstrainedBox(
                          constraints: BoxConstraints(maxHeight: long && !_full ? _peek : double.infinity),
                          // 露一截：不能滚的滚动视图负责裁掉多出的部分（不报溢出）；“展开全部”放开高度
                          child: SingleChildScrollView(physics: const NeverScrollableScrollPhysics(), child: AppMarkdown(planReviewBody(b))),
                        ),
                      ),
                      if (long)
                        Align(
                          alignment: AlignmentDirectional.centerStart,
                          child: TextButton(
                            onPressed: () => setState(() => _full = !_full),
                            style: TextButton.styleFrom(visualDensity: VisualDensity.compact, foregroundColor: p.text2),
                            child: SwapSwitcher(child: Text(_full ? '收起' : '展开全部', key: ValueKey(_full))),
                          ),
                        ),
                    ]),
                  )
                : const SizedBox(width: double.infinity),
          ),
          AnimatedSize(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            child: b.pending && onReply != null
                ? Padding(
                    padding: const EdgeInsets.only(top: Sp.x3),
                    child: Row(children: [
                      Expanded(child: OutlinedButton(onPressed: () => onReply(b.id, false), child: const Text('再改改'))),
                      const SizedBox(width: Sp.x2),
                      Expanded(child: FilledButton(onPressed: () => onReply(b.id, true), child: const Text('批准，开始执行'))),
                    ]),
                  )
                : const SizedBox(width: double.infinity),
          ),
        ]),
      ),
    );
  }
}
