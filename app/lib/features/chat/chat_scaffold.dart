// 聊天页骨架：主聊天和项目聊天共用，一处决定侧栏怎么摆。两者都是一级页面：
// 外框都交给 ShellPage——让出浮动顶栏、左上画本页的按钮（lead）、顶栏下一行 header 写标题（全 App 唯一的标题位）。
//   主聊天：左上“历史”；抽屉盖全屏，开着时浮动顶栏让位（ShellCover，v2.78）；header = 对话标题（ChatTitle，点开本对话用量）。
//   项目聊天（v2.95 项目 = 一段对话）：header = 项目名药丸（ProjectPill，点开项目菜单），下面就是这段对话。
//     左上 ≡ 打开项目切换栏（ProjectSwitcher）。抽屉放在 ShellPage 里层的 Scaffold：从 header 行下面滑出，
//     左上钮和 header 行画在它上面、顶栏不让位，所以同一颗钮在抽屉开着时旋转成 +（MenuPlusIcon）= 新建项目。
//     左上钮和项目列表的 + 挂同一个 Hero（projectLeadTag）：进出项目时钮停在原地 morph（MenuPlusHero）。
//   抽屉开着与否只放在 ValueNotifier 里，按钮自己听，不整页 setState；打开时刷新一次项目列表（状态胶囊以服务器为准）。
//   平板/折叠屏展开（≥ Layout.expandedMin）：侧栏常驻左侧和对话并排；左上钮变成“收起/展开”（专注模式），两种聊天一致。
// 布局切换只增减 Row 前面的侧栏，聊天区始终是同一个带 key 的孩子——转屏时输入框里的字和滚动位置都在。
// 只有用户点收起/展开才有过渡动画；窗口尺寸变化引起的切换直接到位（见 SidePaneSwitcher.animate）。
import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../shell/app_shell.dart' show ShellCover, shellCoverProvider;
import '../../shell/shell_page.dart';
import '../../ui/adaptive.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../projects/project_switcher.dart';
import '../projects/projects_screen.dart' show createProject;
import 'chat_view.dart';
import 'conversation_usage.dart';
import 'history_panel.dart';

/// 项目左上钮的 Hero tag：项目列表的 +（新建项目）和项目页的 ≡（项目切换）是“同一颗钮”。
const projectLeadTag = 'project-lead';

class ChatScaffold extends ConsumerStatefulWidget {
  const ChatScaffold({
    super.key,
    this.projectId = '',
    required this.title,
    this.suggestions = const [],
  });

  final String projectId;

  /// header 行居中的那一个：主聊天 = 对话标题（外面包 ChatTitle），项目 = ProjectPill（原样画）。
  final Widget title;
  final List<String> suggestions;

  @override
  ConsumerState<ChatScaffold> createState() => _ChatScaffoldState();
}

class _ChatScaffoldState extends ConsumerState<ChatScaffold> {
  ShellCover? _cover; // 抽屉开着 → 外壳顶栏让位；离开页面时（抽屉可能还开着）复位
  bool _drawerOpen = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _cover = ProviderScope.containerOf(context, listen: false).read(shellCoverProvider.notifier);
  }

  /// 项目切换抽屉开着（≡ 变 +）。只给左上那颗钮听。
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
  String get _listName => _isProject ? '项目' : '历史';

  /// 项目左上钮：抽屉关着 → 打开；开着（显示 +）→ 收起抽屉并新建项目。
  void _menuTap() {
    final inner = _inner.currentState;
    if (inner == null) return;
    if (_listOpen.value) {
      inner.closeDrawer();
      createProject(context, ref);
    } else {
      inner.openDrawer();
    }
  }

  void _onListChanged(bool open) {
    _listOpen.value = open;
    // 状态胶囊：挂起的卡片出现在一轮中途，打开时以服务器为准
    if (open) ref.read(projectsProvider.notifier).reload().catchError((_) {});
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
    final drawer = twoPane ? null : (_isProject ? ProjectSwitcher.drawer(context, widget.projectId) : HistoryPanel.drawer(context));

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
          frame: (glyph) => GlassIconButton.glyph(glyph: glyph, tooltip: open ? '新项目' : _listName, onTap: _menuTap),
        ),
      );
    } else {
      lead = Builder(builder: (ctx) => GlassIconButton(icon: Icons.notes_rounded, tooltip: _listName, onTap: () => Scaffold.of(ctx).openDrawer()));
    }

    final header = Row(children: [
      AnimatedContainer(
        duration: _animatePane ? context.motion(Motion.slow) : Duration.zero,
        curve: Motion.ease,
        width: showPane ? Layout.sidePane - Sp.x4 : 0,
      ),
      // 主聊天：顶栏下一行居中的小字（不是胶囊）：视觉上属于顶栏，不和消息抢层级；点它看本对话用量。
      // 项目：项目名药丸（ProjectPill 自带样式和点按）。
      Expanded(
        child: Center(
          child: _isProject
              ? widget.title
              : DefaultTextStyle(
                  style: context.text.labelLarge!.copyWith(height: 1.25, color: p.text2),
                  child: ChatTitle(scope: widget.projectId, dense: true, child: widget.title),
                ),
        ),
      ),
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
                  child: _isProject ? ProjectSwitcher(currentId: widget.projectId, docked: true) : const HistoryPanel(docked: true),
                ),
              )
            : null,
      ),
      Expanded(key: const ValueKey('chat'), child: ChatView(projectId: widget.projectId, suggestions: widget.suggestions)),
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
