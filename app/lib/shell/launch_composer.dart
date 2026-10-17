// 一级页面（主页、项目）底部的输入胶囊：和聊天页同一个 Composer、同一个位置，所以看起来是“全局的那一个输入框”。
// 在这里发出 = 开一段新对话、切到聊天（askInNewChat）；它不持有对话状态——编辑、停止、选模型、发件箱
// 都属于某段对话，只在 ChatView 里那一个 Composer 上，避免两处状态打架（见 docs/design-v2.md P2）。
// 聚焦时（“发起”态）：整页磨砂变暗（FrostScrim）、胶囊左边出现“收起”钮、上方升起建议问题；点遮罩/收起/返回键都会收起。
// v3.5.1 模式（LaunchMode，照 Hark）：外面把 mode 设成一种模式 = 进入发起态并聚焦，上方换成这个模式的小字 + 胶囊、
//   占位词轮播、发出前包一层（主页 + 新建面板 = features/home/new_panel.dart newPanelMode）；收起即清回 null。
//   网页版 shell/LaunchComposer.tsx 同一套。
// 聊天页本身不做磨砂：回复时要看得见上面的消息。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/chat/composer.dart';
import '../features/chat/open_conversation.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';

/// 新对话的建议问题：聊天页空状态和一级页面的输入胶囊共用。
const starterPrompts = ['帮我规划这周的学习', '查一下今天的新闻', '把这段话翻译成英文', '每天早上 8 点给我简报'];

/// 模式里的胶囊能做的两件事（都会先收起输入框）：ask = 把一句话（包过 wrap）发进新对话；
/// then = 收起后在页面的 context 上做别的（打开表单、放回面板）。
class LaunchActions {
  const LaunchActions({required this.ask, required this.then});
  final void Function(String text) ask;
  final void Function(Future<void> Function(BuildContext context, WidgetRef ref) action) then;
}

/// 发起态的一种模式（= 网页 LaunchMode）。
class LaunchMode {
  const LaunchMode({required this.caption, required this.hints, this.hintIcons, required this.wrap, required this.extras});

  /// 输入框正上方的一行淡色小字（“创建一个新面板”）。
  final String caption;

  /// 输入框占位词轮播。
  final List<String> hints;

  /// 占位词前的图标（和 hints 一一对应，Hark 样式）；模式里不出“添加附件”，图标占那一位。
  final List<IconData>? hintIcons;

  /// 发出前把输入包一层（newPanelPrompt）。
  final String Function(String text) wrap;

  /// 建议问题那一格换成的内容（胶囊们）。
  final Widget Function(BuildContext context, LaunchActions go) extras;
}

class LaunchComposer extends ConsumerStatefulWidget {
  const LaunchComposer({super.key, required this.child, this.suggestions = starterPrompts, this.mode});
  final Widget child;
  final List<String> suggestions;

  /// 外面设一种模式 = 进入发起态（聚焦、键盘弹出）；收起时这里清回 null。
  final ValueNotifier<LaunchMode?>? mode;

  @override
  ConsumerState<LaunchComposer> createState() => _LaunchComposerState();
}

class _LaunchComposerState extends ConsumerState<LaunchComposer> {
  final _focus = FocusNode();
  bool _focused = false;

  @override
  void initState() {
    super.initState();
    _focus.addListener(_onFocus);
    widget.mode?.addListener(_onMode);
  }

  @override
  void didUpdateWidget(LaunchComposer old) {
    super.didUpdateWidget(old);
    if (old.mode != widget.mode) {
      old.mode?.removeListener(_onMode);
      widget.mode?.addListener(_onMode);
    }
  }

  @override
  void dispose() {
    widget.mode?.removeListener(_onMode);
    _focus.dispose();
    super.dispose();
  }

  void _onFocus() {
    if (_focus.hasFocus == _focused) return;
    setState(() => _focused = _focus.hasFocus);
    if (!_focused) widget.mode?.value = null; // 收起 = 回到普通发起态
  }

  void _onMode() {
    if (!mounted) return;
    setState(() {});
    if (widget.mode?.value != null) _focus.requestFocus();
  }

  void _collapse() => _focus.unfocus();

  LaunchMode? get _mode => _focused ? widget.mode?.value : null;

  void _ask(String text, [List<FileBlock> files = const []]) {
    final wrapped = _mode?.wrap(text) ?? text;
    _collapse();
    askInNewChat(context, ref, wrapped, files: files);
  }

  void _then(Future<void> Function(BuildContext context, WidgetRef ref) action) {
    _collapse();
    action(context, ref);
  }

  @override
  Widget build(BuildContext context) {
    final mode = _mode;
    return PopScope(
      canPop: !_focused, // 安卓返回键先收起输入框
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _collapse();
      },
      child: FloatingFooter(
        behind: FrostScrim(visible: _focused, onTap: _collapse),
        footer: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          RiseSwitcher(
            child: mode != null
                ? _ModeAbove(key: ValueKey(mode), mode: mode, go: LaunchActions(ask: (t) => _ask(t), then: _then))
                : _focused && widget.suggestions.isNotEmpty
                    ? _Suggestions(key: const ValueKey('s'), items: widget.suggestions, onPick: _ask)
                    : null,
          ),
          Composer(
            busy: false,
            focusNode: _focus,
            hints: mode?.hints,
            hintIcons: mode?.hintIcons,
            attach: mode == null,
            leading: _focused ? GlassIconButton(icon: Icons.keyboard_arrow_down_rounded, tooltip: '收起', onTap: _collapse) : null,
            onSend: _ask,
          ),
        ]),
        child: widget.child,
      ),
    );
  }
}

/// 模式的上方：胶囊们 + 紧贴输入框的一行淡色小字。
class _ModeAbove extends StatelessWidget {
  const _ModeAbove({super.key, required this.mode, required this.go});
  final LaunchMode mode;
  final LaunchActions go;

  @override
  Widget build(BuildContext context) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        mode.extras(context, go),
        // Hark：居中、常规字重、比占位词小一档的淡色字，离胶囊顶约 24（这里 Sp.x4 + Composer 自己的上边距 Sp.x2）
        Padding(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, Sp.x4, Layout.gutter, Sp.x4),
          child: FadeSlideIn(
            child: Text(mode.caption,
                textAlign: TextAlign.center, style: context.text.bodyMedium?.copyWith(color: context.palette.text3), maxLines: 1),
          ),
        ),
      ]);
}

/// 一行横向可滑的玻璃胶囊（建议问题、新建面板模式的示例 / 最近移除共用）。
class LaunchChipRow extends StatelessWidget {
  const LaunchChipRow({super.key, required this.children, this.from = 0});
  final List<Widget> children;

  /// 错峰入场从第几拍开始（多行时下一行接着上一行）。
  final int from;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x2, Sp.x3, 0),
        child: Row(children: [
          for (var i = 0; i < children.length; i++)
            Padding(
              padding: EdgeInsets.only(right: i == children.length - 1 ? 0 : Sp.x2),
              child: FadeSlideIn(delay: Motion.stagger(i, from: from), child: children[i]),
            ),
        ]),
      );
}

class _Suggestions extends StatelessWidget {
  const _Suggestions({super.key, required this.items, required this.onPick});
  final List<String> items;
  final void Function(String) onPick;

  @override
  Widget build(BuildContext context) => LaunchChipRow(children: [for (final s in items) GlassChip(label: s, onTap: () => onPick(s))]);
}
