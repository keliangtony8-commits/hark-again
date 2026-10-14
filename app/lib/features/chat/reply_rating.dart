// 回复下的 👍 / 👎（v2.64，对标 Hark / ChatGPT 的回复评价）：操作行末尾两颗安静的小图标。
// 👍 点一下记“有用”、再点取消；👎 弹原因单（答错了 / 没做完 / 太慢或卡住了 / 别的问题 + 可选一句补充），
// 已经是 👎 时再点 = 取消。评过的那颗画实心（PopSwitcher 原地换），另一颗照常可点、点了就换成它。
// 本机先换、服务器没收下换回原样（ChatController.rate）。报告里存什么只在后端 app/feedback.py。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api.dart';
import '../../models/feedback.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/sheets.dart';

typedef RateReply = Future<void> Function(String? kind, {String? note});

class ReplyRating extends StatelessWidget {
  const ReplyRating({super.key, required this.current, required this.onRate});
  final String? current;
  final RateReply onRate;

  Future<void> _send(BuildContext context, String? kind, {String? note}) async {
    HapticFeedback.selectionClick();
    try {
      await onRate(kind, note: note);
      if (context.mounted) showToast(context, feedbackToast(kind));
    } on ApiError catch (e) {
      if (context.mounted) showToast(context, e.isNetwork ? '没连上服务器，评价没记下' : e.message);
    }
  }

  Future<void> _down(BuildContext context) async {
    if (isBadFeedback(current)) return _send(context, null);
    final picked = await showAppSheet<(String, String)>(context, builder: (_) => const _ReasonSheet());
    if (picked != null && context.mounted) await _send(context, picked.$1, note: picked.$2);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final up = current == feedbackGood;
    final down = isBadFeedback(current);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      QuietAction(
        tooltip: up ? '取消“有用”' : '有用',
        onPressed: () => _send(context, up ? null : feedbackGood),
        icon: up
            ? Icon(Icons.thumb_up_alt_rounded, key: const ValueKey('up-on'), color: p.text2)
            : const Icon(Icons.thumb_up_alt_outlined, key: ValueKey('up')),
      ),
      QuietAction(
        tooltip: down ? '取消评价' : '不好',
        onPressed: () => _down(context),
        icon: down
            ? Icon(Icons.thumb_down_alt_rounded, key: const ValueKey('down-on'), color: p.text2)
            : const Icon(Icons.thumb_down_alt_outlined, key: ValueKey('down')),
      ),
    ]);
  }
}

/// 👎 的原因单：先选一个原因（必选），补充一句可不填。返回 (原因, 补充)。
class _ReasonSheet extends StatefulWidget {
  const _ReasonSheet();

  @override
  State<_ReasonSheet> createState() => _ReasonSheetState();
}

class _ReasonSheetState extends State<_ReasonSheet> {
  final _note = TextEditingController();
  String? _kind;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, MediaQuery.viewInsetsOf(context).bottom + Sp.x5),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('哪里不好？', style: context.text.titleLarge),
            const SizedBox(height: Sp.x1),
            Text('会连同这条回复和每一步的记录存一份报告，在“我的 → 反馈”里能看到。', style: context.text.bodySmall),
            const SizedBox(height: Sp.x4),
            Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
              for (final (k, label) in feedbackReasons)
                ChoiceChip(
                  key: ValueKey('reason-$k'),
                  label: Text(label),
                  selected: k == _kind,
                  showCheckmark: false,
                  onSelected: (_) => setState(() => _kind = k),
                ),
            ]),
            const SizedBox(height: Sp.x4),
            TextField(
              controller: _note,
              minLines: 2,
              maxLines: 5,
              decoration: const InputDecoration(labelText: '补充一句（可不填）', hintText: '比如：应该先问我要哪天的票'),
            ),
            const SizedBox(height: Sp.x4),
            FilledButton(
              onPressed: _kind == null ? null : () => Navigator.pop(context, (_kind!, _note.text.trim())),
              child: const Text('提交'),
            ),
          ]),
        ),
      );
}
