// 活动时间线在回复上的样子（v1.28；规则在 models/activity.dart）。和 thought_view 的“已思考 N 秒 ›”同一种低调行：
// 回复上方一行“用了 4 步 · 12 秒 ›”（有没成的步骤时行尾补“1 步没成”，警示色），点开是一条竖向时间线——
// 每步：状态圆点（完成 = 对勾、出错 = 感叹号、没执行 = 禁止、被停 = 停止、进行中 = 脉冲）+ 标题 + 等宽摘要（命令/路径/网址）
// + 右侧用时；没成的步骤下面一行原因。步骤之间一根发丝线连起来。展开逐项错峰浮现。
// 生成中也显示（“已用 2 步”），展开能看着它一步步长出来；正在跑的那一步另有输入框上方的小条（message_view _ToolChip）。
import 'package:flutter/material.dart';

import '../../models/activity.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass_mode.dart';
import '../../ui/motion.dart';

const _mono = 'monospace';
const _dot = 18.0; // 状态圆点直径；竖线从圆点中心穿过

class ActivitySummary extends StatefulWidget {
  const ActivitySummary({super.key, required this.steps, this.pending = false});
  final List<ActivityStep> steps;
  final bool pending;

  @override
  State<ActivitySummary> createState() => _ActivitySummaryState();
}

class _ActivitySummaryState extends State<ActivitySummary> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final steps = widget.steps;
    final label = activitySummary(steps, pending: widget.pending);
    final bad = failedSteps(steps);
    final muted = context.text.labelMedium?.copyWith(color: p.text3);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Pressable(
        semanticLabel: '$label${bad > 0 ? '，$bad 步没成' : ''}，${_open ? '收起' : '展开每一步'}',
        onTap: () => setState(() => _open = !_open),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: A11y.minTap),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x4),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.timeline_rounded, size: 15, color: p.text3),
              const SizedBox(width: Sp.x2),
              SwapSwitcher(child: Text(label, key: ValueKey(label), style: muted)),
              if (bad > 0) ...[
                Text(' · ', style: muted),
                Text('$bad 步没成', style: muted?.copyWith(color: p.warning)),
              ],
              const SizedBox(width: Sp.x1),
              TurnIcon(open: _open, child: Icon(Icons.chevron_right_rounded, size: 18, color: p.text3)),
            ]),
          ),
        ),
      ),
      RiseSwitcher(
        child: _open
            ? Padding(
                key: const ValueKey('steps-open'),
                padding: const EdgeInsets.only(bottom: Sp.x2),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x3, Sp.x4, Sp.x3),
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
                  child: AnimatedSize(
                    duration: context.motion(Motion.base),
                    curve: Motion.ease,
                    alignment: Alignment.topCenter,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      for (final (i, s) in steps.indexed)
                        FadeSlideIn(
                          key: ValueKey(s.id),
                          delay: Motion.stagger(i),
                          child: StepRow(s, first: i == 0, last: i == steps.length - 1),
                        ),
                    ]),
                  ),
                ),
              )
            : null,
      ),
    ]);
  }
}

/// 时间线的一行。first / last 决定圆点上下的连线画不画。
class StepRow extends StatelessWidget {
  const StepRow(this.step, {super.key, this.first = false, this.last = false});
  final ActivityStep step;
  final bool first, last;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = step;
    final line = context.hairline;
    final tone = s.failed ? p.warning : p.text2;
    final mark = switch (s.state) {
      ActivityState.running => PulseDot(color: p.text2),
      ActivityState.done => Icon(Icons.check_rounded, size: 13, color: p.text2),
      ActivityState.error => Icon(Icons.priority_high_rounded, size: 13, color: p.warning),
      ActivityState.denied => Icon(Icons.block_rounded, size: 12, color: p.warning),
      ActivityState.stopped => Icon(Icons.stop_rounded, size: 13, color: p.warning),
    };
    return Semantics(
      label: stepSemantics(s),
      excludeSemantics: true,
      child: IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(
            width: _dot,
            child: Column(children: [
              Container(width: 1, height: Sp.x1, color: first ? null : line),
              Container(
                width: _dot,
                height: _dot,
                alignment: Alignment.center,
                decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: s.failed ? tone : line)),
                child: SwapSwitcher(child: KeyedSubtree(key: ValueKey(s.state), child: mark)),
              ),
              Expanded(child: Container(width: 1, color: last ? null : line)),
            ]),
          ),
          const SizedBox(width: Sp.x3),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(top: Sp.x1, bottom: last ? 0 : Sp.x3),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(s.title, style: context.text.labelMedium?.copyWith(color: p.text)),
                  if (s.detail.isNotEmpty) ...[
                    const SizedBox(width: Sp.x2),
                    Expanded(
                      child: Text(s.detail,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: context.text.bodySmall?.copyWith(fontFamily: _mono, fontSize: Fs.xs, color: p.text2)),
                    ),
                  ] else
                    const Spacer(),
                  if (s.ms != null && !s.running) ...[
                    const SizedBox(width: Sp.x2),
                    Text(stepDuration(s.ms!), style: context.text.labelSmall?.copyWith(color: p.text3)),
                  ],
                ]),
                RiseSwitcher(
                  child: s.failed
                      ? Padding(
                          key: const ValueKey('note'),
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(s.note.isEmpty ? stepStateLabel(s.state) : s.note,
                              style: context.text.bodySmall?.copyWith(color: tone)),
                        )
                      : null,
                ),
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}
