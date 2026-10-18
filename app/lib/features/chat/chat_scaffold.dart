// 聊天页骨架：主聊天和项目聊天共用，一处决定侧栏怎么摆。两者都是一级页面：
// 外框都交给 ShellPage——让出浮动顶栏、左上画本页的按钮（lead）、顶栏下一行 header 写标题（全 App 唯一的标题位）。
// v3.5.2 照 Hark：左上 ☰ 不再开抽屉 / 弹层，而是回到本标签的“目录”页（同一分支内导航，系统返回键同样回来）：
//   主聊天：☰ → /chat/history（对话目录，HistoryPage）；header = 对话标题（ChatTitle，点开本对话用量）。
//   项目聊天（v2.95 项目 = 一段对话）：☰ → 回项目目录（/projects）；header = 项目名小字（ProjectTitle，点开项目菜单）。
//   ☰ 和目录页左上的 + 挂同一个 Hero（chatLeadTag / projectLeadTag）：进出目录时钮停在原地 morph（MenuPlusHero）。
//   平板/折叠屏展开（≥ Layout.expandedMin）：主聊天的历史栏常驻左侧和对话并排，左上钮变成“收起/展开”（专注模式）；项目没有侧栏。
// 布局切换只增减 Row 前面的侧栏，聊天区始终是同一个带 key 的孩子——转屏时输入框里的字和滚动位置都在。
// 只有用户点收起/展开才有过渡动画；窗口尺寸变化引起的切换直接到位（见 SidePaneSwitcher.animate）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../shell/shell_page.dart';
import '../../ui/adaptive.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import 'chat_view.dart';
import 'conversation_usage.dart';
import 'history_panel.dart';

/// 项目左上钮的 Hero tag：项目目录的 +（新建项目）和项目页的 ☰（回目录）是“同一颗钮”。
const projectLeadTag = 'project-lead';

/// 主聊天左上钮的 Hero tag：聊天的 ☰（对话目录）和对话目录页的 +（新对话）是“同一颗钮”。
const chatLeadTag = 'chat-lead';

/// 回到本标签的目录：栈里有就退一页（和系统返回键同一条路），没有（深链直接进来）就去目录。
void backToDirectory(BuildContext context, String directory) {
  if (context.canPop()) {
    context.pop();
  } else {
    context.go(directory);
  }
}

class ChatScaffold extends ConsumerStatefulWidget {
  const ChatScaffold({
    super.key,
    this.projectId = '',
    required this.title,
    this.suggestions = const [],
  });

  final String projectId;

  /// header 行居中的那一个：主聊天 = 对话标题（外面包 ChatTitle），项目 = ProjectTitle。
  final Widget title;
  final List<String> suggestions;

  @override
  ConsumerState<ChatScaffold> createState() => _ChatScaffoldState();
}

class _ChatScaffoldState extends ConsumerState<ChatScaffold> {
  bool _paneOpen = true; // 双栏时用户可收起历史栏
  bool? _wasTwoPane;
  bool _animatePane = false;

  bool get _isProject => widget.projectId.isNotEmpty;

  void _togglePane() => setState(() {
        _paneOpen = !_paneOpen;
        _animatePane = true;
      });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final twoPane = context.window.twoPane && !_isProject;
    if (_wasTwoPane != twoPane) _animatePane = false; // 尺寸变化：直接到位
    _wasTwoPane = twoPane;
    final showPane = twoPane && _paneOpen;

    final Widget lead;
    if (twoPane) {
      lead = GlassIconButton(
        icon: showPane ? Icons.menu_open_rounded : Icons.notes_rounded,
        tooltip: showPane ? '收起历史' : '展开历史',
        onTap: _togglePane,
      );
    } else if (_isProject) {
      lead = MenuPlusHero(
        tag: projectLeadTag,
        plus: false,
        frame: (glyph) => GlassIconButton.glyph(glyph: glyph, tooltip: '项目', onTap: () => backToDirectory(context, '/projects')),
      );
    } else {
      lead = MenuPlusHero(
        tag: chatLeadTag,
        plus: false,
        frame: (glyph) => GlassIconButton.glyph(glyph: glyph, tooltip: '历史', onTap: () => context.push('/chat/history')),
      );
    }

    final header = Row(children: [
      AnimatedContainer(
        duration: _animatePane ? context.motion(Motion.slow) : Duration.zero,
        curve: Motion.ease,
        width: showPane ? Layout.sidePane - Sp.x4 : 0,
      ),
      // 顶栏下一行居中的小字（不是胶囊）：视觉上属于顶栏，不和消息抢层级。主聊天点它看本对话用量；项目点它开项目菜单（ProjectTitle 自带）。
      Expanded(
        child: Center(
          child: DefaultTextStyle(
            style: context.text.labelLarge!.copyWith(height: 1.25, color: p.text2),
            child: _isProject ? widget.title : ChatTitle(scope: widget.projectId, dense: true, child: widget.title),
          ),
        ),
      ),
    ]);

    final chat = ChatView(projectId: widget.projectId, suggestions: widget.suggestions);
    final body = Row(children: [
      SidePaneSwitcher(
        animate: _animatePane,
        child: showPane
            ? SizedBox(
                key: const ValueKey('pane'),
                width: Layout.sidePane,
                child: DecoratedBox(
                  decoration: BoxDecoration(border: Border(right: BorderSide(color: p.border))),
                  child: const HistoryPanel(docked: true),
                ),
              )
            : null,
      ),
      // 主聊天：进对话目录时聊天区淡出、☰ 留在原地 morph 成 +（同项目目录 → 项目）
      Expanded(key: const ValueKey('chat'), child: _isProject ? chat : FadeUnderCover(child: chat)),
    ]);

    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      body: ShellPage(lead: lead, headerHeight: Layout.chatTitle, header: header, child: body),
    );
  }
}
