// 方案卡（v1.71 计划模式，后端 app/plan_mode.py）的显示规则：标签、正文、要不要折叠、读屏文字。界面只读这里。
import '../core/workspace.dart';
import 'block.dart';

/// 正文超过这么多行 / 字就先只露一截，点“展开全部”看完。
const planReviewLongLines = 14;
const planReviewLongChars = 700;

String planReviewLabel(PlanReviewBlock b) => switch (b.state) {
      'approved' => '已批准',
      'rejected' => '要改',
      'expired' => '已过期',
      _ => '等你批准',
    };

/// 卡头小字：等批准时告诉用户点了会怎样；其余状态说结果。
String planReviewHint(PlanReviewBlock b) => switch (b.state) {
      'approved' => '已退出计划模式，按这个方案做',
      'rejected' => '仍在计划模式，在输入框里说要改哪里',
      'expired' => '这一轮停了，没等到你的答复',
      _ => '计划模式 · 批准后它才开始动手',
    };

/// 卡头已经显示标题：正文去掉开头那行 “# 标题”（与标题相同时），免得重复。
String planReviewBody(PlanReviewBlock b) {
  final lines = b.plan.trim().split('\n');
  if (lines.isNotEmpty && RegExp(r'^#\s+').hasMatch(lines.first) && lines.first.replaceFirst(RegExp(r'^#\s+'), '').trim() == b.title.trim()) {
    return lines.skip(1).join('\n').trim();
  }
  return b.plan.trim();
}

bool planReviewLong(PlanReviewBlock b) {
  final body = planReviewBody(b);
  return body.split('\n').length > planReviewLongLines || body.length > planReviewLongChars;
}

/// 已经有结果的方案卡默认收成一行（点卡头展开）；等批准的始终展开。
bool planReviewCollapsedByDefault(PlanReviewBlock b) => !b.pending;

String planReviewSemantics(PlanReviewBlock b) => '方案：${b.title}，${planReviewLabel(b)}。${planReviewHint(b)}';


/// 批准后方案存成了工作区文件（v1.72，后端 plan_mode.plan_file）：卡上露一行，点开看 / 下载。老卡、没批准的不显示。
bool planReviewSaved(PlanReviewBlock b) => b.state == 'approved' && b.path.isNotEmpty && b.workspace.isNotEmpty;

/// 那一行的文件名（只显示最后一段，完整路径在读屏文字里）。
String planReviewFileName(PlanReviewBlock b) => b.path.split('/').last;

String planReviewFilePath(PlanReviewBlock b) => workspaceFilePath(b.workspace, b.path);

String planReviewFileSemantics(PlanReviewBlock b) => '方案已存到${workspaceFilesTitle(b.workspace)}：${b.path}，点开查看';
