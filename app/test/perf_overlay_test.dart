// v3.5.2 隐藏性能浮层：关于页连点“版本”5 次打开（存本机、重启保留），再连点 5 次关闭；点慢了重新数；一行轻提示。
// 同文件顺带：PulseDot 30fps 节拍（曲线不变、不在台上 / 减少动态不起 Timer）。
import 'package:assistant/brand.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/perf_overlay.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/about_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://ai.example.com', token: 't');
}

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async => throw Exception('404');

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

/// 和 app.dart 一样：MaterialApp.showPerformanceOverlay 跟着 perfOverlayProvider。
class _App extends ConsumerWidget {
  const _App();
  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp(
        showPerformanceOverlay: ref.watch(perfOverlayProvider).value ?? false,
        theme: buildTheme(Brightness.light),
        home: const AboutScreen(),
      );
}

Future<void> _pump(WidgetTester tester) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 1600);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(_Api()), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: const _App(),
  ));
  await tester.pumpAndSettle();
}

bool _overlay(WidgetTester tester) => tester.widget<MaterialApp>(find.byType(MaterialApp)).showPerformanceOverlay;

Future<void> _tapVersion(WidgetTester tester, int n, {Duration gap = const Duration(milliseconds: 200)}) async {
  for (var i = 0; i < n; i++) {
    await tester.tap(find.text(appVersion));
    await tester.pump(gap);
  }
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('连点版本 5 次打开、存本机；重启后仍开；再连点 5 次关闭', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await _pump(tester);
    expect(_overlay(tester), isFalse);
    expect(find.byIcon(Icons.chevron_right_rounded).evaluate().length, 1, reason: '版本行不多出箭头（只有“开源许可”那一行有）');

    await _tapVersion(tester, 4);
    expect(_overlay(tester), isFalse, reason: '4 次不触发');
    await _tapVersion(tester, 1);
    expect(_overlay(tester), isTrue);
    expect(find.text('性能浮层已打开，再连点 5 次关闭'), findsOneWidget);
    expect((await SharedPreferences.getInstance()).getBool(PerfOverlayNotifier.key), isTrue);

    // “重启”：新的 ProviderScope 从本机偏好读
    await tester.pumpWidget(const SizedBox());
    await _pump(tester);
    expect(_overlay(tester), isTrue, reason: '重启保留');

    await _tapVersion(tester, 5);
    expect(_overlay(tester), isFalse);
    expect(find.text('性能浮层已关闭'), findsOneWidget);
    expect((await SharedPreferences.getInstance()).getBool(PerfOverlayNotifier.key), isFalse);
  });

  testWidgets('点慢了（间隔超过 0.8 秒）重新数', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await _pump(tester);
    await _tapVersion(tester, 3);
    await tester.pump(const Duration(seconds: 1));
    await _tapVersion(tester, 3);
    expect(_overlay(tester), isFalse);
    await _tapVersion(tester, 2);
    expect(_overlay(tester), isTrue);
  });

  group('PulseDot 30fps', () {
    test('曲线同原来：0.3 ↔ 1 线性往返，单程 Motion.pulse', () {
      final half = Motion.pulse.inMilliseconds;
      expect(PulseDot.opacityAt(0), closeTo(0.3, 1e-9));
      expect(PulseDot.opacityAt(half ~/ 2), closeTo(0.65, 1e-3));
      expect(PulseDot.opacityAt(half), closeTo(1, 1e-9));
      expect(PulseDot.opacityAt(half * 3 ~/ 2), closeTo(0.65, 1e-3));
      expect(PulseDot.opacityAt(half * 2), closeTo(0.3, 1e-9));
      expect(PulseDot.frame, const Duration(milliseconds: 33));
    });

    testWidgets('在台上不请求 vsync 帧，按 33ms 步进；TickerMode 关 / 减少动态不起 Timer', (tester) async {
      Widget host({bool ticker = true, bool reduce = false}) => MediaQuery(
            data: MediaQueryData(disableAnimations: reduce),
            child: TickerMode(enabled: ticker, child: const Center(child: PulseDot(color: Colors.red))),
          );
      dynamic state() => tester.state(find.byType(PulseDot));
      double opacity() => tester.widget<FadeTransition>(find.descendant(of: find.byType(PulseDot), matching: find.byType(FadeTransition))).opacity.value;

      await tester.pumpWidget(host());
      expect(state().running, isTrue);
      expect(tester.binding.hasScheduledFrame, isFalse, reason: '没有 Ticker：静止时不每个 vsync 出帧');
      final o0 = opacity();
      await tester.pump(const Duration(milliseconds: 300));
      expect(opacity(), greaterThan(o0));

      await tester.pumpWidget(host(ticker: false));
      expect(state().running, isFalse, reason: '不在台上不走');
      await tester.pumpWidget(host(reduce: true));
      expect(state().running, isFalse);
      expect(opacity(), closeTo(0.65, 1e-3), reason: '减少动态停在中间值');
      await tester.pumpWidget(const SizedBox());
    });
  });
}
