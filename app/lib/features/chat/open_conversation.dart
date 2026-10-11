// 从别的页面跳进某个对话的唯一入口（收件箱报告、用量页的“最花钱的对话”…）：
// 先切到 Chat 标签，再让主聊天控制器打开它。以后要改跳转方式（比如平板分栏）只改这里。
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../models/block.dart';
import 'chat_controller.dart';

/// [send]：打开后再发一句（主页建议卡“开始做”：服务端刚开的空对话 + 卡上的指令）。
Future<void> openConversation(BuildContext context, WidgetRef ref, String id, {String? focus, String? send}) async {
  final chat = ref.read(chatProvider('').notifier);
  context.go('/chat');
  await chat.open(id, focus: focus);
  if (send != null && send.trim().isNotEmpty) chat.send(send);
}

/// 从别的页面“问一句”：开一段新对话发出去，然后切到聊天（主页/项目的输入胶囊、新建面板都走这里）。
void askInNewChat(BuildContext context, WidgetRef ref, String text, {List<FileBlock> files = const []}) {
  if (text.trim().isEmpty && files.isEmpty) return;
  final ctl = ref.read(chatProvider('').notifier);
  ctl.open(null).then((_) => ctl.send(text, files: files));
  context.go('/chat');
}
