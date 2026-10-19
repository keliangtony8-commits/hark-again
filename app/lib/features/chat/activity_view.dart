// 步骤胶囊（v3.5.5，照 Hark；规则在 models/activity.dart，网页同款 features/chat/Activity.tsx）：一条回复的过程只用回复下方一颗胶囊表达——
// 生成中只显示“当前正在做的那一步”（capsuleLabel），换步骤原地交叉淡入淡出，前面一颗脉冲点；生成完收成安静的“N 个步骤 · 12 秒”
// （有失败补“· N 项失败”，警示色）。点胶囊展开 = 竖向时间线：每步状态圆点（完成 = 对勾、出错 = 感叹号、没执行 = 禁止、被停 = 停止、进行中 = 脉冲）
// + 标题 + 等宽摘要 + 右侧用时，没成的下面一行原因，发丝线连起来，逐项错峰浮现。替换了 v1.28 回复上方那一行和回复卡里逐条的“正在…”小条。
// 默认收起；只有一轮停在出错的一步时自己展开（activityOpensItself）。不到 1 秒的步骤不写用时。
// v1.34 / v1.69：改了文件的步骤行尾 “+3 −1”，点开看 diff；几个文件先列每个文件（FileDiffRow），再点某个看它的 diff。
import 'package:flutter/material.dart';

import '../../models/activity.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/diff_view.dart';
import '../../ui/glass_mode.dart';
import '../../ui/motion.dart';

const _dot = 18.0; // 状态圆点直径；竖线从圆点中心穿过
const _capsuleH = 28.0; // 胶囊本身的高（外面补足最小点按区）

class StepCapsule extends StatefulWidget {
  const StepCapsule({super.key, required this.steps, this.pending = false});
  final List<ActivityStep> steps;
  final bool pending;

  @override
  State<StepCapsule> createState() => _StepCapsuleState();
}

class _StepCapsuleState extends State<StepCapsule> {
  late bool _open = activityOpensItself(widget.steps, pending: widget.pending);

  @override
  void didUpdateWidget(StepCapsule old) {
    super.didUpdateWidget(old);
    if (old.pending && !widget.pending && activityOpensItself(widget.steps)) _open = true; // 刚结束、卡在出错的一步
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final steps = widget.steps;
    final live = widget.pending;
    final (title, detail) = live ? capsuleLabel(steps) : (activitySummary(steps), '');
    final bad = live ? 0 : failedSteps(steps);
    final ink = context.text.labelMedium?.copyWith(color: live ? p.text2 : p.text3);
    final label = detail.isEmpty ? title : '$title · $detail';
    final capsule = Container(
      height: _capsuleH,
      padding: const EdgeInsets.symmetric(horizontal: Sp.x3),
      decoration: BoxDecoration(
        color: GlassMode.solidOf(context) ? p.surface : p.card,
        border: Border.all(color: context.hairline),
        borderRadius: BorderRadius.circular(Radii.full),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        SwapSwitcher(
          child: live
              ? SizedBox(key: const ValueKey('live'), width: 8, height: 8, child: Center(child: PulseDot(color: p.text2)))
              : Icon(Icons.timeline_rounded, key: const ValueKey('done'), size: 14, color: p.text3),
        ),
        const SizedBox(width: Sp.x2),
        // 换步骤：原地交叉淡入淡出（旧的往上淡出、新的从下淡入）；窄屏长摘要省略，“N 项失败”和箭头留着
        Flexible(
          child: SwapSwitcher(
            child: Text.rich(
              TextSpan(text: title, children: [
                if (detail.isNotEmpty) TextSpan(text: ' · $detail', style: TextStyle(color: p.text3)),
              ]),
              key: ValueKey(label),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: ink,
            ),
          ),
        ),
        if (bad > 0) ...[
          Text(' · ', style: ink),
          Text('$bad 项失败', style: ink?.copyWith(color: p.warning)),
        ],
        const SizedBox(width: 2),
        TurnIcon(open: _open, child: Icon(Icons.chevron_right_rounded, size: 16, color: p.text3)),
      ]),
    );
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Semantics(
        liveRegion: live, // 生成中：读屏播报当前这一步
        child: Pressable(
          semanticLabel: '$label${bad > 0 ? '，$bad 项失败' : ''}，${_open ? '收起步骤' : '展开步骤'}',
          onTap: () => setState(() => _open = !_open),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: A11y.minTap),
            child: Align(alignment: Alignment.centerLeft, widthFactor: 1, child: capsule),
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
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
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
      if (s.ms case final ms? when !s.running)
        if (stepDuration(ms) case final d?) ...[
          const SizedBox(width: Sp.x2),
          Text(d, style: small?.copyWith(color: p.text3)),
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
