// 一级页面（主页、项目）底部的输入胶囊：和聊天页同一个 Composer、同一个位置，所以看起来是“全局的那一个输入框”。
// 在这里发出 = 开一段新对话、切到聊天（askInNewChat）；它不持有对话状态——编辑、停止、选模型、发件箱
// 都属于某段对话，只在 ChatView 里那一个 Composer 上，避免两处状态打架（见 docs/design-v2.md P2）。
// 聚焦时：整页磨砂变暗（FrostScrim）、胶囊左边出现“收起”钮、上方升起建议问题；点遮罩/收起/返回键都会收起。
// 聊天页本身不做磨砂：回复时要看得见上面的消息。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/chat/composer.dart';
import '../features/chat/open_conversation.dart';
import '../models/block.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';

/// 新对话的建议问题：聊天页空状态和一级页面的输入胶囊共用。
const starterPrompts = ['帮我规划这周的学习', '查一下今天的新闻', '把这段话翻译成英文', '每天早上 8 点给我简报'];

class LaunchComposer extends ConsumerStatefulWidget {
  const LaunchComposer({super.key, required this.child, this.suggestions = starterPrompts});
  final Widget child;
  final List<String> suggestions;

  @override
  ConsumerState<LaunchComposer> createState() => _LaunchComposerState();
}

class _LaunchComposerState extends ConsumerState<LaunchComposer> {
  final _focus = FocusNode();
  bool _focused = false;

  @override
  void initState() {
    super.initState();
    _focus.addListener(() {
      if (_focus.hasFocus != _focused) setState(() => _focused = _focus.hasFocus);
    });
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  void _collapse() => _focus.unfocus();

  void _ask(String text, [List<FileBlock> files = const []]) {
    _collapse();
    askInNewChat(context, ref, text, files: files);
  }

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: !_focused, // 安卓返回键先收起输入框
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) _collapse();
        },
        child: FloatingFooter(
          behind: FrostScrim(visible: _focused, onTap: _collapse),
          footer: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            RiseSwitcher(child: _focused && widget.suggestions.isNotEmpty ? _Suggestions(key: const ValueKey('s'), items: widget.suggestions, onPick: _ask) : null),
            Composer(
              busy: false,
              focusNode: _focus,
              leading: _focused ? GlassIconButton(icon: Icons.keyboard_arrow_down_rounded, tooltip: '收起', onTap: _collapse) : null,
              onSend: _ask,
            ),
          ]),
          child: widget.child,
        ),
      );
}

class _Suggestions extends StatelessWidget {
  const _Suggestions({super.key, required this.items, required this.onPick});
  final List<String> items;
  final void Function(String) onPick;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x2, Sp.x3, 0),
        child: Row(children: [
          for (var i = 0; i < items.length; i++)
            Padding(
              padding: EdgeInsets.only(right: i == items.length - 1 ? 0 : Sp.x2),
              child: FadeSlideIn(delay: Motion.stagger(i), child: GlassChip(label: items[i], onTap: () => onPick(items[i]))),
            ),
        ]),
      );
}
