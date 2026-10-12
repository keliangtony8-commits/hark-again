// 子助手卡的纯规则（v1.48，后端 agent/subagent.py）：标题行进度、每个子任务的副标题、能不能展开看结论、读屏文字。
// 网页版 lib/delegate.ts 同规则。
import '../ui/format.dart';
import 'block.dart';

bool delegateEnded(DelegateTask t) => t.state != DelegateState.running;

int delegateDone(DelegateBlock b) => b.tasks.where((t) => t.state == DelegateState.done).length;

/// 标题右侧小字：进行中 “1/3 完成”；全结束且都完成 “3 个都完成了”；全结束有没成的 “完成 2/3”。
String delegateProgress(DelegateBlock b) {
  final n = b.tasks.length, d = delegateDone(b);
  if (b.tasks.every(delegateEnded)) return d == n ? '$n 个都完成了' : '完成 $d/$n';
  return '$d/$n 完成';
}

String delegateStateLabel(DelegateState s) => switch (s) {
      DelegateState.running => '在做',
      DelegateState.done => '完成',
      DelegateState.partial => '交了半截',
      DelegateState.failed => '没成',
      DelegateState.stopped => '被停下',
    };

/// 子任务标题下的一行：在做 “第 3 步 · 正在搜索”；完成 “7 步 · 42 秒”；没成 / 半截 给原因。
String delegateTaskLine(DelegateTask t) {
  final took = [if (t.steps > 0) '${t.steps} 步', if (t.seconds != null) formatDuration(t.seconds! * 1000)].join(' · ');
  return switch (t.state) {
    DelegateState.running => t.now?.isNotEmpty ?? false
        ? (t.steps > 0 ? '第 ${t.steps} 步 · ${t.now}' : t.now!)
        : (t.steps > 0 ? '第 ${t.steps} 步 · 在想' : '刚开始'),
    DelegateState.done => took.isEmpty ? '完成' : took,
    DelegateState.partial || DelegateState.failed => t.note?.isNotEmpty ?? false ? t.note! : delegateStateLabel(t.state),
    DelegateState.stopped => '这一轮被停下了',
  };
}

/// 有结论可看：结束了且带 result。
bool delegateCanOpen(DelegateTask t) => delegateEnded(t) && (t.result?.trim().isNotEmpty ?? false);

String delegateSemantics(DelegateBlock b) => [
      '子助手，${delegateProgress(b)}',
      for (final t in b.tasks) '${t.title}，${delegateStateLabel(t.state)}，${delegateTaskLine(t)}',
    ].join('；');
