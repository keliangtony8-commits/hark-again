// 卡片块的唯一外框（v0.84）：审批 / 订单 / 表单 / 浏览器以前各写一份 AnimatedContainer 边框，现在都走这里。
// 卡片块单独成卡、直接坐在背景上（见 models/block.dart replySegments），所以和 AppCard 是同一种玻璃：
// 半透明 cardFill（v3.5.1）、Radii.card（v2.80 无高光）。语气 tone 只决定边框：
//   calm    不描边（看完了 / 已处理）
//   waiting 警示色描边（等用户：待批准、待确认下单、待填写）
//   live    强调色描边（用户正在接管浏览器，唯一关键状态）
// 换语气时边框颜色和粗细按 Motion.base 过渡。
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';

enum FrameTone { calm, waiting, live }

class BlockFrame extends StatelessWidget {
  const BlockFrame({super.key, this.tone = FrameTone.calm, this.padding = const EdgeInsets.all(Sp.x4), this.clip = false, required this.child});
  final FrameTone tone;
  final EdgeInsets padding;
  final bool clip; // 内容要贴边裁圆角（浏览器画面）
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final (color, width) = switch (tone) {
      FrameTone.calm => (p.surface.withValues(alpha: 0), 1.0), // v2.80：平静的块不描边，只有等你/进行中才有一圈
      FrameTone.waiting => (p.warning.withValues(alpha: 0.5), 1.5),
      FrameTone.live => (p.accent, 1.5),
    };
    return AnimatedContainer(
        duration: context.motion(Motion.base),
        curve: Motion.ease,
        padding: padding,
        clipBehavior: clip ? Clip.antiAlias : Clip.none,
        decoration: BoxDecoration(
          color: context.cardFill,
          borderRadius: BorderRadius.circular(Radii.card),
          border: Border.all(color: color, width: width),
        ),
        child: child,
    );
  }
}
