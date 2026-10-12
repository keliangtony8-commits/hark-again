// 文件改动的两件小部件（v1.68 从活动时间线抽出，时间线一步 + 改动卡共用）：
//   DiffStat “新建 +3 −1”（等宽，新增绿、删除红）；DiffView 展开的 diff 正文。
import 'package:flutter/material.dart';

import '../models/activity.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass_mode.dart';

const monoFont = 'monospace';

class DiffStat extends StatelessWidget {
  const DiffStat(this.change, {super.key});
  final FileChange change;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final small = context.text.labelSmall;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      if (change.created) Text('新建 ', style: small?.copyWith(color: p.text3)),
      Text('+${change.added}', style: small?.copyWith(fontFamily: monoFont, color: p.success)),
      if (change.removed > 0) Text(' −${change.removed}', style: small?.copyWith(fontFamily: monoFont, color: p.danger)),
    ]);
  }
}

/// 一次文件改动的 diff：等宽小字，新增绿、删除红、@@ 段头和截断说明淡色；太长纵向滚、太宽横向滚。
class DiffView extends StatelessWidget {
  const DiffView(this.change, {super.key});
  final FileChange change;

  static const maxHeight = 280.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final base = context.text.bodySmall?.copyWith(fontFamily: monoFont, fontSize: Fs.xs, height: 1.45);
    Color color(DiffKind k) => switch (k) {
          DiffKind.add => p.success,
          DiffKind.remove => p.danger,
          DiffKind.hunk || DiffKind.note => p.text3,
          DiffKind.context => p.text2,
        };
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Container(
        width: double.infinity,
        constraints: const BoxConstraints(maxHeight: maxHeight),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(Sp.x2),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final (kind, text) in diffLines(change.diff))
                Text(text.isEmpty ? ' ' : text, softWrap: false, style: base?.copyWith(color: color(kind))),
            ]),
          ),
        ),
      ),
    );
  }
}
