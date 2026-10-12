// 定时任务用哪个模型、想多深：只在 task_form.dart 的表单里用（新建 / 编辑共用），放在计划选择器下面。
// 列表与规则全来自对话那一套（model_choice.dart 的 modelCatalogProvider + ModelCatalog / ModelEfforts）：
// 选默认存 null（以后服务器改默认会跟着变）；只有一个模型且它不能调思考 → 整块不出现。
// 换模型时，原来选的思考档新模型没有 → 清回默认（不留看不见的选择）；思考那一行按当前模型淡入 / 收起。
// 网页版 features/me/TaskModelPicker.tsx 同结构。服务端规则见 backend app/task_store.py（model_choice / reasoning_choice）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import '../chat/model_choice.dart' show modelCatalogProvider;

/// 任务的模型选择：两项都是 null = 默认。
@immutable
class TaskModel {
  const TaskModel({this.model, this.reasoning});
  factory TaskModel.of(ScheduledTask t) => TaskModel(model: t.model, reasoning: t.reasoning);
  final String? model, reasoning;

  Map<String, dynamic> toJson() => {'model': model, 'reasoning': reasoning};

  @override
  bool operator ==(Object other) => other is TaskModel && other.model == model && other.reasoning == reasoning;
  @override
  int get hashCode => Object.hash(model, reasoning);
}

/// 一句话描述（详情页“结果放进 Home 收件箱”后面那段）：都是默认 → 空串；否则“深度 · 思考 高”。
String taskModelLabel(ScheduledTask t, ModelCatalog? cat) {
  if (cat == null || (t.model == null && t.reasoning == null)) return '';
  final m = cat.effective(t.model);
  if (m == null) return '';
  final eff = cat.effortsFor(m.id);
  final level = eff?.effective(t.reasoning);
  return [
    if (t.model != null) m.label,
    if (level != null && level.id != eff!.defaultId) '思考 ${level.label}',
  ].join(' · ');
}

class TaskModelPicker extends ConsumerWidget {
  const TaskModelPicker({super.key, required this.controller});
  final ValueNotifier<TaskModel> controller;

  void _model(ModelCatalog cat, String id) {
    final next = cat.toChoice(id);
    final r = controller.value.reasoning;
    final levels = cat.effortsFor(id)?.levels ?? const <EffortLevel>[];
    controller.value = TaskModel(model: next, reasoning: levels.any((l) => l.id == r) ? r : null);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cat = ref.watch(modelCatalogProvider).value;
    if (cat == null) return const SizedBox.shrink();
    return ValueListenableBuilder<TaskModel>(
      valueListenable: controller,
      builder: (context, v, _) {
        final m = cat.effective(v.model);
        final efforts = m == null ? null : cat.effortsFor(m.id);
        if (m == null || (!cat.selectable && efforts == null)) return const SizedBox.shrink();
        final level = efforts?.effective(v.reasoning);
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          if (cat.selectable)
            _Line(label: '模型', children: [
              for (final o in cat.options)
                ChoiceChip(
                  key: Key('task-model-${o.id}'),
                  label: Text(o.label),
                  selected: o.id == m.id,
                  showCheckmark: false,
                  onSelected: (_) => _model(cat, o.id),
                ),
            ]),
          RiseSwitcher(
            child: efforts == null
                ? null
                : Padding(
                    key: ValueKey('efforts-${m.id}'),
                    padding: EdgeInsets.only(top: cat.selectable ? Sp.x2 : 0),
                    child: _Line(label: '思考', children: [
                      for (final l in efforts.levels)
                        Tooltip(
                          message: l.id == efforts.defaultId ? '默认 · ${l.description}' : l.description,
                          child: ChoiceChip(
                            key: Key('task-effort-${l.id}'),
                            label: Text(l.label),
                            selected: l.id == level!.id,
                            showCheckmark: false,
                            onSelected: (_) => controller.value = TaskModel(model: v.model, reasoning: efforts.toChoice(l.id)),
                          ),
                        ),
                    ]),
                  ),
          ),
        ]);
      },
    );
  }
}

/// 一行：左边小标题（固定宽，两行对齐），右边一排 Chip。
class _Line extends StatelessWidget {
  const _Line({required this.label, required this.children});
  final String label;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        SizedBox(width: Sp.x7, child: Text(label, style: context.text.labelMedium?.copyWith(color: context.palette.text2))),
        Expanded(child: Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: children)),
      ]);
}
