// Home“今天”：今天排着的定时任务按钟点排成一条日程（对标 Hark 主页“今天接下来是什么 + 当天其余按小时”）。
// 纯函数，只管“哪些、几点、什么状态、怎么说”；画法在 home_screen.dart _Today。网页版 features/home/todayAgenda.ts 同规则同措辞。
import '../../core/cron.dart';
import '../../models/resources.dart';

export '../me/task_library.dart' show prepDayPrompt, morningBrief, briefTaskOf;

/// Home“今天”段末的胶囊：开一段新对话让助手准备今天（后端 day_overview + 技能 prep-my-day 出简报卡）。
const prepDayLabel = '帮我准备今天';

/// 胶囊下的小按钮：还没排早间简报时，一键打开预填好的定时任务表单（每天 07:00，可改）。排了就不再出现——
/// 简报任务本身已是今天日程里的一行。
const scheduleBriefLabel = '每天早上自动准备';

/// 已完成 / 失败 / 进行中（到点了或排队中）/ 下一个 / 稍后 / 已暂停（连续失败被自动停了，今天本该跑）。
enum AgendaState { done, failed, running, next, later, paused }

class AgendaItem {
  const AgendaItem(this.task, this.at, this.state);
  final ScheduledTask task;

  /// 今天的那个时刻（本地时间）。
  final DateTime at;
  final AgendaState state;

  String get time => clockOf(at);

  /// 顺利跑完的一项：行变淡，让还没发生的更显眼。失败不变淡——淡掉的警示字发灰发脏，又正是要人看见的（v1.02 截图）。
  bool get faded => state == AgendaState.done;
}

/// HH:MM（等宽钟点列、摘要、“现在”标记共用）。
String clockOf(DateTime t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

/// “现在”标记插在第几行之前：第一件钟点晚于此刻的那行。只在前后都有事时才有意义（全在前或全在后 = null），
/// 否则一条线贴在列表头尾只是噪音。
int? agendaNowAt(List<AgendaItem> items, DateTime now) {
  final i = items.indexWhere((x) => x.at.isAfter(now));
  return i <= 0 ? null : i;
}

/// 今天这条任务排在几点：一次性任务 = 计划时刻正好在今天；重复任务 = cron 今天的时刻。不在今天 = null。
DateTime? todaySlot(ScheduledTask t, DateTime now) {
  if (t.isOnce) {
    final l = t.runAt!.toLocal();
    return l.year == now.year && l.month == now.month && l.day == now.day ? l : null;
  }
  return cronTodayAt(t.cron, now);
}

/// 今天的日程：只放“报告”类任务（面板按自己的节奏刷新，不算一件事）；手动停掉的不放（用户自己不要了），
/// 自动暂停的放（今天本该跑却不会跑，要让人看见）；一次性任务跑完了也留着显示结果。按钟点排序。
List<AgendaItem> todayAgenda(List<ScheduledTask> tasks, DateTime now) {
  final slots = <(ScheduledTask, DateTime)>[];
  for (final t in tasks) {
    if (t.isPanel) continue;
    if (!t.active && !t.autoPaused && !t.done) continue;
    final at = todaySlot(t, now);
    if (at != null) slots.add((t, at));
  }
  slots.sort((a, b) => a.$2.compareTo(b.$2));
  var nextGiven = false;
  return [
    for (final (t, at) in slots)
      AgendaItem(t, at, () {
        if (t.autoPaused) return AgendaState.paused;
        if (t.runRequested) return AgendaState.running;
        final last = t.lastRunAt?.toLocal();
        if (t.done || (last != null && !last.isBefore(at))) return t.lastFailed ? AgendaState.failed : AgendaState.done;
        if (!at.isAfter(now)) return AgendaState.running; // 到点了，worker 马上接手
        if (nextGiven) return AgendaState.later;
        nextGiven = true;
        return AgendaState.next;
      }()),
  ];
}

/// 行尾小字：下一个 / 进行中… / 已完成；失败与暂停走行的 problem（警示色），稍后没有字。
String agendaHint(AgendaItem i) => switch (i.state) {
      AgendaState.next => '下一个',
      AgendaState.running => '进行中…',
      AgendaState.done => '已完成',
      _ => '',
    };

/// 失败 / 已暂停：放在副标题最前面用警示色（ListRow.problem）。
String? agendaProblem(AgendaItem i) => switch (i.state) {
      AgendaState.failed => '失败',
      AgendaState.paused => '已暂停',
      _ => null,
    };

/// 副标题：暂停的说为什么（连续失败 N 次），其余是计划本身的人话（每天 08:00 → 只说“每天”太重复，用规则名）。
String agendaDetail(AgendaItem i) =>
    i.state == AgendaState.paused ? '连续失败 ${i.task.failStreak} 次，今日不再运行' : (i.task.isOnce ? '一次性' : _repeat(i.task.cron));

String _repeat(String cron) {
  final f = cron.trim().split(RegExp(r'\s+'));
  if (f.length < 5) return '重复';
  if (f[4] == '1-5') return '工作日';
  if (f[4] != '*') return '每周';
  if (f[2] != '*') return '每月';
  return '每天';
}

/// 区块标题旁的一句话：还剩 2 件 · 下一个 21:00 / 今天的 3 项均已完成 / 今天没有排定的任务。
String agendaSummary(List<AgendaItem> items) {
  if (items.isEmpty) return '今天没有排定的任务';
  final next = items.where((i) => i.state == AgendaState.next).firstOrNull;
  final left = items.where((i) => i.state == AgendaState.next || i.state == AgendaState.later || i.state == AgendaState.running).length;
  if (left == 0) return '今天的 ${items.length} 项均已完成';
  return next == null ? '还剩 $left 件' : '还剩 $left 件 · 下一个 ${next.time}';
}
