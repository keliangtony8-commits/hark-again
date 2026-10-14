import 'package:flutter/material.dart';

import '../../models/retry_notice.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';

/// 生成中回复上方的一行：模型调用失败、正在自动重试（“模型那边限流了，正在重试 2/5”），
/// 或重试用完换了备用模型（“刚才模型服务器出错了，这一轮改用「快速」”）。
/// 和“做了 N 步”那行同一个排版（小灰字 + 15 号图标，左右 Sp.x4），图标用 warning 色提醒但不吓人；
/// 次数变化走 SwapSwitcher，整行出现 / 收起由 MessageView 的 RiseSwitcher 负责。不可点，读屏念完整句。
class RetryLine extends StatelessWidget {
  const RetryLine({super.key, required this.notice});
  final RetryNotice notice;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final label = retryNoticeText(notice);
    final muted = context.text.labelMedium?.copyWith(color: p.text3);
    return Semantics(
      liveRegion: true,
      label: retryNoticeSemantics(notice),
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x2),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          SwapSwitcher(
            child: Icon(notice.isFallback ? Icons.swap_horiz_rounded : Icons.sync_problem_rounded,
                key: ValueKey(notice.isFallback), size: 15, color: p.warning),
          ),
          const SizedBox(width: Sp.x2),
          Flexible(child: SwapSwitcher(child: Text(label, key: ValueKey(label), maxLines: 2, overflow: TextOverflow.ellipsis, style: muted))),
        ]),
      ),
    );
  }
}
