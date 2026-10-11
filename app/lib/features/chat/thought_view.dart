// 推理模型的“思考”在界面上的两种样子（v0.67 起单独成文件，message_view 只管摆放）：
// 1. 生成中、正文还没来：ThinkingCard = 跳点 + “思考中” + 右侧秒数计时 + 最新两行思考（TailText 顶部渐隐）；
// 2. 正文一来（以及回复完成后）：卡片收成回复上方一行 ThoughtSummary “已思考 8 秒 ›”，点开展开全部思考（只留尾部 2000 字）。
// 思考只活在本次会话（服务器不存），重新打开对话就没有这一行了。
import 'dart:async';

import 'package:flutter/material.dart';

import '../../models/message.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';

/// “8 秒” / “1 分 5 秒”；不足 1 秒按 1 秒（看得到思考就至少想了一下）。
String thinkDuration(Duration d) {
  final s = d.inMilliseconds <= 1000 ? 1 : (d.inMilliseconds / 1000).round();
  return s < 60 ? '$s 秒' : '${s ~/ 60} 分 ${s % 60} 秒';
}

/// 生成中的思考小卡。[since] = 第一段思考到达的时间，标题行右侧每秒跳一次计时。
class ThinkingCard extends StatefulWidget {
  const ThinkingCard({super.key, required this.text, this.since});
  final String text;
  final DateTime? since;

  @override
  State<ThinkingCard> createState() => _ThinkingCardState();
}

class _ThinkingCardState extends State<ThinkingCard> {
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(Timing.clockTick, (_) => setState(() {}));
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final since = widget.since;
    return Semantics(
      liveRegion: true,
      label: '正在思考',
      excludeSemantics: true,
      child: GlassSurface(
        radius: Radii.lg,
        shadow: false,
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            const TypingDots(),
            const SizedBox(width: Sp.x2),
            Text('思考中', style: context.text.labelMedium?.copyWith(color: p.text2)),
            const Spacer(),
            if (since != null)
              Text(thinkDuration(DateTime.now().difference(since)), style: context.text.labelSmall?.copyWith(color: p.text3)),
          ]),
          const SizedBox(height: Sp.x2),
          TailText(widget.text.replaceAll(RegExp(r'\s+'), ' ').trim(), style: context.text.bodySmall!.copyWith(color: p.text3)),
        ]),
      ),
    );
  }
}

/// 回复上方的一行“已思考 N 秒 ›”：点按展开/收起全部思考。左边和回复卡里的正文对齐。
class ThoughtSummary extends StatefulWidget {
  const ThoughtSummary({super.key, required this.message});
  final Message message;

  @override
  State<ThoughtSummary> createState() => _ThoughtSummaryState();
}

class _ThoughtSummaryState extends State<ThoughtSummary> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final m = widget.message;
    final time = m.thinkTime;
    final label = time == null ? '思考过程' : '已思考 ${thinkDuration(time)}';
    final muted = context.text.labelMedium?.copyWith(color: p.text3);
    // 只留了尾部：开头补省略号，表示前面还有
    final body = (m.thought.length >= Message.thoughtKeep ? '…' : '') + m.thought.trim();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Pressable(
        semanticLabel: _open ? '$label，收起' : '$label，展开',
        onTap: () => setState(() => _open = !_open),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: A11y.minTap),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x4),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.lightbulb_outline_rounded, size: 15, color: p.text3),
              const SizedBox(width: Sp.x2),
              Text(label, style: muted),
              const SizedBox(width: Sp.x1),
              TurnIcon(open: _open, child: Icon(Icons.chevron_right_rounded, size: 18, color: p.text3)),
            ]),
          ),
        ),
      ),
      RiseSwitcher(
        child: _open
            ? Padding(
                key: const ValueKey('thought-open'),
                padding: const EdgeInsets.only(bottom: Sp.x2),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
                  child: SelectableText(body, style: context.text.bodySmall?.copyWith(color: p.text2)),
                ),
              )
            : null,
      ),
    ]);
  }
}
