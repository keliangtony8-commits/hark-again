// 用户自己跑的命令（输入框里 !命令，后端 app/user_shell.py）：不经过助手，直接在这段对话的电脑上前台执行。
// 这里是纯规则——认不认命令、卡片状态文案、用时、读屏；卡片在 blocks/shell_block.dart，输入框提示在 composer。
// 网页版 frontend/src/lib/shell.ts 同一套规则。
import 'block.dart';
import 'job.dart';

const shellPrefixes = ['!', '！']; // 中文输入法的全角叹号也算（和后端 PREFIXES 一致）

/// 输入框里这段字会不会被当成命令：去掉首尾空白后以 ! / ！ 开头、后面还有东西。带附件的消息不算（调用方判断）。
String? shellCommandOf(String text) {
  final t = text.trim();
  if (t.isEmpty || !shellPrefixes.contains(t[0])) return null;
  final cmd = t.substring(1).trim();
  return cmd.isEmpty ? null : cmd;
}

/// 卡片语气：沿用后台任务卡的四种（运行中 / 好了 / 出问题 / 安静地停了），两种卡一眼同一套语言。
JobTone shellTone(String state) => switch (state) {
      'running' => JobTone.running,
      'done' => JobTone.ok,
      'stopped' => JobTone.quiet,
      _ => JobTone.problem,
    };

String shellStateLabel(ShellBlock b) => switch (b.state) {
      'running' => '运行中',
      'done' => '已完成',
      'failed' => b.exitCode == null ? '失败' : '失败 · 退出码 ${b.exitCode}',
      'timeout' => '超时被终止',
      'stopped' => '已停止',
      'refused' => '已拦下，没有执行',
      'error' => '没拿到结果',
      _ => b.state,
    };

/// 用时：10 秒内带一位小数（命令多半很快），再长按后台任务卡的写法。没有用时（被拦下 / 运行中）= 空。
String shellDuration(double? seconds) {
  if (seconds == null) return '';
  if (seconds < 10) return '${seconds.toStringAsFixed(1)} 秒';
  return jobDuration(Duration(milliseconds: (seconds * 1000).round()));
}

/// 卡片上只看尾巴（[lines] 行），完整输出点“完整输出”。
String shellTail(String output, int lines) => jobTailLines(output, lines);

/// 输出比卡片上显示的多：给“完整输出”入口。
bool shellHasMore(String output, int lines) => output.trimRight().split('\n').length > lines;

String shellSemantics(ShellBlock b) {
  final d = shellDuration(b.seconds);
  return '你运行的命令 ${b.command}，${shellStateLabel(b)}${d.isEmpty ? '' : '，用时 $d'}${b.note == null ? '' : '：${b.note}'}';
}
