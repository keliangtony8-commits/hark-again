// 活动时间线在回复上的样子（v1.28；规则在 models/activity.dart）。和 thought_view 的“已思考 N 秒 ›”同一种低调行：
// 回复上方一行“用了 4 步 · 12 秒 ›”（有没成的步骤时行尾补“1 步没成”，警示色），点开是一条竖向时间线——
// 每步：状态圆点（完成 = 对勾、出错 = 感叹号、没执行 = 禁止、被停 = 停止、进行中 = 脉冲）+ 标题 + 等宽摘要（命令/路径/网址）
// + 右侧用时；没成的步骤下面一行原因。步骤之间一根发丝线连起来。展开逐项错峰浮现。
// 生成中也显示（“已用 2 步”），展开能看着它一步步长出来；正在跑的那一步另有输入框上方的小条（message_view _ToolChip）。
// v1.34：改了文件的步骤（写文件 / 改文件）行尾多一个 “+3 −1”（绿/红），点这一步展开 diff（等宽，新增绿、删除红、段头淡）。
// v1.69：一步改了几个文件（apply_patch）：行尾是合计，点开先列出每个文件（FileDiffRow，错峰浮现），再点某个文件看它的 diff。
import 'package:flutter/material.dart';

import '../../models/activity.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/diff_view.dart';
import '../../ui/glass_mode.dart';
import '../../ui/motion.dart';

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
              // 窄屏 + 长摘要（“用了 12 步 · 1 分 5 秒 · 2 步没成”）不撑破：摘要可省略，“N 步没成”和箭头留着
              Flexible(child: SwapSwitcher(child: Text(label, key: ValueKey(label), maxLines: 1, overflow: TextOverflow.ellipsis, style: muted))),
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

/// 时间线的一行。first / last 决定圆点上下的连线画不画。改了文件的步骤可点开看 diff。
class StepRow extends StatefulWidget {
  const StepRow(this.step, {super.key, this.first = false, this.last = false});
  final ActivityStep step;
  final bool first, last;

  @override
  State<StepRow> createState() => _StepRowState();
}

class _StepRowState extends State<StepRow> {
  bool _diff = false;
  int? _file; // 几个文件时展开了哪一个

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = widget.step;
    final first = widget.first, last = widget.last;
    final change = s.change;
    final canOpen = s.expandable;
    final line = context.hairline;
    final tone = s.failed ? p.warning : p.text2;
    final mark = switch (s.state) {
      ActivityState.running => PulseDot(color: p.text2),
      ActivityState.done => Icon(Icons.check_rounded, size: 13, color: p.text2),
      ActivityState.error => Icon(Icons.priority_high_rounded, size: 13, color: p.warning),
      ActivityState.denied => Icon(Icons.block_rounded, size: 12, color: p.warning),
      ActivityState.stopped => Icon(Icons.stop_rounded, size: 13, color: p.warning),
    };
    final small = context.text.labelSmall;
    final head = Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(s.title, style: context.text.labelMedium?.copyWith(color: p.text)),
      if (s.detail.isNotEmpty) ...[
        const SizedBox(width: Sp.x2),
        Expanded(
          child: Text(s.detail,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: context.text.bodySmall?.copyWith(fontFamily: monoFont, fontSize: Fs.xs, color: p.text2)),
        ),
      ] else
        const Spacer(),
      if (change != null) ...[
        const SizedBox(width: Sp.x2),
        DiffStat(change),
        if (canOpen) TurnIcon(open: _diff, child: Icon(Icons.chevron_right_rounded, size: 14, color: p.text3)),
      ],
      if (s.ms != null && !s.running) ...[
        const SizedBox(width: Sp.x2),
        Text(stepDuration(s.ms!), style: small?.copyWith(color: p.text3)),
      ],
    ]);
    // 读屏：整步一句话挂在标题行上（原因、diff 正文不再单独读）；几个文件展开后每个文件各自一行可点。
    void toggle() => setState(() => _diff = !_diff);
    final title = Semantics(
      label: stepSemantics(s),
      excludeSemantics: true,
      button: canOpen,
      onTap: canOpen ? toggle : null,
      child: canOpen ? Pressable(onTap: toggle, child: head) : head,
    );
    return IntrinsicHeight(
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
                title,
                RiseSwitcher(
                  child: s.failed
                      ? ExcludeSemantics(
                          key: const ValueKey('note'),
                          child: Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(s.note.isEmpty ? stepStateLabel(s.state) : s.note,
                              style: context.text.bodySmall?.copyWith(color: tone)),
                        ))
                      : null,
                ),
                RiseSwitcher(
                  child: !_diff || !canOpen
                      ? null
                      : s.files.length == 1
                          ? ExcludeSemantics(key: const ValueKey('diff'), child: DiffView(s.files.first))
                          : Column(key: const ValueKey('files'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                              for (final (i, f) in s.files.indexed)
                                FadeSlideIn(
                                  key: ValueKey(f.path),
                                  delay: Motion.stagger(i),
                                  child: FileDiffRow(f,
                                      tag: stepFileTag(f),
                                      open: _file == i,
                                      onTap: f.expandable ? () => setState(() => _file = _file == i ? null : i) : null),
                                ),
                            ]),
                ),
              ]),
            ),
          ),
        ]),
    );
  }
}
