// 计划清单卡的纯规则（v1.47，后端 app/plan.py）：进度、标题行、要不要默认收起、读屏文字。网页版 lib/plan.ts 同规则。
import 'block.dart';

int planDone(PlanBlock b) => b.items.where((i) => i.status == PlanStatus.completed).length;

double planRatio(PlanBlock b) => b.items.isEmpty ? 0 : planDone(b) / b.items.length;

bool planFinished(PlanBlock b) => b.items.isNotEmpty && planDone(b) == b.items.length;

/// 正在做的那一步（没有就 null）。
PlanItem? planCurrent(PlanBlock b) {
  for (final i in b.items) {
    if (i.status == PlanStatus.inProgress) return i;
  }
  return null;
}

/// 标题右侧的小字：“2/5”；全做完 “5 步都完成了”；这一轮停了还没做完 “停在 2/5”。
String planProgress(PlanBlock b) {
  final n = b.items.length, d = planDone(b);
  if (planFinished(b)) return '$n 步都完成了';
  if (b.settled) return '停在 $d/$n';
  return '$d/$n';
}

/// 全做完且这一轮结束：默认收起成一行（翻历史时不占地方），点一下展开。
bool planCollapsedByDefault(PlanBlock b) => b.settled && planFinished(b);

String planStatusLabel(PlanStatus s) => switch (s) {
      PlanStatus.pending => '待做',
      PlanStatus.inProgress => '进行中',
      PlanStatus.completed => '完成',
    };

String planSemantics(PlanBlock b) {
  final steps = [for (final (n, i) in b.items.indexed) '第${n + 1}步 ${i.content}，${planStatusLabel(i.status)}'];
  return ['计划，${planProgress(b)}', if (b.explanation?.isNotEmpty ?? false) '调整原因：${b.explanation}', ...steps].join('；');
}
