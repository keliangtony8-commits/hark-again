// 聊天页（一级）：浮动顶栏下一行居中小标题（点开看本对话用量）+ 聊天区；新对话在左侧历史按钮打开的面板里。
// 历史栏手机在抽屉、平板常驻左侧，都交给 ChatScaffold。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/tokens.dart';
import '../../shell/launch_composer.dart';
import 'chat_controller.dart';
import 'chat_scaffold.dart';


class ChatScreen extends ConsumerWidget {
  const ChatScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(chatProvider(''));
    final title = chat.conversations.where((c) => c.id == chat.activeId).map((c) => c.title).firstOrNull ?? '新对话';
    return ChatScaffold(
      title: AnimatedSwitcher(duration: Motion.base, child: Text(title, key: ValueKey(title), maxLines: 1, overflow: TextOverflow.ellipsis)),
      suggestions: starterPrompts,
    );
  }
}
