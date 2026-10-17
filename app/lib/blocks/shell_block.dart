// 用户自己跑的命令卡（输入框 !命令，不经过助手）。和后台任务卡同一套样子，两种卡一眼是一家：
//   [●] $ npm test                            1.2 秒
//   ┌ 输出最后几行（等宽，运行中实时）┐
//   一句说明（超时 / 内存 / 电脑刚被唤醒 / 被拦下的原因）
//   已完成                               完整输出  复制
// 运行中：服务器每 0.5 秒推一次最近的输出（block.update），停掉用输入框的“停止”。规则在 models/shell.dart。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../models/job.dart';
import '../models/shell.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import '../ui/sheets.dart';
import 'block_frame.dart';
import 'job_block.dart';

const _mono = 'monospace';

class ShellBlockView extends StatelessWidget {
  const ShellBlockView(this.block, {super.key});
  final ShellBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = block;
    final tone = shellTone(b.state);
    final tail = shellTail(b.output, Layout.jobLogLines);
    final small = context.text.labelSmall;
    final empty = switch (b.state) {
      'running' => '等待输出…',
      'refused' || 'error' => '（没有执行）',
      _ => '（没有输出）',
    };
    return Semantics(
      container: true,
      label: shellSemantics(b),
      child: BlockFrame(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x2, Sp.x1),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          ExcludeSemantics(
            child: Padding(
              padding: const EdgeInsets.only(right: Sp.x2),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SwapSwitcher(child: JobStatusMark(tone, key: ValueKey(tone))),
                const SizedBox(width: Sp.x2),
                Expanded(
                  child: Text('\$ ${b.command}',
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontFamily: _mono, fontSize: Fs.sm, height: 1.35, color: p.text)),
                ),
                const SizedBox(width: Sp.x2),
                FadeSwitcher(
                  child: Text(shellDuration(b.seconds), key: ValueKey(b.seconds == null), style: small?.copyWith(color: p.text3)),
                ),
              ]),
            ),
          ),
          const SizedBox(height: Sp.x2),
          Padding(
            padding: const EdgeInsets.only(right: Sp.x2),
            child: AnimatedSize(
              duration: context.motion(Motion.base),
              curve: Motion.ease,
              alignment: Alignment.topCenter,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x2),
                decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
                child: ExcludeSemantics(
                  child: Text(
                    tail.isEmpty ? empty : tail,
                    maxLines: Layout.jobLogLines,
                    overflow: TextOverflow.clip,
                    style: TextStyle(fontFamily: _mono, fontSize: Fs.xs, height: 1.45, color: tail.isEmpty ? p.text3 : p.text2),
                  ),
                ),
              ),
            ),
          ),
          RiseSwitcher(
            child: b.note != null
                ? Padding(
                    key: ValueKey(b.note),
                    padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
                    child: ExcludeSemantics(
                      child: Text(b.note!, style: small?.copyWith(color: p.text2), maxLines: 3, overflow: TextOverflow.ellipsis),
                    ),
                  )
                : const SizedBox.shrink(key: ValueKey('none')),
          ),
          SizedBox(
            height: 44, // 运行中没有按钮时卡片不跳
            child: Row(children: [
              Expanded(
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: SwapSwitcher(
                    child: Text(
                      shellStateLabel(b),
                      key: ValueKey(b.state),
                      style: small?.copyWith(
                          color: tone == JobTone.problem ? p.warning : p.text2,
                          fontWeight: tone == JobTone.problem ? Weights.title : null),
                    ),
                  ),
                ),
              ),
              FadeSwitcher(
                child: b.running
                    ? const SizedBox.shrink(key: ValueKey('busy'))
                    : Row(key: const ValueKey('done'), mainAxisSize: MainAxisSize.min, children: [
                        if (shellHasMore(b.output, Layout.jobLogLines))
                          TextButton(onPressed: () => showShellOutput(context, b), child: const Text('完整输出')),
                        CopyAction(text: '\$ ${b.command}\n${b.output.trimRight()}', tooltip: '复制命令和输出'),
                      ]),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 完整输出（就在消息里，不用再问服务器）：可选中复制。
Future<void> showShellOutput(BuildContext context, ShellBlock b) => showAppScrollSheet<void>(
      context,
      title: '完整输出',
      builder: (ctx) {
        final p = ctx.palette;
        return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x3, Sp.x3),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text([shellStateLabel(b), shellDuration(b.seconds)].where((s) => s.isNotEmpty).join(' · '), style: ctx.text.labelSmall),
                  const SizedBox(height: Sp.x1),
                  Text('\$ ${b.command}',
                      maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: _mono, fontSize: Fs.md, color: p.text)),
                ]),
              ),
              CopyAction(text: b.output, tooltip: '复制输出'),
            ]),
          ),
          SheetList(padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x5), children: [
            SelectableText(
              b.output.trim().isEmpty ? '（没有输出）' : b.output.trimRight(),
              style: TextStyle(fontFamily: _mono, fontSize: Fs.xs, height: 1.5, color: p.text2),
            ),
          ]),
        ]);
      },
    );
