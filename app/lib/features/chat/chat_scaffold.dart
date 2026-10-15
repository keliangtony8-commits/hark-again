// 聊天页骨架：主聊天和项目聊天共用，一处决定历史栏怎么摆。两者都是一级页面（v2.93 §Q 起项目对话也不再是子页面）：
// 外框都交给 ShellPage——让出浮动顶栏、左上画本页的按钮（lead）、顶栏下一行 header 写标题。
//   主聊天：左上“历史”；抽屉盖全屏，开着时浮动顶栏让位（ShellCover，v2.78）。
//   项目聊天：左上 ≡（打开本项目对话列表）。抽屉放在 ShellPage 里层的 Scaffold：从 header 行下面滑出，
//     左上钮和 header 行画在它上面、顶栏不让位，所以同一颗钮在列表开着时旋转成 +（MenuPlusIcon）= 本项目新对话（v2.91）。
//     左上钮和项目列表的 + 挂同一个 Hero（projectLeadTag）：进出项目时钮停在原地 morph（MenuPlusHero）。
//     header 行 = 左 ‹ 返回项目列表 + 项目名（点开本对话用量）+ 右 ⋯ 项目菜单。
//   列表开着与否只放在 ValueNotifier 里，按钮自己听，不整页 setState；打开列表时刷新一次（状态胶囊以服务器为准）。
//   平板/折叠屏展开（≥ Layout.expandedMin）：历史栏常驻左侧和对话并排；左上钮变成“收起/展开历史”（专注模式），两种聊天一致。
// 标题下挂本对话用量（ChatTitle，点开明细），主聊天和项目聊天一致。
// 布局切换只增减 Row 前面的侧栏，聊天区始终是同一个带 key 的孩子——转屏时输入框里的字和滚动位置都在。
// 只有用户点收起/展开才有过渡动画；窗口尺寸变化引起的切换直接到位（见 SidePaneSwitcher.animate）。
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../shell/app_shell.dart' show ShellCover, shellCoverProvider;
import '../../shell/shell_page.dart';
import '../../ui/adaptive.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import 'chat_controller.dart';
import 'chat_view.dart';
import 'conversation_usage.dart';
import 'history_panel.dart';

/// 项目左上钮的 Hero tag：项目列表的 +（新建项目）和项目页的 ≡（对话列表）是“同一颗钮”。
const projectLeadTag = 'project-lead';

class ChatScaffold extends StatefulWidget {
  const ChatScaffold({
    super.key,
    this.projectId = '',
    required this.title,
    this.back,
    this.actions = const [],
    this.suggestions = const [],
    this.empty,
  });

  final String projectId;
  final Widget title;

  /// header 行最左边的返回键（项目页：返回项目列表）；和右侧 [actions] 对称，标题居中。
  final Widget? back;
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

    final Widget lead;
    if (twoPane) {
      lead = GlassIconButton(
        icon: showPane ? Icons.menu_open_rounded : Icons.notes_rounded,
        tooltip: showPane ? '收起$_listName' : '展开$_listName',
        onTap: _togglePane,
      );
    } else if (_isProject) {
      lead = ValueListenableBuilder<bool>(
        valueListenable: _listOpen,
        builder: (_, open, _) => MenuPlusHero(
          tag: projectLeadTag,
          plus: open,
          frame: (glyph) => GlassIconButton.glyph(glyph: glyph, tooltip: open ? '新对话' : _listName, onTap: _menuTap),
        ),
      );
    } else {
      lead = Builder(builder: (ctx) => GlassIconButton(icon: Icons.notes_rounded, tooltip: _listName, onTap: () => Scaffold.of(ctx).openDrawer()));
    }

    final side = Layout.chatTitle * math.max(widget.actions.length, widget.back == null ? 0 : 1); // 左右同宽，标题居中
    final header = Row(children: [
      SizedBox(width: side, child: Align(alignment: Alignment.centerLeft, child: widget.back)),
      AnimatedContainer(
        duration: _animatePane ? context.motion(Motion.slow) : Duration.zero,
        curve: Motion.ease,
        width: showPane ? Layout.sidePane - Sp.x4 : 0,
      ),
      // 标题是顶栏下一行居中的小字（不是胶囊）：视觉上属于顶栏，不和消息抢层级；点它看本对话用量
      Expanded(
        child: Center(
          child: DefaultTextStyle(
            style: context.text.labelLarge!.copyWith(height: 1.25, color: p.text2),
            child: ChatTitle(scope: widget.projectId, dense: true, child: widget.title),
          ),
        ),
      ),
      SizedBox(width: side, child: Row(mainAxisAlignment: MainAxisAlignment.end, children: widget.actions)),
    ]);

    final body = Row(children: [
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
    ]);

    // 主聊天：抽屉在外层 Scaffold（盖全屏，顶栏让位）；项目：抽屉在 ShellPage 里层（header 行下面，左上钮和 header 在它之上）
    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      drawer: _isProject ? null : drawer,
      onDrawerChanged: _isProject
          ? null
          : (open) {
              _drawerOpen = open;
              _cover?.set(open);
            },
      body: ShellPage(
        lead: lead,
        headerHeight: Layout.chatTitle,
        header: header,
        child: _isProject
            ? Scaffold(key: _inner, backgroundColor: Colors.transparent, drawer: drawer, onDrawerChanged: _onListChanged, body: body)
            : body,
      ),
    );
  }
}
