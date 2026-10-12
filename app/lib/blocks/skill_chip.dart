// 用户消息里 `$技能` 点名的技能（v1.81）：气泡上方一枚胶囊小标签，告诉你这次按哪个技能做。
// 点一下打开技能页里的这条（看正文 / 改）。规则在服务器 app/skill_mentions.py。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';

class SkillChip extends StatelessWidget {
  const SkillChip(this.block, {super.key});
  final SkillBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Pressable(
      semanticLabel: '技能 ${block.name}',
      onTap: () => context.push('/me/skills/${Uri.encodeComponent(block.id)}'),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x1),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.full)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.auto_awesome_rounded, size: 14, color: p.text2),
          const SizedBox(width: Sp.x1),
          Flexible(
            child: Text(block.name,
                style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
        ]),
      ),
    );
  }
}
