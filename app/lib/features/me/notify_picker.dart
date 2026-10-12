// 定时脚本“什么时候告诉我”：失败时 / 每次 / 输出变了，三颗 ChoiceChip。只在 task_form.dart 的脚本表单里用（新建 / 编辑共用），
// 放在计划选择器下面；下面一行小字解释当前这档（换档时 SwapSwitcher 换字）。规则见 backend app/script_tasks.py；网页版 TaskSheet.tsx 同结构。
import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import 'task_labels.dart';

const _hints = {
  'failure': '成功了不打扰；失败时结果进 Home 收件箱。',
  'always': '每次跑完都把输出放进 Home 收件箱。',
  'change': '输出和上次不一样才告诉你，适合盯网页、价格、库存。',
};

class NotifyPicker extends StatefulWidget {
  const NotifyPicker({super.key, required this.controller});
  final ValueNotifier<String> controller;

  @override
  State<NotifyPicker> createState() => _NotifyPickerState();
}

class _NotifyPickerState extends State<NotifyPicker> {
  @override
  Widget build(BuildContext context) {
    final v = widget.controller.value;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
        for (final MapEntry(:key, :value) in notifyLabels.entries)
          ChoiceChip(
            key: Key('notify-$key'),
            label: Text(value),
            selected: v == key,
            showCheckmark: false,
            onSelected: (_) => setState(() => widget.controller.value = key),
          ),
      ]),
      const SizedBox(height: Sp.x2),
      SwapSwitcher(
        child: Align(
          key: ValueKey(v),
          alignment: Alignment.centerLeft,
          child: Text(_hints[v] ?? '', style: context.text.bodySmall?.copyWith(color: context.palette.text2)),
        ),
      ),
    ]);
  }
}
