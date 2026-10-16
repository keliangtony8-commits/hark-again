// 外壳（设计 v2）：壁纸 → 当前 Tab 的内容 → 浮动顶栏 → 收件箱横幅（最上层）。三个一级入口（主页/聊天/项目）各保留自己的导航栈和滚动位置。
// “我的”不再是 Tab，而是点右上角头像进入的全屏页（/me，见 app.dart）。
// 顶栏在一级页面和项目页（/projects/<id>，v2.93 §Q 项目对话也在一级外壳下）显示；进了子页面（规则与档案、电脑等，
// 它们是 SubPage，有自己的玻璃标题栏）就淡出让位。判定只有 shellBarShown 一处（网页 TopBar.tsx isShellRoot 同规则）。
// 手机、平板同一套结构：平板上聊天的历史栏常驻由 ChatScaffold 决定，外壳不管宽度。
// 收件箱提醒（横幅 + 主页角标）也挂在这一层：登录后才有外壳，正好是该轮询的范围。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/api.dart';
import '../core/profile.dart';
import '../features/home/inbox.dart';
import '../theme/look.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import 'top_bar.dart';

/// 一级页面的路径，顺序 = 分支顺序 = 顶栏分段顺序。
const shellRoots = ['/home', '/chat', '/projects'];

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
              index: shell.currentIndex,
              onSelect: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
              onAvatar: () => context.push('/me'),
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
