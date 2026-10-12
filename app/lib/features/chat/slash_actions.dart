// 本机斜杠命令的执行（v1.87，规则在 models/slash.dart）：不发消息、不花 token，全部复用已有入口——
//   /new → ChatController.open(null)（和历史面板“新对话”同一条路）
//   /compact → POST /api/conversations/{id}/compact（和对话记忆卡“整理上文”同一个接口，提示条同一句 compactToast）
//   /plan → ChatController.setPlanMode（和模式钮同一条 dirty/PATCH 路；接了话 = 打开后把这段话发出去）
//   /copy → 最近一条助手回答的 copyText（和长按回复“复制”同一套规则）
//   /status → showConversationUsage（标题弹出的本对话用量页）
//   /model → 不接话：showModelSheet（模型钮同一个弹层）；接名字：ModelCatalog.find 认出来就 setModel（同一条 dirty/PATCH 路）
//   /diff → latestChanges 找最近一张改动卡 → ChatController.seek（搜索定位同一条路：滚过去 + 闪一下）
// 没有对话时 /compact /status 只给一句提示。ChatView 把它接到 Composer.onSlash。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../models/block.dart';
import '../../models/changes.dart';
import '../../models/conversation_context.dart';
import '../../models/message.dart';
import '../../models/slash.dart';
import '../../ui/kit.dart';
import 'chat_controller.dart';
import 'conversation_memory.dart';
import 'conversation_usage.dart';
import 'model_choice.dart';

/// 还没开始对话时 /compact /status 的提示。
const noConversationToast = '还没开始对话';

/// /copy 要复制的文字：最近一条有内容的助手回答（没有 → null）。
String? lastReplyText(List<Message> messages) {
  for (final m in messages.reversed) {
    if (m.isUser) continue;
    final t = copyText(m.blocks).trim();
    if (t.isNotEmpty) return t;
  }
  return null;
}

Future<void> runSlash(BuildContext context, WidgetRef ref, String scope, SlashCall call, List<FileBlock> files) async {
  final ctl = ref.read(chatProvider(scope).notifier);
  final chat = ref.read(chatProvider(scope));
  final id = chat.activeId;
  switch (call.command.name) {
    case 'new':
      await ctl.open(null);
    case 'plan':
      final on = call.args.isNotEmpty || files.isNotEmpty ? true : !chat.planMode;
      final changed = on != chat.planMode;
      await ctl.setPlanMode(on);
      if (call.args.isNotEmpty || files.isNotEmpty) {
        ctl.send(call.args, files: files);
      } else if (changed && context.mounted) {
        showToast(context, planModeToast(on));
      }
    case 'copy':
      final t = lastReplyText(chat.messages);
      if (t != null) await Clipboard.setData(ClipboardData(text: t));
      if (context.mounted) showToast(context, t == null ? '还没有可复制的回答' : '已复制上一条回答');
    case 'status':
      if (id == null) return showToast(context, noConversationToast);
      await showConversationUsage(context, id);
    case 'model':
      final cat = ref.read(modelCatalogProvider).value;
      if (cat == null || !cat.selectable) return showToast(context, '服务器只配了一个模型');
      final current = cat.effective(chat.model)!.id;
      final picked = call.args.isEmpty ? await showModelSheet(context, cat, current) : cat.find(call.args);
      if (picked == null) {
        if (call.args.isNotEmpty && context.mounted) showToast(context, cat.findMiss(call.args));
        return;
      }
      if (picked != current) await ctl.setModel(cat.toChoice(picked));
      if (context.mounted) showToast(context, modelToast(cat, picked));
    case 'diff':
      final hit = latestChanges(chat.messages);
      if (hit == null) return showToast(context, noChangesToast);
      ctl.seek(hit.$1);
      showToast(context, latestChangesToast(hit.$2));
    case 'compact':
      if (id == null) return showToast(context, noConversationToast);
      final text = await _compact(ref, id);
      ref.invalidate(conversationContextProvider(id));
      if (context.mounted) showToast(context, text);
  }
}

Future<String> _compact(WidgetRef ref, String id) async {
  final api = ref.read(apiProvider);
  try {
    final before = ConversationContext.fromJson((await api.get('/api/conversations/$id/context') as Map).cast<String, dynamic>());
    final r = CompactResult.fromJson((await api.post('/api/conversations/$id/compact') as Map).cast<String, dynamic>());
    return compactToast(before, r);
  } on ApiError catch (e) {
    return e.message;
  } catch (_) {
    return '整理失败，稍后再试';
  }
}
