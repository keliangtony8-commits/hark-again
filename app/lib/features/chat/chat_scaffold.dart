// 聊天页骨架：主聊天和项目聊天共用，一处决定历史栏怎么摆。
//   手机/小平板：历史在抽屉里，顶栏有“历史”按钮（主聊天在左边开，项目页左边是返回键所以在右边开）。
//   平板/折叠屏展开（≥ Layout.expandedMin）：历史栏常驻左侧和对话并排；顶栏按钮变成“收起/展开历史”（专注模式）。
// 标题下挂本对话用量（ChatTitle，点开明细），主聊天和项目聊天一致。
// 主聊天是一级页面（设计 v2）：没有 AppBar，历史按钮是浮动顶栏左侧的玻璃圆钮（ShellPage.lead），
//   标题 + 用量是顶栏下面居中的一行小字；新对话在历史面板顶部（v0.46 起，去掉了第二排的胶囊和按钮）。
//   项目聊天是子页面：SubPage（玻璃标题栏 + 壁纸），历史栏和对话都从标题栏下面滚过。
// 布局切换只增减 Row 前面的侧栏，聊天区始终是同一个带 key 的孩子——转屏时输入框里的字和滚动位置都在。
// 只有用户点收起/展开才有过渡动画；窗口尺寸变化引起的切换直接到位（见 SidePaneSwitcher.animate）。
import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../shell/app_shell.dart' show ShellCover, shellCoverProvider;
import '../../shell/shell_page.dart';
import '../../ui/adaptive.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';
import 'chat_view.dart';
import 'conversation_usage.dart';
import 'history_panel.dart';

class ChatScaffold extends StatefulWidget {
  const ChatScaffold({
    super.key,
    this.projectId = '',
    required this.title,
    this.actions = const [],
    this.suggestions = const [],
    this.historyTooltip = '历史',
    this.empty,
  });

  final String projectId;
  final Widget title;
  final List<Widget> actions;
  final List<String> suggestions;
  final String historyTooltip;

  /// 没有消息时的首屏（见 ChatView.empty）。
  final Widget Function(BuildContext context, void Function(String text) send)? empty;

  @override
  State<ChatScaffold> createState() => _ChatScaffoldState();
}

class _ChatScaffoldState extends State<ChatScaffold> {
  ShellCover? _cover; // 抽屉开着 → 外壳顶栏让位；离开页面时（抽屉可能还开着）复位
  bool _drawerOpen = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _cover = ProviderScope.containerOf(context, listen: false).read(shellCoverProvider.notifier);
  }

  @override
  void dispose() {
    final cover = _cover;
    if (cover != null && _drawerOpen) Future.microtask(() => cover.set(false)); // 抽屉开着离开才复位；不在拆树途中改状态
    super.dispose();
  }

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
    final twoPane = context.window.twoPane;
    if (_wasTwoPane != twoPane) _animatePane = false; // 尺寸变化：直接到位
    _wasTwoPane = twoPane;
    final showPane = twoPane && _paneOpen;

    Widget historyButton(BuildContext ctx) => twoPane
        ? IconButton(
            icon: Icon(showPane ? Icons.menu_open_rounded : Icons.notes_rounded),
            tooltip: showPane ? '收起${widget.historyTooltip}' : '展开${widget.historyTooltip}',
            onPressed: _togglePane,
          )
        : IconButton(
            icon: const Icon(Icons.notes_rounded),
            tooltip: widget.historyTooltip,
            onPressed: () => Scaffold.of(ctx).openEndDrawer(), // 只有项目聊天用这个按钮（主聊天是 ShellPage.lead）
          );
    final drawer = twoPane ? null : HistoryPanel.drawer(context, projectId: widget.projectId);
    if (!_isProject) return _floating(context, twoPane: twoPane, showPane: showPane, drawer: drawer);

    // 项目聊天：子页面外框（玻璃标题栏 + 壁纸），历史按钮在右（左边是返回键），历史栏和对话都在标题栏下面
    return SubPage(
      title: ChatTitle(scope: widget.projectId, child: widget.title),
      actions: [Builder(builder: historyButton), ...widget.actions],
      endDrawer: drawer,
      body: Row(children: [
        SidePaneSwitcher(
          animate: _animatePane,
          child: showPane
              ? SizedBox(
                  key: const ValueKey('pane'),
                  width: Layout.sidePane,
                  child: DecoratedBox(
                    decoration: BoxDecoration(border: Border(right: BorderSide(color: p.glassBorder))),
                    child: HistoryPanel(projectId: widget.projectId, docked: true),
                  ),
                )
              : null,
        ),
        Expanded(key: const ValueKey('chat'), child: ChatView(projectId: widget.projectId, suggestions: widget.suggestions, empty: widget.empty)),
      ]),
    );
  }

  /// 主聊天：外框交给 ShellPage（让出浮动顶栏 + 标题胶囊），整行（历史栏 + 对话）都在它里面，
  /// 所以左侧按钮永远对齐顶栏的空位；常驻历史栏靠 SafeArea 自动落在让位线下面。
  Widget _floating(BuildContext context, {required bool twoPane, required bool showPane, required Widget? drawer}) {
    final p = context.palette;
    final lead = Builder(
      builder: (ctx) => twoPane
          ? GlassIconButton(
              icon: showPane ? Icons.menu_open_rounded : Icons.notes_rounded,
              tooltip: showPane ? '收起${widget.historyTooltip}' : '展开${widget.historyTooltip}',
              onTap: _togglePane,
            )
          : GlassIconButton(icon: Icons.notes_rounded, tooltip: widget.historyTooltip, onTap: () => Scaffold.of(ctx).openDrawer()),
    );
    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      drawer: drawer,
      onDrawerChanged: (open) {
        _drawerOpen = open;
        _cover?.set(open);
      }, // 抽屉开着时浮动顶栏让位
      body: ShellPage(
        lead: lead,
        headerHeight: Layout.chatTitle,
        header: Row(children: [
          AnimatedContainer(
            duration: _animatePane ? context.motion(Motion.slow) : Duration.zero,
            curve: Motion.ease,
            width: showPane ? Layout.sidePane - Sp.x4 : 0,
          ),
          SizedBox(width: Layout.chatTitle * widget.actions.length), // 与右侧动作对称，胶囊居中
          // 标题是顶栏下一行居中的小字（不再是胶囊）：视觉上属于顶栏，不和消息抢层级；点它看本对话用量
          Expanded(
            child: Center(
              child: DefaultTextStyle(
                style: context.text.labelLarge!.copyWith(height: 1.25, color: p.text2),
                child: ChatTitle(scope: widget.projectId, dense: true, child: widget.title),
              ),
            ),
          ),
          ...widget.actions,
        ]),
        child: Row(children: [
          SidePaneSwitcher(
            animate: _animatePane,
            child: showPane
                ? SizedBox(
                    key: const ValueKey('pane'),
                    width: Layout.sidePane,
                    child: DecoratedBox(
                      decoration: BoxDecoration(border: Border(right: BorderSide(color: p.border))),
                      child: HistoryPanel(projectId: widget.projectId, docked: true),
                    ),
                  )
                : null,
          ),
          Expanded(key: const ValueKey('chat'), child: ChatView(projectId: widget.projectId, suggestions: widget.suggestions, empty: widget.empty)),
        ]),
      ),
    );
  }
}
