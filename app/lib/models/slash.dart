// 输入框里的 `/命令`（学 Codex tui/slash_command.rs + Gemini CLI 的斜杠命令）。纯规则：认不认、候选、提示文案。
// 两类（v1.87 起）：
//   · 服务器命令：/init —— 原文照发，服务器 app/init_command.py 是唯一规则（存库的仍是 “/init”，给模型时才换成提示词；
//     工作区根目录已有非空 AGENTS.md 就不调模型、直接回一句）。
//   · 本机命令（local）：/new /compact /plan /copy /status /model /diff —— 不发消息、不花 token，由 features/chat/slash_actions.dart
//     调已有的接口 / 界面（新对话、整理上文、计划模式开关、复制上一条回答、本对话用量、换模型、跳到最近的改动卡）。
//     /model /diff 是 v1.89 加的（Codex 的 /model 不在生成中用、接名字直接换；/diff 看工作区改动 → 我们已有逐轮改动卡，跳过去）。
// 照 Codex 的三条性质：available_during_task（duringTask：生成中能不能用；不能 → 提示条说“回答结束后再用”、发送钮灰掉）、
// supports_inline_args（args：能不能在后面接话；不接受的命令后面带了字 → 当普通文字发给助手）、点候选时不带参数的命令直接执行。
// 只在整条消息开头打 `/` 时弹候选（`a/b` 路径、句中的 / 都不弹）。网页版 frontend/src/lib/slash.ts 同一套规则。
import 'package:flutter/material.dart';

class SlashCommand {
  const SlashCommand(this.name, this.title, this.hint, this.icon, {this.local = false, this.duringTask = true, this.args = false});
  final String name, title, hint;
  final IconData icon;

  /// 本机执行（不发消息）。
  final bool local;

  /// 生成中也能用。
  final bool duringTask;

  /// 后面能接一段话（/init 的补充要求、/plan 后面要发的消息）。
  final bool args;
  String get token => '/$name';
}

const initCommand = SlashCommand('init', '生成 AGENTS.md', '先看一遍工作区，写一份项目说明和规矩，以后每轮都照着做', Icons.auto_stories_rounded, args: true);
const newCommand = SlashCommand('new', '新对话', '另起一段对话，这段留在历史里', Icons.add_comment_outlined, local: true, duringTask: false);
const compactCommand =
    SlashCommand('compact', '整理上文', '把较早的消息压成摘要，之后每轮更省 token', Icons.compress_rounded, local: true, duringTask: false);
const planCommand = SlashCommand('plan', '计划模式', '开 / 关：只看不改，先出方案你批准；后面接话 = 打开并发出去', Icons.map_outlined,
    local: true, duringTask: false, args: true);
const copyCommand = SlashCommand('copy', '复制上一条回答', '把助手最近一条回答复制到剪贴板', Icons.content_copy_rounded, local: true);
const statusCommand = SlashCommand('status', '本对话用量', '看用了多少 token、上文记忆和这段对话的文件', Icons.insights_rounded, local: true);

const modelCommand = SlashCommand('model', '换模型', '不接话 = 打开模型列表；接名字（如 /model 深度）= 直接换，下一轮起用', Icons.tune_rounded,
    local: true, duringTask: false, args: true);
const diffCommand = SlashCommand('diff', '最近改动', '跳到最近一张改动卡：看 diff、整轮撤销', Icons.difference_outlined, local: true);

const slashCommands = [initCommand, newCommand, compactCommand, planCommand, modelCommand, diffCommand, copyCommand, statusCommand];

/// 认出来的一条命令 + 后面接的话（没有就是 ''）。
class SlashCall {
  const SlashCall(this.command, this.args);
  final SlashCommand command;
  final String args;
  bool get local => command.local;

  @override
  bool operator ==(Object other) => other is SlashCall && other.command.name == command.name && other.args == args;
  @override
  int get hashCode => Object.hash(command.name, args);
}

/// 光标前正在打的 `/xxx`：整段文字（到光标）只有 `/` 加字母，返回 xxx；否则 null。
String? slashQueryAt(String text, int caret) {
  if (caret < 1 || caret > text.length || text.length != text.trimLeft().length) return null;
  final head = text.substring(0, caret);
  if (!head.startsWith('/') || text.substring(caret).trim().isNotEmpty) return null;
  final q = head.substring(1);
  return RegExp(r'^[A-Za-z]*$').hasMatch(q) ? q.toLowerCase() : null;
}

/// 候选：名字开头对得上的。local = false（这个输入框不接本机命令，如没有 onSlash）→ 只列服务器命令。
List<SlashCommand> rankSlash(String query, {bool local = true}) =>
    [for (final c in slashCommands) if (c.name.startsWith(query) && (local || !c.local)) c];

/// 点了候选：整段换成 `/init `，光标放最后（后面可接补充要求）。
(String, int) applySlash(SlashCommand c) => ('${c.token} ', c.token.length + 1);

/// 整条消息是不是一条命令（大小写不敏感；名字后面必须是空白或结尾，`/initial` 不算；不接话的命令后面带了字 → 不算）。
SlashCall? slashOf(String text, {bool local = true}) {
  final t = text.trim();
  final m = RegExp(r'^/([A-Za-z]+)(?:\s+([\s\S]*))?$').firstMatch(t);
  if (m == null) return null;
  final name = m.group(1)!.toLowerCase();
  final args = (m.group(2) ?? '').trim();
  for (final c in slashCommands) {
    if (c.name != name || (c.local && !local)) continue;
    return args.isNotEmpty && !c.args ? null : SlashCall(c, args);
  }
  return null;
}

/// 整条消息是不是 `/init`（可带补充要求）——和服务器 init_command.parse 一致。是 → 补充要求（没有就是 ''）；不是 → null。
String? initNoteOf(String text) {
  final c = slashOf(text, local: false);
  return c?.command == initCommand ? c!.args : null;
}

/// 输入框上方的提示：要不要带补充要求的写法。
String initBarText(String note) => note.isEmpty ? '${initCommand.title} · ${initCommand.hint}' : '${initCommand.title} · 补充：$note';

/// 现在不能用（生成中且这条命令只能在空闲时用）。
bool slashBlocked(SlashCall c, {required bool busy}) => busy && !c.command.duringTask;

/// 输入框上方的提示条文案。
String slashBarText(SlashCall c, {bool busy = false}) {
  final t = c.command.title;
  if (slashBlocked(c, busy: busy)) return '$t · 回答结束后再用';
  if (c.command == initCommand) return initBarText(c.args);
  if (c.command == planCommand && c.args.isNotEmpty) return '$t · 打开并发出去';
  if (c.command == modelCommand && c.args.isNotEmpty) return '$t · 换成「${c.args}」';
  return '$t · ${c.command.hint}';
}

/// 候选列表第二行：生成中不能用的标出来。
String slashSubtitle(SlashCommand c, {bool busy = false}) => busy && !c.duringTask ? '${c.title} · 回答结束后再用' : c.title;
