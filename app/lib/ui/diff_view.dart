// 文件改动的小部件（v1.68 从活动时间线抽出，时间线一步 + 改动卡共用）：
//   DiffStat “新建 +3 −1”（等宽，新增绿、删除红）；DiffView 展开的 diff 正文；
//   FileDiffRow 一行文件（路径 + 状态 + 可展开 diff；v1.69 从改动卡抽出，apply_patch 一步改几个文件时时间线也用它）。
import 'package:flutter/material.dart';

import '../models/activity.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass_mode.dart';
import 'motion.dart';

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
      if (change.movedFrom.isNotEmpty) Text('改名 ', style: small?.copyWith(color: p.text3)),
      if (change.mode.isNotEmpty) Text('${change.mode} ', style: small?.copyWith(color: p.text3)),
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
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
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

/// 一个文件的一行：路径（等宽，改名写 “旧 → 新”；undone 划掉）+ 右侧 tag 或 “+N −M” + 可展开 diff。
/// 展开状态由外面管（改动卡 / 时间线一步里同时只开一个）。
class FileDiffRow extends StatelessWidget {
  const FileDiffRow(this.f, {super.key, this.undone = false, this.open = false, this.onTap, this.tag});
  final FileChange f;
  final bool undone, open;
  final VoidCallback? onTap;

  /// 代替 “+N −M” 的状态字（“已不在”“大文件”“已删除”）。
  final String? tag;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final small = context.text.labelSmall;
    final head = Padding(
      padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
      child: Row(children: [
        Expanded(
          child: AnimatedDefaultTextStyle(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            style: (context.text.bodySmall ?? const TextStyle()).copyWith(
                fontFamily: monoFont,
                color: undone ? p.text3 : p.text,
                decoration: undone ? TextDecoration.lineThrough : null,
                decorationColor: p.text3),
            child: Text(f.label, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
        ),
        const SizedBox(width: Sp.x2),
        if (tag case final t?) Text(t, style: small?.copyWith(color: p.text3)) else DiffStat(f),
        if (onTap != null) TurnIcon(open: open, child: Icon(Icons.chevron_right_rounded, size: 16, color: p.text3)),
      ]),
    );
    return Semantics(
      button: onTap != null,
      label: '${f.label}，${tag ?? f.semantics}',
      excludeSemantics: true,
      onTap: onTap,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        onTap == null ? head : Pressable(onTap: onTap!, child: head),
        Padding(
          padding: const EdgeInsets.only(right: Sp.x2),
          child: RiseSwitcher(child: open ? DiffView(f, key: const ValueKey('diff')) : null),
        ),
      ]),
    );
  }
}
