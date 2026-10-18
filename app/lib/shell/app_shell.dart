// 外壳（设计 v2）：壁纸 → 当前分支的内容 → 浮动顶栏 → 收件箱横幅（最上层）。四个一级分支（主页/聊天/项目/我的）各保留自己的导航栈和滚动位置。
// v3.5.1 照 Hark：“我的”是第四个分支（/me，见 app.dart），由右上头像进入；顶栏不消失，三个分段都不选中、头像高亮为当前项。
//   分支切换（ShellBranches）：进出“我的”整页横滑（去“我的”= 当前页向左滑出、“我的”从右滑入，回去反向）；主页/聊天/项目之间照旧直接切换。
// 顶栏在一级页面和项目页（/projects/<id>，v2.93 §Q 项目对话也在一级外壳下）显示；进了子页面（规则与档案、电脑、“我的”里的每一项等，
// 它们是 SubPage，有自己的返回钮）就淡出让位。判定只有 shellBarShown 一处（网页 TopBar.tsx isShellRoot 同规则）。
// 手机、平板同一套结构：平板上聊天的历史栏常驻由 ChatScaffold 决定，外壳不管宽度。
// 收件箱提醒（横幅 + 主页角标）也挂在这一层：登录后才有外壳，正好是该轮询的范围。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/profile.dart';
import '../features/home/inbox.dart';
import '../theme/look.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import 'top_bar.dart';

/// 一级页面的路径，顺序 = 分支顺序：前三个 = 顶栏分段，第四个“我的” = 顶栏头像（[meBranch]）。
const shellRoots = ['/home', '/chat', '/projects', '/me'];

/// “我的”分支的下标：顶栏头像对应它（分段导航只有前三个）。
const meBranch = 3;

final _projectPage = RegExp(r'^/projects/[^/]+$');

/// 浮动顶栏在这条路径上显示吗：三个一级页面 + 项目页（项目名在顶栏下的 header 行，不是子页面）。
bool shellBarShown(String location) => shellRoots.contains(location) || _projectPage.hasMatch(location);

/// 一级页面上盖了东西（v2.78：聊天的历史抽屉打开）→ 浮动顶栏淡出让位，不再画在抽屉上面（用户 15:30 截图“还叠在一起”）。
/// 弹层（ui/sheets.dart）走根导航器，本来就盖在外壳之上，不经这里。
class ShellCover extends Notifier<bool> {
  @override
  bool build() => false;

  void set(bool covered) {
    if (ref.mounted && state != covered) state = covered; // 页面拆掉时外壳可能已先销毁
  }
}

final shellCoverProvider = NotifierProvider<ShellCover, bool>(ShellCover.new);

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.shell, required this.location});
  final StatefulNavigationShell shell;
  final String location;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(inboxProvider.select((s) => s.unread));
    final avatar = ref.watch(lookProvider.select((l) => l.value?.avatar));
    final profile = ref.watch(profileProvider).value; // v2.92 §P 首字母 / 上传的头像
    final photo = profile?.avatar;
    final covered = ref.watch(shellCoverProvider);
    return Scaffold(
      backgroundColor: Colors.transparent,
      // 横幅浮在最上层（盖住顶栏，像系统通知）：InboxWatcher 包整层，而不是只包内容——
      // v1.08 前它只包内容，横幅被浮动顶栏压在下面，只露出半截。
      // 毛玻璃分组（v3.3）：顶栏和一级页面的左侧按钮 / header 共用一次取背景（ShellPage 先画内容和渐隐条、再画它们，顶栏最后）。
      // 横幅在组外：它盖在顶栏上，要模糊的正是顶栏。
      body: InboxWatcher(
          child: BlurGroup(
              child: SkyCoverScope(
                  child: Stack(children: [
        // 外壳壁纸：分支里的不透明子页（SubPage）进场完成后完全盖住它 → 暂停，返回一开始就恢复（ui/sky.dart SkyCover）
        const Positioned.fill(child: Backdrop(coverable: true)),
        Positioned.fill(child: shell),
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: FloatAway(
            visible: shellBarShown(location) && !covered,
            child: FloatingTopBar(
              index: shell.currentIndex, // = meBranch 时分段都不选中、头像高亮
              onSelect: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
              onAvatar: () => shell.goBranch(meBranch, initialLocation: shell.currentIndex == meBranch),
              avatarColor: avatar,
              initial: profile?.initial ?? '我',
              image: photo == null ? null : ref.read(apiProvider).fileUrl(photo),
              tabs: [(label: '主页', badge: unread), (label: '聊天', badge: 0), (label: '项目', badge: 0)],
            ),
          ),
        ),
      ])))),
    );
  }
}

/// 分支容器（StatefulShellRoute.navigatorContainerBuilder）：和 go_router 自带的 indexedStack 一样，每个分支常驻（Offstage + TickerMode），
/// 切换不丢导航栈和滚动位置；多的只有一件事——进出“我的”时整页横滑（v3.5.1 照 Hark，用户：“点击他做了一个从左往右滑的特效，就相当于切过去了”）：
/// 去“我的”= 当前页向左滑出、“我的”从右滑入；从“我的”回别的分支反过来。主页/聊天/项目之间照旧直接切换（不在这次改手感）。
/// 只动 transform（FractionalTranslation，整屏宽为单位），不动透明度、不触发布局；减少动态时直接切换。
/// 每个分支的子树结构固定不变（只改属性），切换不会重建页面状态；滑动中只有进出的两页在台上，其余照旧不画。
class ShellBranches extends StatefulWidget {
  const ShellBranches({super.key, required this.index, required this.children});
  final int index;
  final List<Widget> children;

  @override
  State<ShellBranches> createState() => _ShellBranchesState();
}

class _ShellBranchesState extends State<ShellBranches> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: Motion.slow, value: 1)..addStatusListener(_status);
  late final _t = CurvedAnimation(parent: _c, curve: Motion.ease);
  late int _from = widget.index; // 滑动中正在离场的分支
  double _dir = 1; // 1 = 新页从右边进（去“我的”），-1 = 从左边进（离开“我的”）

  bool get _sliding => _c.isAnimating;

  void _status(AnimationStatus s) {
    if (s.isCompleted && mounted) setState(() {}); // 离场页下台（Offstage）
  }

  @override
  void didUpdateWidget(ShellBranches old) {
    super.didUpdateWidget(old);
    if (old.index == widget.index) return;
    final crossesMe = (old.index == meBranch) != (widget.index == meBranch);
    if (crossesMe && !context.reduceMotion) {
      _from = old.index;
      _dir = widget.index == meBranch ? 1 : -1;
      _c.forward(from: 0);
    } else {
      _c.value = 1; // 三个分段之间 / 减少动态：直接切；滑到一半又切走也直接到位
      _from = widget.index;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  /// 第 [i] 个分支此刻的横向位移（屏宽的倍数）。
  double _dx(int i) {
    if (!_sliding) return 0;
    final t = _t.value;
    if (i == widget.index) return _dir * (1 - t);
    if (i == _from) return -_dir * t;
    return 0;
  }

  @override
  Widget build(BuildContext context) => Stack(fit: StackFit.expand, children: [
        for (var i = 0; i < widget.children.length; i++)
          Offstage(
            offstage: !(i == widget.index || (_sliding && i == _from)),
            child: TickerMode(
              enabled: i == widget.index || (_sliding && i == _from),
              child: IgnorePointer(
                ignoring: i != widget.index, // 离场页不接点击
                child: AnimatedBuilder(
                  animation: _t,
                  builder: (_, child) => FractionalTranslation(translation: Offset(_dx(i), 0), child: child),
                  child: widget.children[i],
                ),
              ),
            ),
          ),
      ]);
}
