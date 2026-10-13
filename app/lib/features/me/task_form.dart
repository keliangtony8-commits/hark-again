// 定时任务（含面板）的唯一表单：列表页“新建”、详情页“编辑”、主页面板菜单“编辑面板”都用它。
// 名称 + 指令 + 计划（SchedulePicker；面板只能重复，不给“一次”）+ 模型 / 思考（TaskModelPicker，服务器只有一个不能调的模型时不出现）。网页版 features/me/TaskSheet.tsx 同结构。
// 新建时可带 [starter]（tasks_screen 的起步模板）：名称/指令/计划预填，用户改完再建。
// 返回要发给服务端的字段：新建 = 全量；编辑 = 只带改了的字段（没改返回空 map，调用方不发请求）。
// 面板改名时服务端会把 Home 卡片标题一起改（task_store.after_patch），客户端不用另外 PATCH 卡片。
// 定时脚本（[script] 或已有脚本任务 / 脚本模板）：同一张表单换成“命令”+ 计划 + 什么时候告诉我（NotifyPicker），没有模型选择（不调模型）；
// 新建时多发 kind:'script' 与 notify，类型建好不改（服务端 script_tasks.check）。
import 'package:flutter/widgets.dart';

import '../../theme/tokens.dart';

import '../../core/cron.dart';
import '../../models/resources.dart';
import '../../ui/sheets.dart';
import 'notify_picker.dart';
import 'schedule_picker.dart';
import 'task_library.dart';
import 'task_model_picker.dart';

Future<Map<String, dynamic>?> showTaskForm(BuildContext context, {ScheduledTask? task, TaskStarter? starter, bool script = false}) async {
  final panel = task?.isPanel ?? false;
  final log = task?.isLog ?? false; // 记录面板：只能改标题（内容按记下的每一笔算）
  final isScript = task?.isScript ?? (script || (starter?.script ?? false));
  final notify = ValueNotifier(task?.notify ?? 'failure');
  final plan = ValueNotifier(task == null ? TaskPlan.repeat(starter?.cron ?? cronPresets.first.$2) : TaskPlan.of(task));
  final initialModel = task == null ? const TaskModel() : TaskModel.of(task);
  final model = ValueNotifier(initialModel);
  final v = await showFormSheet(
    context,
    title: task == null ? (isScript ? '新定时脚本' : '新定时任务') : (panel ? '编辑面板' : (isScript ? '编辑脚本' : '编辑任务')),
    subtitle: log
        ? '在聊天里说一句就记一笔（“今天跑了 5 公里”），面板自动算今天、近 7 天和连续天数'
        : (isScript ? '到点直接在工作区跑这条命令，不调用模型、不花 token' : null),
    submit: task == null ? '创建' : '保存',
    fields: [
      FieldSpec('name', panel ? '标题' : '名称', hint: panel ? '上海天气' : '早间简报', initial: task?.name ?? starter?.name ?? ''),
      if (log)
        ...const <FieldSpec>[]
      else if (isScript)
        FieldSpec('prompt', '到点运行的命令', hint: 'python3 scripts/fetch.py', lines: 3, initial: task?.prompt ?? starter?.prompt ?? '')
      else
        FieldSpec('prompt', panel ? '每次刷新查什么、怎么展示' : '要我做什么',
            hint: '查今天上海的天气和我的日程，简短总结', lines: 2, initial: task?.prompt ?? starter?.prompt ?? ''),
    ],
    extra: log ? null : Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SchedulePicker(controller: plan, repeatOnly: panel),
      const SizedBox(height: Sp.x3),
      if (isScript) NotifyPicker(controller: notify) else TaskModelPicker(controller: model),
    ]),
  );
  final chosen = plan.value, picked = model.value, told = notify.value;
  plan.dispose();
  model.dispose();
  notify.dispose();
  if (v == null) return null;
  if (task == null) {
    return {
      'name': v['name'],
      'prompt': v['prompt'],
      ...chosen.toJson(),
      if (isScript) ...{'kind': 'script', 'notify': told} else ...picked.toJson(),
    };
  }
  if (log) return {if (v['name'] != task.name) 'name': v['name']};
  return {
    if (v['name'] != task.name) 'name': v['name'],
    if (v['prompt'] != task.prompt) 'prompt': v['prompt'],
    if (chosen.cron != task.cron || chosen.runAt != task.runAt) ...chosen.toJson(),
    if (!isScript && picked.model != initialModel.model) 'model': picked.model,
    if (!isScript && picked.reasoning != initialModel.reasoning) 'reasoning': picked.reasoning,
    if (isScript && told != task.notify) 'notify': told,
  };
}
