// 聊天页（一级）：浮动顶栏下一行居中小标题（点开看本对话用量）+ 聊天区；新对话在左侧历史按钮打开的面板里。
// 历史栏手机在抽屉、平板常驻左侧，都交给 ChatScaffold。
// v2.92 §P 首次问候：主聊天空白、服务器说还没问候过（profile.greet）→ 请服务器建「初次见面」对话并打开它，
// 助手的开场白就是那段对话的第一条消息（在聊天里问称呼，不做表单引导页）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/profile.dart';
import '../../theme/tokens.dart';
import '../../shell/launch_composer.dart';
import 'chat_controller.dart';
import 'chat_scaffold.dart';


class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  @override
  void initState() {
    super.initState();
    ref.listenManual(profileProvider.select((p) => p.value?.greet ?? false), (_, greet) {
      if (greet) _greet();
    }, fireImmediately: true);
  }

  Future<void> _greet() async {
    if (ref.read(chatProvider('')).activeId != null || ref.read(chatProvider('')).messages.isNotEmpty) return;
    final id = await ref.read(profileProvider.notifier).greet();
    if (id == null || !mounted) return;
    final ctl = ref.read(chatProvider('').notifier);
    await ctl.refreshList();
    if (mounted && ref.read(chatProvider('')).activeId == null) await ctl.open(id);
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider(''));
    final title = chat.conversations.where((c) => c.id == chat.activeId).map((c) => c.title).firstOrNull ?? '新对话';
    return ChatScaffold(
      title: AnimatedSwitcher(duration: Motion.base, child: Text(title, key: ValueKey(title), maxLines: 1, overflow: TextOverflow.ellipsis)),
      suggestions: starterPrompts,
    );
  }
}
