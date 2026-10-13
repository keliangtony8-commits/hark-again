// 转交卡（v2.23，服务器 app/project_relay.py）：助手把一件事交给了另一个项目。
// 左边对方项目的表情方块，右边“已交给 · 项目名”、交代的话（两行）、在哪段对话 / 带了哪些文件；
// 点整张卡 = 打开那个项目里的那段对话（BlockActions.onOpenConversation；Home 上没给就不可点、不显示箭头）。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import 'block_actions.dart';
import 'block_frame.dart';

class RelayBlockView extends StatelessWidget {
  const RelayBlockView(this.block, {super.key});
  final RelayBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final open = BlockActions.of(context)?.onOpenConversation;
    final card = BlockFrame(
      padding: const EdgeInsets.all(Sp.x3),
      child: Row(children: [
        Container(
          width: A11y.minTap,
          height: A11y.minTap,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
          child: Text(block.emoji, style: context.text.titleLarge),
        ),
        const SizedBox(width: Sp.x3),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(Icons.forward_rounded, size: 16, color: p.text2),
              const SizedBox(width: Sp.x1),
              Flexible(
                child: Text('已交给 · ${block.name}', style: context.text.titleSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ]),
            if (block.text.isNotEmpty) ...[
              const SizedBox(height: 2),
              Text(block.text, style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 2, overflow: TextOverflow.ellipsis),
            ],
            const SizedBox(height: 2),
            Text(block.meta, style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
        if (open != null) Icon(Icons.chevron_right_rounded, color: p.text3),
      ]),
    );
    if (open == null || block.conversationId.isEmpty) return Semantics(label: block.semantics, excludeSemantics: true, child: card);
    return Pressable(semanticLabel: block.semantics, onTap: () => open(block.conversationId, block.projectId), child: card);
  }
}
