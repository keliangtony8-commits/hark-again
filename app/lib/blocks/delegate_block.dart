// 子助手卡（v1.48）：主助手把几件独立的事并行交给子助手，聊天里一张卡实时看它们各自做到哪。
//   [⑂] 子助手                                  1/2 完成
//   ● 查竞品定价                                          （在做：脉冲点）
//     第 3 步 · 正在搜索
//   ✓ 整理用户评论                                   ⌄   （完成：点开看交回的结论）
//     7 步 · 42 秒
// 状态变了：标记 SwapSwitcher 换、副标题 SwapSwitcher 淡换；结论 AnimatedSize 展开 + TurnIcon；行入场 FadeSlideIn 错开。
// v1.97 追问：这一轮结束后展开一个子任务，结论下面有“追问”——弹出输入框，发出去的消息让主助手接着问这个子助手
// （它记得自己查过 / 做过的；服务器 agent/subagent_threads.py）。BlockActions 没给 onFollowUp（如 Home）就不显示。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../models/delegate.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import '../ui/sheets.dart';
import 'block_actions.dart';
import 'block_frame.dart';

class DelegateBlockView extends StatelessWidget {
  const DelegateBlockView(this.block, {super.key});
  final DelegateBlock block;

  @override
  Widget build(BuildContext context) {
    final b = block;
    if (b.tasks.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    return Semantics(
      container: true,
      label: delegateSemantics(b),
      child: BlockFrame(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
        child: ExcludeSemantics(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Icon(Icons.call_split_rounded, size: 18, color: p.text2),
              const SizedBox(width: Sp.x2),
              Expanded(child: Text('子助手', style: context.text.labelLarge)),
              SwapSwitcher(
                child: Text(delegateProgress(b),
                    key: ValueKey(delegateProgress(b)), style: context.text.labelSmall?.copyWith(color: p.text3)),
              ),
            ]),
            const SizedBox(height: Sp.x1),
            for (final (n, t) in b.tasks.indexed)
              FadeSlideIn(key: ValueKey(t.title), delay: Motion.stagger(n), child: _Task(t, block: b)),
          ]),
        ),
      ),
    );
  }
}

class _Task extends StatefulWidget {
  const _Task(this.task, {required this.block});
  final DelegateTask task;
  final DelegateBlock block;
  bool get live => block.live;

  @override
  State<_Task> createState() => _TaskState();
}

class _TaskState extends State<_Task> {
  bool _open = false;

  Future<void> _follow(void Function(String, String, String) send, DelegateTask t) async {
    final r = await showFormSheet(
      context,
      title: delegateFollowTitle(t.title),
      subtitle: '它记得自己查过、做过的，接着问不用从头再来。主助手会把你的问题转给它，再整理它的回答。',
      fields: const [FieldSpec('text', '想接着问什么', hint: '比如：第四家的运费呢？', lines: 3)],
      submit: '发送',
    );
    final text = r?['text'] ?? '';
    if (text.isNotEmpty && t.id != null) send(t.id!, t.title, text);
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.task;
    final p = context.palette;
    final onFollow = BlockActions.of(context)?.onFollowUp;
    final canFollow = onFollow != null && delegateCanFollow(widget.block, t);
    final canOpen = delegateHasResult(t) || canFollow;
    final open = _open && canOpen;
    final line = delegateTaskLine(t);
    final bad = t.state == DelegateState.failed;
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Pressable(
          onTap: canOpen ? () => setState(() => _open = !_open) : null,
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox.square(
              dimension: 20,
              child: Center(
                child: SwapSwitcher(
                  child: KeyedSubtree(
                    key: ValueKey('${t.state}${widget.live}'),
                    child: switch (t.state) {
                      DelegateState.running when widget.live => PulseDot(color: p.accent, size: 8),
                      DelegateState.running => Icon(Icons.adjust_rounded, size: 18, color: p.text3),
                      DelegateState.done => Icon(Icons.check_circle_rounded, size: 18, color: p.text2),
                      DelegateState.partial => Icon(Icons.timelapse_rounded, size: 18, color: p.warning),
                      DelegateState.failed => Icon(Icons.error_outline_rounded, size: 18, color: p.danger),
                      DelegateState.stopped => Icon(Icons.stop_circle_outlined, size: 18, color: p.text3),
                    },
                  ),
                ),
              ),
            ),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(t.title, style: context.text.bodyMedium?.copyWith(fontWeight: Weights.title), maxLines: 1, overflow: TextOverflow.ellipsis),
                SwapSwitcher(
                  child: Text(line,
                      key: ValueKey(line),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: context.text.labelSmall?.copyWith(color: bad ? p.danger : p.text3)),
                ),
              ]),
            ),
            if (canOpen)
              TurnIcon(open: open, turns: 0.5, child: Icon(Icons.expand_more_rounded, size: 18, color: p.text3)),
          ]),
        ),
        AnimatedSize(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          alignment: Alignment.topCenter,
          child: open
              ? Padding(
                  padding: const EdgeInsets.only(top: Sp.x2, left: 20 + Sp.x2),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    if (delegateHasResult(t))
                      Container(
                        padding: const EdgeInsets.all(Sp.x3),
                        constraints: const BoxConstraints(maxHeight: 240),
                        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
                        child: SingleChildScrollView(
                          child: SelectableText(t.result!, style: context.text.bodySmall?.copyWith(color: p.text2)),
                        ),
                      ),
                    if (canFollow)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: _FollowButton(onTap: () => _follow(onFollow, t)),
                      ),
                  ]),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}

class _FollowButton extends StatelessWidget {
  const _FollowButton({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Pressable(
      semanticLabel: '追问这个子助手',
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: Sp.x2),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.reply_rounded, size: 16, color: p.text2),
          const SizedBox(width: Sp.x1),
          Text('追问', style: context.text.labelMedium?.copyWith(color: p.text2)),
        ]),
      ),
    );
  }
}
