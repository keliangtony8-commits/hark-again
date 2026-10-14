// v2.91 §N 对话状态胶囊（项目对话列表、项目首屏“最近的对话”共用这一个）。值只来自服务器 status（后端 app/conversation_status.py），
// 这里只管怎么画：进行中 = 安静底 + 呼吸小点；等你回复 = 墨色实心（唯一要你动手的信号）；已完成 = 安静底、三级字。
// 状态变了淡入换字；呼吸点在减少动态时停住（PulseDot）。
import 'package:flutter/material.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass_mode.dart';
import '../../ui/motion.dart';

class StatusCapsule extends StatelessWidget {
  const StatusCapsule(this.status, {super.key});
  final ConversationStatus status;

  static const height = 22.0;
  static const dot = 6.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final (fill, ink) = switch (status) {
      ConversationStatus.waiting => (p.ink, p.onInk),
      ConversationStatus.running => (context.tileFill, p.text2),
      ConversationStatus.done => (context.tileFill, p.text3),
    };
    return Semantics(
      label: '状态：${status.label}',
      excludeSemantics: true,
      child: AnimatedSwitcher(
        duration: context.motion(Motion.base),
        switchInCurve: Motion.ease,
        switchOutCurve: Motion.ease,
        child: Container(
          key: ValueKey(status),
          height: height,
          padding: const EdgeInsets.symmetric(horizontal: Sp.x2),
          decoration: BoxDecoration(color: fill, borderRadius: BorderRadius.circular(Radii.full)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            if (status == ConversationStatus.running) ...[
              PulseDot(color: ink, size: dot),
              const SizedBox(width: Sp.x1 + 1),
            ],
            Text(status.label,
                style: context.text.labelSmall?.copyWith(color: ink, fontWeight: Weights.title, letterSpacing: 0, height: 1)),
          ]),
        ),
      ),
    );
  }
}
