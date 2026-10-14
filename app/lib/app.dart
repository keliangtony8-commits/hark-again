// 路由与主题。未登录 → /login；登录后三个一级 Tab（主页/聊天/项目），各自一条导航栈；“我的”是头像进入的全屏页。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/session.dart';
import 'features/auth/login_screen.dart';
import 'features/chat/chat_screen.dart';
import 'features/home/home_screen.dart';
import 'features/computer/computer_screen.dart';
import 'features/me/connectors_screen.dart';
import 'features/me/about_screen.dart';
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
import 'features/me/vault_screen.dart';
import 'features/me/wallet_screen.dart';
import 'features/projects/project_brief_screen.dart';
import 'features/projects/projects_screen.dart';
import 'shell/app_shell.dart';
import 'theme/app_theme.dart';
import 'theme/appearance.dart';
import 'theme/look.dart';
import 'ui/glass.dart';
import 'theme/tokens.dart';

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
      StatefulShellRoute.indexedStack(
        builder: (_, state, shell) => AppShell(shell: shell, location: state.uri.path),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/home', builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/chat', builder: (_, _) => const ChatScreen())]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/projects', builder: (_, _) => const ProjectsScreen(), routes: [
              GoRoute(path: ':id', builder: (_, s) => ProjectDetailScreen(id: s.pathParameters['id']!), routes: [
                GoRoute(path: 'brief', builder: (_, s) => ProjectBriefScreen(id: s.pathParameters['id']!)),
                GoRoute(path: 'computer', builder: (_, s) => ComputerScreen(ws: s.pathParameters['id']!)),
              ]),
            ]),
          ]),
        ],
      ),
      // 我的：点头像进入的全屏页，盖在外壳上面（不是 Tab）。深链 /me/connectors?… 直接打开时返回会回到主页（见 MeScreen）。
      GoRoute(path: '/me', builder: (_, _) => const MeScreen(), routes: [
        GoRoute(path: 'memory', builder: (_, _) => const MemoryScreen(), routes: [
          GoRoute(path: 'notes/:id', builder: (_, s) => MemoryNoteScreen(id: s.pathParameters['id']!)),
        ]),
        GoRoute(path: 'tasks', builder: (_, _) => const TasksScreen(), routes: [
          GoRoute(path: ':id', builder: (_, s) => TaskDetailScreen(id: s.pathParameters['id']!)),
        ]),
        GoRoute(path: 'connectors', builder: (_, s) => ConnectorsScreen(oauth: OAuthResult.fromQuery(s.uri.queryParameters))),
        GoRoute(path: 'vault', builder: (_, _) => const VaultScreen()),
        GoRoute(path: 'wallet', builder: (_, _) => const WalletScreen()),
        GoRoute(path: 'security', builder: (_, _) => const SecurityScreen()),
        GoRoute(path: 'feedback', builder: (_, _) => const FeedbackScreen(), routes: [
          GoRoute(path: ':id', builder: (_, s) => FeedbackDetailScreen(id: s.pathParameters['id']!)),
        ]),
        GoRoute(path: 'computer', builder: (_, _) => const ComputerScreen()),
        GoRoute(path: 'pages', builder: (_, _) => const PagesScreen()),
        GoRoute(path: 'usage', builder: (_, _) => const UsageScreen()),
        GoRoute(path: 'profile', builder: (_, _) => const MeHubScreen(hub: MeHub.profile)),
        GoRoute(path: 'accounts', builder: (_, _) => const MeHubScreen(hub: MeHub.accounts)),
        GoRoute(path: 'preferences', builder: (_, _) => const PreferencesScreen()),
        GoRoute(path: 'about', builder: (_, _) => const AboutScreen()),
        GoRoute(path: 'skills', builder: (_, _) => const SkillsScreen(), routes: [
          GoRoute(path: ':id', builder: (_, s) => SkillEditorScreen(id: s.pathParameters['id']!, starter: s.extra is SkillStarter ? s.extra as SkillStarter : null)),
        ]),
      ]),
    ],
  );
});

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
      title: '助手',
      debugShowCheckedModeBanner: false,
      theme: _light,
      darkTheme: _dark,
      themeMode: mode,
      themeAnimationDuration: Motion.theme,
      themeAnimationCurve: Motion.ease,
      builder: (context, child) => MediaQuery.withClampedTextScaling(
        // 跟随系统字号，但封顶：页面在 1.3 倍下有测试兜底，再往上只保证不崩
        maxScaleFactor: A11y.textScaleMax,
        child: AnnotatedRegion<SystemUiOverlayStyle>(
          value: systemOverlay(Theme.of(context).brightness),
          child: GlassMode(solid: solid, child: child!),
        ),
      ),
      routerConfig: ref.watch(routerProvider),
    );
  }
}
