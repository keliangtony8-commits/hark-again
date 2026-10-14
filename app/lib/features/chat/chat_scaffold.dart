// 聊天页骨架：主聊天和项目聊天共用，一处决定历史栏怎么摆。
//   手机/小平板：历史在抽屉里。主聊天：顶栏左侧“历史”按钮。
//   项目聊天（v2.91 §N）：标题栏左侧 返回 + “≡”；≡ 打开项目对话列表——抽屉在标题栏下面滑出（SubPage 里再套一层 Scaffold，
//   抽屉和遮罩只盖正文），所以同一颗钮在列表打开时旋转成 +（MenuPlusIcon）= 本项目新对话，拇指不用挪位；遮罩 / 返回键收起。
//   列表开着与否只放在 ValueNotifier 里，按钮自己听，不整页 setState；打开列表时刷新一次（状态胶囊以服务器为准）。
//   平板/折叠屏展开（≥ Layout.expandedMin）：历史栏常驻左侧和对话并排；顶栏按钮变成“收起/展开历史”（专注模式，项目页在标题栏右侧）。
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
import 'chat_controller.dart';
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
    this.empty,
  });

  final String projectId;
  final Widget title;
  final List<Widget> actions;
  final List<String> suggestions;

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

  /// 项目抽屉开着（≡ 变 +）。只给左上那颗钮听。
  final _listOpen = ValueNotifier(false);
  final _inner = GlobalKey<ScaffoldState>();

  @override
  void dispose() {
    _listOpen.dispose();
    final cover = _cover;
    if (cover != null && _drawerOpen) Future.microtask(() => cover.set(false)); // 抽屉开着离开才复位；不在拆树途中改状态
    super.dispose();
  }

  bool _paneOpen = true; // 双栏时用户可收起历史栏
  bool? _wasTwoPane;
  bool _animatePane = false;

  bool get _isProject => widget.projectId.isNotEmpty;
  String get _listName => _isProject ? '项目对话' : '历史';

  ChatController get _ctl => ProviderScope.containerOf(context, listen: false).read(chatProvider(widget.projectId).notifier);

  /// 项目左上钮：列表关着 → 打开；开着（显示 +）→ 本项目新对话并收起列表。
  void _menuTap() {
    final inner = _inner.currentState;
    if (inner == null) return;
    if (_listOpen.value) {
      _ctl.open(null);
      inner.closeDrawer();
    } else {
      inner.openDrawer();
    }
  }

  void _onListChanged(bool open) {
    _listOpen.value = open;
    if (open) _ctl.refreshList().catchError((_) {}); // 状态胶囊：挂起的卡片出现在一轮中途，打开时以服务器为准
  }

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

    final drawer = twoPane ? null : HistoryPanel.drawer(context, projectId: widget.projectId);
    if (!_isProject) return _floating(context, twoPane: twoPane, showPane: showPane, drawer: drawer);

    // 项目聊天：子页面外框（玻璃标题栏 + 壁纸）。手机：左上 返回 + ≡/+，抽屉在里层 Scaffold（标题栏下面）；
    // 双栏：历史栏常驻，标题栏右侧是收起/展开。两种都是同一棵树（里层 Scaffold → Row → 带 key 的聊天区），转屏不丢状态。
    final menu = ValueListenableBuilder<bool>(
      valueListenable: _listOpen,
      builder: (_, open, _) => IconButton(
        icon: MenuPlusIcon(plus: open),
        tooltip: open ? '新对话' : _listName,
        onPressed: _menuTap,
      ),
    );
    return SubPage(
      title: ChatTitle(scope: widget.projectId, child: widget.title),
      leading: twoPane ? null : Row(mainAxisSize: MainAxisSize.min, children: [const BackButton(), menu]),
      leadingWidth: twoPane ? null : A11y.minTap * 2 + Sp.x2,
      actions: [
        if (twoPane)
          IconButton(
            icon: Icon(showPane ? Icons.menu_open_rounded : Icons.notes_rounded),
            tooltip: showPane ? '收起$_listName' : '展开$_listName',
            onPressed: _togglePane,
          ),
        ...widget.actions,
      ],
      body: Scaffold(
        key: _inner,
        backgroundColor: Colors.transparent,
        drawer: drawer,
        onDrawerChanged: _onListChanged,
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
      ),
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
              tooltip: showPane ? '收起$_listName' : '展开$_listName',
              onTap: _togglePane,
            )
          : GlassIconButton(icon: Icons.notes_rounded, tooltip: _listName, onTap: () => Scaffold.of(ctx).openDrawer()),
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
