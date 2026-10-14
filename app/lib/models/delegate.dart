// 子助手卡的纯规则（v1.48，后端 agent/subagent.py）：标题行进度、每个子任务的副标题、能不能展开看结论、读屏文字。
// 网页版 lib/delegate.ts 同规则。
import '../ui/format.dart';
import 'block.dart';

bool delegateEnded(DelegateTask t) => t.state != DelegateState.running;

int delegateDone(DelegateBlock b) => b.tasks.where((t) => t.state == DelegateState.done).length;

/// 标题右侧小字：进行中与结束有失败的都是 “已完成 2/3”；全部完成 “3 项全部完成”。
String delegateProgress(DelegateBlock b) {
  final n = b.tasks.length, d = delegateDone(b);
  if (b.tasks.every(delegateEnded)) return d == n ? '$n 项全部完成' : '已完成 $d/$n';
  return '已完成 $d/$n';
}

String delegateStateLabel(DelegateState s) => switch (s) {
      DelegateState.running => '进行中',
      DelegateState.done => '已完成',
      DelegateState.partial => '部分完成',
      DelegateState.failed => '失败',
      DelegateState.stopped => '已停止',
    };

/// 子任务标题下的一行：在做 “第 3 步 · 正在搜索”；完成 “7 步 · 42 秒”；没成 / 半截 给原因。续问的那次前面加“第 2 轮 · ”。
String delegateTaskLine(DelegateTask t) {
  final line = _taskLine(t);
  return t.round > 1 ? '第 ${t.round} 轮 · $line' : line;
}

String _taskLine(DelegateTask t) {
  final took = [if (t.steps > 0) '${t.steps} 步', if (t.seconds != null) formatDuration(t.seconds! * 1000)].join(' · ');
  return switch (t.state) {
    DelegateState.running => t.now?.isNotEmpty ?? false
        ? (t.steps > 0 ? '第 ${t.steps} 步 · ${t.now}' : t.now!)
        : (t.steps > 0 ? '第 ${t.steps} 步 · 在想' : '刚开始'),
    DelegateState.done => took.isEmpty ? '已完成' : took,
    DelegateState.partial || DelegateState.failed => t.note?.isNotEmpty ?? false ? t.note! : delegateStateLabel(t.state),
    DelegateState.stopped => '本轮已停止',
  };
}

/// 有结论可看：结束了且带 result。
bool delegateHasResult(DelegateTask t) => delegateEnded(t) && (t.result?.trim().isNotEmpty ?? false);

/// 能接着问（v1.97，服务器 agent/subagent_threads.py）：这一轮已经结束、子任务带编号（老卡片没有）、结束了。
/// 上下文被清掉的情况服务器会照实说（gone），这里不猜。
bool delegateCanFollow(DelegateBlock b, DelegateTask t) => !b.live && delegateEnded(t) && (t.id?.isNotEmpty ?? false);

/// 能展开：有结论，或者能追问（没结论的也给个追问入口）。
bool delegateCanOpen(DelegateBlock b, DelegateTask t) => delegateHasResult(t) || delegateCanFollow(b, t);

/// 追问弹窗的标题、气泡上的标签。
String delegateFollowTitle(String title) => '追问「$title」';

String agentChipLabel(AgentBlock a) => a.target == null ? a.name : '追问 · ${a.title?.isNotEmpty ?? false ? a.title! : '子任务'}';

String agentChipSemantics(AgentBlock a) =>
    a.target == null ? '交给${a.name}' : '追问子助手 ${a.title ?? ''}${a.gone ? '，其上下文已失效' : ''}';

String delegateSemantics(DelegateBlock b) => [
      '子助手，${delegateProgress(b)}',
      for (final t in b.tasks) '${t.title}，${delegateStateLabel(t.state)}，${delegateTaskLine(t)}${delegateCanFollow(b, t) ? '，可以追问' : ''}',
    ].join('；');
