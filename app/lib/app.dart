// 路由与主题。未登录 → /login；登录后四个一级分支（主页/聊天/项目/我的），各自一条导航栈。
// “我的”是第四个分支（v3.5.1 照 Hark）：顶栏右上头像进入，顶栏不消失；和其他分支之间横滑切换（shell/app_shell.dart ShellBranches）。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/perf_overlay.dart';
import 'core/session.dart';
import 'features/auth/login_screen.dart';
import 'features/chat/chat_screen.dart';
import 'features/chat/history_panel.dart' show HistoryPage;
import 'features/home/home_screen.dart';
import 'features/computer/computer_screen.dart';
import 'features/me/connectors_screen.dart';
import 'features/me/about_screen.dart';
import 'features/me/perf_probe_screen.dart';
import 'features/me/me_hub.dart';
import 'features/me/me_screen.dart';
import 'features/me/preferences_screen.dart';
import 'features/me/memory_notes.dart';
import 'features/me/memory_screen.dart';
import 'features/me/pages_screen.dart';
import 'features/me/skill_library.dart';
import 'features/me/skills_screen.dart';
import 'features/me/task_detail.dart';
import 'features/me/tasks_screen.dart';
import 'features/me/usage_screen.dart';
import 'features/me/feedback_screen.dart';
import 'features/me/security_screen.dart';
import 'features/me/wallet_screen.dart';
import 'features/projects/project_brief_screen.dart';
import 'features/projects/projects_screen.dart';
import 'shell/app_shell.dart';
import 'theme/app_theme.dart';
import 'theme/appearance.dart';
import 'theme/look.dart';
import 'ui/glass.dart';
import 'ui/kit.dart' show SpotlightScope;
import 'ui/motion.dart';
import 'ui/sky.dart' show SkyScrollPause;
import 'theme/tokens.dart';
import 'brand.dart';

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: '/home',
    refreshListenable: refresh,
    redirect: (_, state) {
      final session = ref.read(sessionProvider);
      if (session.isLoading) return null;
      final signedIn = session.value?.signedIn ?? false;
      final atLogin = state.matchedLocation == '/login';
      if (!signedIn) return atLogin ? null : '/login';
      return atLogin ? '/home' : null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, _) => const LoginScreen()),
      StatefulShellRoute(
        builder: (_, state, shell) => AppShell(shell: shell, location: state.uri.path),
        navigatorContainerBuilder: (_, shell, children) => ShellBranches(index: shell.currentIndex, children: children),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/home', builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/chat', builder: (_, _) => const ChatScreen(), routes: [
              // v3.5.2 照 Hark：聊天左上 ☰ = 对话目录页（不是抽屉）；转场同项目页，左上 ☰/+ 的 Hero 骑在这条路由动画上
              GoRoute(
                path: 'history',
                pageBuilder: (_, s) => CustomTransitionPage<void>(
                  key: s.pageKey,
                  transitionDuration: Motion.morph,
                  reverseTransitionDuration: Motion.morph,
                  transitionsBuilder: (ctx, a, _, child) => pageRiseTransition(ctx, a, child),
                  child: const HistoryPage(),
                ),
              ),
            ]),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/projects', builder: (_, _) => const ProjectsScreen(), routes: [
              // v2.93 §Q 项目页自带转场（淡入 + 浮上，Motion.morph）：左上 +/≡ 的 Hero 飞行要骑在一条真的路由动画上。
              // 其余路由沿用 go_router 默认页（实测在本 App 里是无转场页，见 devlog v2.93），不在这一轮改全局手感。
              GoRoute(
                  path: ':id',
                  pageBuilder: (_, s) => CustomTransitionPage<void>(
                        key: s.pageKey,
                        transitionDuration: Motion.morph,
                        reverseTransitionDuration: Motion.morph,
                        transitionsBuilder: (ctx, a, _, child) => pageRiseTransition(ctx, a, child),
                        child: ProjectDetailScreen(id: s.pathParameters['id']!),
                      ),
                  routes: [
                GoRoute(path: 'brief', builder: (_, s) => ProjectBriefScreen(id: s.pathParameters['id']!)),
                GoRoute(path: 'computer', builder: (_, s) => ComputerScreen(ws: s.pathParameters['id']!), routes: [
                  // v3.5.1 电脑子页：tasks / ports / memory / processes / disk（见 computer_screen.dart）
                  GoRoute(path: ':part', builder: (_, s) => ComputerDetailScreen(ws: s.pathParameters['id']!, part: s.pathParameters['part']!)),
                ]),
              ]),
            ]),
          ]),
          // 我的：第四个分支（头像进入）。子页仍是 SubPage（自带返回钮，顶栏淡出）；深链 /me/connectors?… 直接打开时栈底是“我的”，返回回到它。
          StatefulShellBranch(routes: [
            GoRoute(path: '/me', builder: (_, _) => const MeScreen(), routes: [
              GoRoute(path: 'memory', builder: (_, _) => const MemoryScreen(), routes: [
                GoRoute(path: 'notes/:id', builder: (_, s) => MemoryNoteScreen(id: s.pathParameters['id']!)),
              ]),
              GoRoute(path: 'tasks', builder: (_, _) => const TasksScreen(), routes: [
                GoRoute(path: ':id', builder: (_, s) => TaskDetailScreen(id: s.pathParameters['id']!)),
              ]),
              GoRoute(path: 'connectors', builder: (_, s) => ConnectorsScreen(oauth: OAuthResult.fromQuery(s.uri.queryParameters))),
              GoRoute(path: 'wallet', builder: (_, _) => const WalletScreen()),
              GoRoute(path: 'security', builder: (_, s) => _spot(s, const SecurityScreen())),
              GoRoute(path: 'feedback', builder: (_, _) => const FeedbackScreen(), routes: [
                GoRoute(path: ':id', builder: (_, s) => FeedbackDetailScreen(id: s.pathParameters['id']!)),
              ]),
              GoRoute(path: 'computer', builder: (_, s) => _spot(s, const ComputerScreen()), routes: [
                // v3.5.1 子页：tasks / ports / memory / processes / disk / browser-logins / pages / host
                GoRoute(path: ':part', builder: (_, s) => ComputerDetailScreen(part: s.pathParameters['part']!)),
              ]),
              GoRoute(path: 'pages', builder: (_, _) => const PagesScreen()),
              GoRoute(path: 'usage', builder: (_, _) => const UsageScreen(), routes: [
                GoRoute(path: ':part', builder: (_, s) => UsageDetailScreen(part: s.pathParameters['part']!)),
              ]),
              GoRoute(path: 'profile', builder: (_, _) => const MeHubScreen(hub: MeHub.profile)),
              GoRoute(path: 'preferences', builder: (_, s) => _spot(s, const PreferencesScreen())),
              GoRoute(path: 'about', builder: (_, s) => _spot(s, const AboutScreen())),
              GoRoute(path: 'perf-probe', builder: (_, _) => const PerfProbeScreen()), // v3.5.3 性能自检结果
              GoRoute(path: 'skills', builder: (_, _) => const SkillsScreen(), routes: [
                GoRoute(path: ':id', builder: (_, s) => SkillEditorScreen(id: s.pathParameters['id']!, starter: s.extra is SkillStarter ? s.extra as SkillStarter : null)),
              ]),
            ]),
          ]),
        ],
      ),
    ],
  );
});

/// v3.0 设置搜索直达：带 `?focus=<id>` 进这几页时，页里对应的 Spotlight 滚到那一项并闪一下（索引在 features/me/me_index.dart）。
Widget _spot(GoRouterState s, Widget page) => SpotlightScope(focus: s.uri.queryParameters['focus'], child: page);

final _light = buildTheme(Brightness.light);
final _dark = buildTheme(Brightness.dark);

class AssistantApp extends ConsumerWidget {
  const AssistantApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appearance = ref.watch(appearanceProvider);
    final mode = appearance.value?.mode ?? ThemeMode.system;
    final solid = ref.watch(lookProvider.select((l) => l.value?.solid ?? false));
    // 偏好没读完前不画任何东西，避免“先亮后暗”闪一下
    if (ref.watch(sessionProvider).isLoading || appearance.isLoading) {
      return MaterialApp(theme: _light, darkTheme: _dark, themeMode: mode, home: const SizedBox.shrink());
    }
    return MaterialApp.router(
      title: appName,
      debugShowCheckedModeBanner: false,
      showPerformanceOverlay: ref.watch(perfOverlayProvider).value ?? false, // v3.5.2 隐藏开关：关于页连点版本 5 次
      theme: _light,
      darkTheme: _dark,
      themeMode: mode,
      themeAnimationDuration: Motion.theme,
      themeAnimationCurve: Motion.ease,
      scrollBehavior: const AppScrollBehavior(),
      builder: (context, child) => MediaQuery.withClampedTextScaling(
        // 跟随系统字号，但封顶：页面在 1.3 倍下有测试兜底，再往上只保证不崩
        maxScaleFactor: A11y.textScaleMax,
        child: AnnotatedRegion<SystemUiOverlayStyle>(
          value: systemOverlay(Theme.of(context).brightness),
          child: GlassMode(solid: solid, child: SkyScrollPause(child: child!)), // v3.5.2 滑动期间暂停流光（ui/sky.dart）
        ),
      ),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
