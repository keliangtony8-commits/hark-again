// 选“什么时候跑”：重复（cron 常用项）或一次（快捷时刻 + 滚轮自选）。只在 task_form.dart 的表单里用（新建/编辑共用）；
// 面板只能重复刷新：repeatOnly 去掉“重复/一次”切换。
// 计划与服务端同一规则：cron 与 run_at 二选一（docs/protocol.md 定时任务）。网页版 features/me/SchedulePicker.tsx 同结构。
import 'package:flutter/cupertino.dart' show CupertinoDatePicker, CupertinoDatePickerMode;
import 'package:flutter/material.dart';

import '../../core/cron.dart';
import '../../models/resources.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/motion.dart';

/// 一个计划：runAt 非空 = 一次性，否则按 cron 重复。
@immutable
class TaskPlan {
  const TaskPlan.repeat(this.cron) : runAt = null;
  const TaskPlan.once(DateTime this.runAt) : cron = '';
  factory TaskPlan.of(ScheduledTask t) => t.runAt != null ? TaskPlan.once(t.runAt!) : TaskPlan.repeat(t.cron);

  final String cron;
  final DateTime? runAt;
  bool get isOnce => runAt != null;

  /// 发给服务端的字段：两个都带，切换模式时另一个被清掉。
  Map<String, dynamic> toJson() => {'cron': cron, 'run_at': runAt?.toUtc().toIso8601String()};
}

/// 一次性的快捷时刻：1 小时后（取整到 5 分）/ 今晚 20:00（已过就不给）/ 明早 08:00 / 明晚 20:00。
List<(String, DateTime)> onceShortcuts(DateTime now) {
  final inHour = now.add(const Duration(hours: 1));
  final tonight = DateTime(now.year, now.month, now.day, 20);
  final tomorrow = DateTime(now.year, now.month, now.day + 1);
  return [
    ('1 小时后', DateTime(inHour.year, inHour.month, inHour.day, inHour.hour, (inHour.minute ~/ 5 + 1) * 5)),
    if (tonight.isAfter(now.add(const Duration(minutes: 10)))) ('今晚 20:00', tonight),
    ('明早 08:00', tomorrow.add(const Duration(hours: 8))),
    ('明晚 20:00', tomorrow.add(const Duration(hours: 20))),
  ];
}

/// 计划选择器。状态放在 [controller] 里，表单提交时读 controller.value。
class SchedulePicker extends StatefulWidget {
  const SchedulePicker({super.key, required this.controller, this.now, this.repeatOnly = false});
  final ValueNotifier<TaskPlan> controller;
  final bool repeatOnly; // 面板：只能按 cron 重复
  final DateTime? now; // 测试注入

  @override
  State<SchedulePicker> createState() => _SchedulePickerState();
}

class _SchedulePickerState extends State<SchedulePicker> {
  late final DateTime _now = widget.now ?? DateTime.now();
  late final _shortcuts = onceShortcuts(_now);
  late bool _custom = _isCustom(widget.controller.value);
  String _lastCron = cronPresets.first.$2;

  ValueNotifier<TaskPlan> get _c => widget.controller;

  bool _isCustom(TaskPlan p) => p.isOnce && !_shortcuts.any((s) => s.$2 == p.runAt);

  void _set(TaskPlan p) => setState(() => _c.value = p);

  void _mode(bool once) {
    if (once == _c.value.isOnce) return;
    if (!once) return _set(TaskPlan.repeat(_lastCron));
    _lastCron = _c.value.cron.isEmpty ? _lastCron : _c.value.cron;
    _custom = false;
    _set(TaskPlan.once(_shortcuts.first.$2));
  }

  @override
  Widget build(BuildContext context) {
    final plan = _c.value;
    final presets = [
      ...cronPresets,
      // 已有任务的 cron 不在常用项里：也显示出来，保持选中
      if (!plan.isOnce && plan.cron.isNotEmpty && !cronPresets.any((p) => p.$2 == plan.cron)) (describeCron(plan.cron), plan.cron),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (!widget.repeatOnly) ...[
      SegmentedButton<bool>(
        key: const Key('plan-mode'),
        showSelectedIcon: false,
        segments: const [
          ButtonSegment(value: false, label: Text('重复'), icon: Icon(Icons.repeat_rounded, size: 18)),
          ButtonSegment(value: true, label: Text('一次'), icon: Icon(Icons.alarm_rounded, size: 18)),
        ],
        selected: {plan.isOnce},
        onSelectionChanged: (s) => _mode(s.first),
      ),
      const SizedBox(height: Sp.x3),
      ],
      SwapSwitcher(
        child: Align(
          key: ValueKey(plan.isOnce),
          alignment: Alignment.centerLeft,
          child: Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
            if (!plan.isOnce)
              for (final (label, c) in presets)
                ChoiceChip(label: Text(label), selected: plan.cron == c, showCheckmark: false, onSelected: (_) => _set(TaskPlan.repeat(c)))
            else ...[
              for (final (label, at) in _shortcuts)
                ChoiceChip(
                  label: Text(label),
                  selected: !_custom && plan.runAt == at,
                  showCheckmark: false,
                  onSelected: (_) => setState(() {
                    _custom = false;
                    _c.value = TaskPlan.once(at);
                  }),
                ),
              ChoiceChip(
                key: const Key('plan-custom'),
                label: Text(_custom ? formatWhen(plan.runAt, now: _now) : '选时间…'),
                selected: _custom,
                showCheckmark: false,
                onSelected: (_) => setState(() => _custom = true),
              ),
            ],
          ]),
        ),
      ),
      RiseSwitcher(
        child: plan.isOnce && _custom
            ? SizedBox(
                key: const ValueKey('wheel'),
                height: 168,
                child: CupertinoDatePicker(
                  mode: CupertinoDatePickerMode.dateAndTime,
                  use24hFormat: true,
                  minimumDate: _now,
                  initialDateTime: plan.runAt!.isBefore(_now) ? _now : plan.runAt,
                  onDateTimeChanged: (t) => setState(() => _c.value = TaskPlan.once(t)),
                ),
              )
            : null,
      ),
    ]);
  }
}
