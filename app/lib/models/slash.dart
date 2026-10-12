// 输入框里的 `/命令`（学 Codex / Gemini CLI 的斜杠命令）。纯规则：认不认、候选、提示文案。
// 目前一条：`/init` —— 让助手看一遍工作区写 AGENTS.md（服务器 app/init_command.py 是唯一规则：
// 存库的仍是 “/init”，给模型时才换成提示词；工作区根目录已有非空 AGENTS.md 就不调模型、直接回一句）。
// 只在整条消息开头打 `/` 时弹候选（`a/b` 路径、句中的 / 都不弹）。网页版 frontend/src/lib/slash.ts 同一套规则。
import 'package:flutter/material.dart';

class SlashCommand {
  const SlashCommand(this.name, this.title, this.hint, this.icon);
  final String name, title, hint;
  final IconData icon;
  String get token => '/$name';
}

const initCommand = SlashCommand('init', '生成 AGENTS.md', '先看一遍工作区，写一份项目说明和规矩，以后每轮都照着做', Icons.auto_stories_rounded);

const slashCommands = [initCommand];

/// 光标前正在打的 `/xxx`：整段文字（到光标）只有 `/` 加字母，返回 xxx；否则 null。
String? slashQueryAt(String text, int caret) {
  if (caret < 1 || caret > text.length || text.length != text.trimLeft().length) return null;
  final head = text.substring(0, caret);
  if (!head.startsWith('/') || text.substring(caret).trim().isNotEmpty) return null;
  final q = head.substring(1);
  return RegExp(r'^[A-Za-z]*$').hasMatch(q) ? q.toLowerCase() : null;
}

/// 候选：名字开头对得上的。
List<SlashCommand> rankSlash(String query) => [for (final c in slashCommands) if (c.name.startsWith(query)) c];

/// 点了候选：整段换成 `/init `，光标放最后（后面可接补充要求）。
(String, int) applySlash(SlashCommand c) => ('${c.token} ', c.token.length + 1);

/// 整条消息是不是 `/init`（可带补充要求；大小写不敏感；`/initial` 不算）——和服务器 init_command.parse 一致。
/// 是 → 补充要求（没有就是 ''）；不是 → null。
String? initNoteOf(String text) {
  final t = text.trim();
  final n = initCommand.token.length;
  if (t.length < n || t.substring(0, n).toLowerCase() != initCommand.token) return null;
  if (t.length > n && t[n].trim().isNotEmpty) return null;
  return t.substring(n).trim();
}

/// 输入框上方的提示：要不要带补充要求的写法。
String initBarText(String note) => note.isEmpty ? '${initCommand.title} · ${initCommand.hint}' : '${initCommand.title} · 补充：$note';
