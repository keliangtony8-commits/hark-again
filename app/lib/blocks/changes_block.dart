// 改动卡（v1.68）：这一轮助手用 write_file / edit_file 改过的文件，每个一份净 diff，可整轮撤销。
//   [文件图标] 改了 3 个文件            +12 −3   撤销
//   notes.md                         +1 −1  ›    （点开看 diff，RiseSwitcher）
//   out/report.md               新建 +8      ›
//   （小字：2 个大文件不能撤销 / 文件已回到这一轮之前的样子）
// 撤销：confirmDanger 确认 → BlockActions.onUndoChanges（服务器核对“之后没再被改过”才恢复）；
// 成功后服务器回的消息替换本条，卡片变“已撤销”（图标 PopSwitcher、标题 FadeSwitcher、文件名划掉）。
// v2.18 内容拆成 ChangesPanel（不带外框）：后台任务卡里嵌同一块（scope = job，撤销走 /api/jobs/{id}/changes/undo）。
import 'package:flutter/material.dart';

import '../models/block.dart';
import '../models/changes.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/diff_view.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import '../ui/sheets.dart';
import 'block_actions.dart';
import 'block_frame.dart';

class ChangesBlockView extends StatelessWidget {
  const ChangesBlockView(this.block, {super.key});
  final ChangesBlock block;

  @override
  Widget build(BuildContext context) {
    if (block.files.isEmpty) return const SizedBox.shrink();
    final undo = BlockActions.of(context)?.onUndoChanges;
    return BlockFrame(
      padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x2, Sp.x3),
      child: ChangesPanel(block, onUndo: undo == null ? null : () => undo(block.token)),
    );
  }
}

/// 改动列表本体：标题行（合计 + 撤销）、每个文件一行（点开看 diff）、卡底小字。
/// onUndo 返回 null = 成功（调用方负责换上新数据）；否则是给用户看的原因。
class ChangesPanel extends StatefulWidget {
  const ChangesPanel(this.block, {super.key, this.onUndo, this.scope = ChangesScope.turn});
  final ChangesBlock block;
  final Future<String?> Function()? onUndo;
  final ChangesScope scope;

  @override
  State<ChangesPanel> createState() => _ChangesPanelState();
}

class _ChangesPanelState extends State<ChangesPanel> {
  bool _busy = false;
  String? _open; // 展开 diff 的那个文件

  Future<void> _undo() async {
    final undo = widget.onUndo;
    if (undo == null) return;
    final (title, text) = changesConfirm(widget.block, scope: widget.scope);
    final ok = await confirmDanger(context, title: title, text: text, action: '撤销');
    if (!ok || !mounted) return;
    setState(() => _busy = true);
    final err = await undo();
    if (!mounted) return;
    setState(() => _busy = false);
    if (err != null) showToast(context, err);
  }

  @override
  Widget build(BuildContext context) {
    final b = widget.block;
    final scope = widget.scope;
    if (b.files.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    final small = context.text.labelSmall;
    final (added, removed) = changesTotals(b);
    final note = changesNote(b, scope: scope);
    final canUndo = changesUndoable(b) && widget.onUndo != null;
    return Semantics(
      container: true,
      label: changesSemantics(b, scope: scope),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            PopSwitcher(
              child: Icon(b.undone ? Icons.undo_rounded : Icons.difference_outlined,
                  key: ValueKey(b.undone), size: 18, color: p.text2),
            ),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: FadeSwitcher(
                alignment: AlignmentDirectional.centerStart,
                child: Text(changesTitle(b, scope: scope), key: ValueKey(b.undone), style: context.text.labelLarge),
              ),
            ),
            if (!b.undone) ...[
              Text('+$added', style: small?.copyWith(fontFamily: monoFont, color: p.success)),
              if (removed > 0) Text(' −$removed', style: small?.copyWith(fontFamily: monoFont, color: p.danger)),
            ],
            FadeSwitcher(
              child: canUndo
                  ? TextButton(
                      key: const ValueKey('undo'),
                      onPressed: _busy ? null : _undo,
                      style: TextButton.styleFrom(visualDensity: VisualDensity.compact, foregroundColor: p.text2),
                      child: PopSwitcher(
                        child: _busy
                            ? SizedBox.square(key: const ValueKey('busy'), dimension: 14, child: CircularProgressIndicator(strokeWidth: 2, color: p.text2))
                            : const Text('撤销', key: ValueKey('label')),
                      ),
                    )
                  : const SizedBox(key: ValueKey('none'), width: Sp.x2, height: A11y.minTap - Sp.x3),
            ),
          ]),
          for (final (n, f) in b.files.indexed)
            FadeSlideIn(
              key: ValueKey(f.path),
              delay: Motion.stagger(n),
              child: FileDiffRow(f,
                  undone: b.undone,
                  tag: changeTag(f),
                  open: _open == f.path,
                  onTap: f.expandable ? () => setState(() => _open = _open == f.path ? null : f.path) : null),
            ),
          if (b.more > 0)
            Padding(
              padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
              child: Text('还有 ${b.more} 个文件', style: small?.copyWith(color: p.text3)),
            ),
          RiseSwitcher(
            child: note == null
                ? null
                : Padding(
                    key: ValueKey(note),
                    padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
                    child: Text(note, style: small?.copyWith(color: p.text3)),
                  ),
          ),
        ]),
    );
  }
}
