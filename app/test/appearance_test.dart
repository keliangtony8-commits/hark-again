import 'package:assistant/features/me/preferences_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/appearance.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('Palette.lerp 两端等于原色、中间是渐变', () {
    expect(Palette.lerp(Palette.light, Palette.dark, 0).bg, Palette.light.bg);
    expect(Palette.lerp(Palette.light, Palette.dark, 1).accent, Palette.dark.accent);
    final mid = Palette.lerp(Palette.light, Palette.dark, 0.5).bg;
    expect(mid, isNot(Palette.light.bg));
    expect(mid, isNot(Palette.dark.bg));
  });

  test('状态栏图标与主题相反', () {
    expect(systemOverlay(Brightness.dark).statusBarIconBrightness, Brightness.light);
    expect(systemOverlay(Brightness.light).statusBarIconBrightness, Brightness.dark);
    expect(systemOverlay(Brightness.dark).systemNavigationBarColor, Colors.transparent);
  });

  test('外观偏好：默认跟随系统，未知值回落，设置后落盘', () async {
    SharedPreferences.setMockInitialValues({'appearance': 'weird'});
    final c = ProviderContainer();
    addTearDown(c.dispose);
    expect(await c.read(appearanceProvider.future), Appearance.system);
    await c.read(appearanceProvider.notifier).set(Appearance.dark);
    expect(c.read(appearanceProvider).value, Appearance.dark);
    expect((await SharedPreferences.getInstance()).getString('appearance'), 'dark');
  });

  testWidgets('偏好设置 → 外观：选“深色”整屏切到深色调色板', (tester) async {
    SharedPreferences.setMockInitialValues({'server': 'https://a.example'});
    FlutterSecureStoragePlatformMock.install();
    tester.view.physicalSize = const Size(1080, 2400); // 长屏：整页一次排完，不靠滚动
    tester.view.devicePixelRatio = 1.5;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      child: Consumer(builder: (context, ref, _) {
        final mode = ref.watch(appearanceProvider).value?.mode ?? ThemeMode.system;
        return MaterialApp(
          theme: buildTheme(Brightness.light),
          darkTheme: buildTheme(Brightness.dark),
          themeMode: mode,
          themeAnimationDuration: Motion.theme,
          home: const PreferencesScreen(),
        );
      }),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('appearance')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('深色').last);
    await tester.pumpAndSettle();
    final ctx = tester.element(find.byType(Scaffold));
    expect(Theme.of(ctx).brightness, Brightness.dark);
    expect(ctx.palette.bg, Palette.dark.bg);
  });
}

/// 测试环境没有 Keystore：给 flutter_secure_storage 的方法通道一个空实现。
abstract final class FlutterSecureStoragePlatformMock {
  static void install() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),
      (call) async => null,
    );
  }
}
