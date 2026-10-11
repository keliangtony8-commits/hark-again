// 定时任务（含面板）的唯一表单：列表页“新建”、详情页“编辑”、主页面板菜单“编辑面板”都用它。
// 名称 + 指令 + 计划（SchedulePicker；面板只能重复，不给“一次”）。网页版 features/me/TaskSheet.tsx 同结构。
// 新建时可带 [starter]（tasks_screen 的起步模板）：名称/指令/计划预填，用户改完再建。
// 返回要发给服务端的字段：新建 = 全量；编辑 = 只带改了的字段（没改返回空 map，调用方不发请求）。
// 面板改名时服务端会把 Home 卡片标题一起改（task_store.after_patch），客户端不用另外 PATCH 卡片。
import 'package:flutter/widgets.dart';

import '../../core/cron.dart';
import '../../models/resources.dart';
import '../../ui/sheets.dart';
import 'schedule_picker.dart';
import 'task_library.dart';

Future<Map<String, dynamic>?> showTaskForm(BuildContext context, {ScheduledTask? task, TaskStarter? starter}) async {
  final panel = task?.isPanel ?? false;
  final plan = ValueNotifier(task == null ? TaskPlan.repeat(starter?.cron ?? cronPresets.first.$2) : TaskPlan.of(task));
  final v = await showFormSheet(
    context,
    title: task == null ? '新定时任务' : (panel ? '编辑面板' : '编辑任务'),
    submit: task == null ? '创建' : '保存',
    fields: [
      FieldSpec('name', panel ? '标题' : '名称', hint: panel ? '上海天气' : '早间简报', initial: task?.name ?? starter?.name ?? ''),
      FieldSpec('prompt', panel ? '每次刷新查什么、怎么展示' : '要我做什么',
          hint: '查今天上海的天气和我的日程，简短总结', lines: 2, initial: task?.prompt ?? starter?.prompt ?? ''),
    ],
    extra: SchedulePicker(controller: plan, repeatOnly: panel),
  );
  final chosen = plan.value;
  plan.dispose();
  if (v == null) return null;
  if (task == null) return {'name': v['name'], 'prompt': v['prompt'], ...chosen.toJson()};
  return {
    if (v['name'] != task.name) 'name': v['name'],
    if (v['prompt'] != task.prompt) 'prompt': v['prompt'],
    if (chosen.cron != task.cron || chosen.runAt != task.runAt) ...chosen.toJson(),
  };
}
