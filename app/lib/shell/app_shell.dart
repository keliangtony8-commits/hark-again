// 外壳（设计 v2）：壁纸 → 当前 Tab 的内容 → 浮动顶栏 → 收件箱横幅（最上层）。三个一级入口（主页/聊天/项目）各保留自己的导航栈和滚动位置。
// “我的”不再是 Tab，而是点右上角头像进入的全屏页（/me，见 app.dart）。
// 顶栏只在一级页面显示；进了子页面（项目详情等，它们是 SubPage，有自己的玻璃标题栏）就淡出让位。
// 手机、平板同一套结构：平板上聊天的历史栏常驻由 ChatScaffold 决定，外壳不管宽度。
// 收件箱提醒（横幅 + 主页角标）也挂在这一层：登录后才有外壳，正好是该轮询的范围。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/home/inbox.dart';
import '../theme/look.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import 'top_bar.dart';

/// 一级页面的路径，顺序 = 分支顺序 = 顶栏分段顺序。
const shellRoots = ['/home', '/chat', '/projects'];

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.shell, required this.location});
  final StatefulNavigationShell shell;
  final String location;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(inboxProvider.select((s) => s.unread));
    final avatar = ref.watch(lookProvider.select((l) => l.value?.avatar));
    return Scaffold(
      backgroundColor: Colors.transparent,
      // 横幅浮在最上层（盖住顶栏，像系统通知）：InboxWatcher 包整层，而不是只包内容——
      // v1.08 前它只包内容，横幅被浮动顶栏压在下面，只露出半截。
      body: InboxWatcher(
          child: Stack(children: [
        const Positioned.fill(child: Backdrop()),
        Positioned.fill(child: shell),
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: FloatAway(
            visible: shellRoots.contains(location),
            child: FloatingTopBar(
              index: shell.currentIndex,
              onSelect: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
              onAvatar: () => context.push('/me'),
              avatarColor: avatar,
              tabs: [(label: '主页', badge: unread), (label: '聊天', badge: 0), (label: '项目', badge: 0)],
            ),
          ),
        ),
      ])),
    );
  }
}
