// v3.5.3 性能自检：PerfProbe 默认全开、变体切换与恢复（各层真的换、页面状态不丢）、统计函数、runner 跑变体并恢复、关于页入口只在浮层打开时出现。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/perf_overlay.dart';
import 'package:assistant/core/perf_probe.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/about_screen.dart';
import 'package:assistant/features/me/perf_probe_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/sky.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Counter extends StatefulWidget {
  const _Counter();
  @override
  State<_Counter> createState() => _CounterState();
}

class _CounterState extends State<_Counter> {
  int n = 0;
  @override
  Widget build(BuildContext context) => Text('n=$n', textDirection: TextDirection.ltr);
}

class _Marker extends StatelessWidget {
  const _Marker({required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => child;
}

Widget _layers() => MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Backdrop(
        child: Stack(children: [
          const Positioned(top: 0, left: 0, right: 0, height: 120, child: BackdropFade(clear: 40, solid: 120)),
          const Positioned(top: 200, left: 20, child: GlassSurface(key: Key('top'), blur: true, probe: PerfBlur.topBar, child: SizedBox(width: 100, height: 40))),
          const Positioned(top: 300, left: 20, child: GlassSurface(key: Key('search'), blur: true, probe: PerfBlur.search, child: SizedBox(width: 100, height: 40))),
          const Positioned(top: 400, left: 20, child: GlassSurface(key: Key('btn'), blur: true, child: SizedBox(width: 40, height: 40))),
          const Positioned(top: 500, left: 20, child: GlassSurface(key: Key('card'), child: _Counter())),
        ]),
      ),
    );

bool _blurOn(WidgetTester t, String key) =>
    t.widget<BackdropFilter>(find.descendant(of: find.byKey(Key(key)), matching: find.byType(BackdropFilter))).enabled;
int _skies(WidgetTester t) => find.byType(SkyLayer).evaluate().length;
Color _cardColor(WidgetTester t) =>
    ((t.widget<AnimatedContainer>(find.descendant(of: find.byKey(const Key('card')), matching: find.byType(AnimatedContainer))).decoration!) as BoxDecoration).color!;

class _FakeRates implements PerfRateSource {
  int calls = 0;
  @override
  Future<double?> sample() async => (calls++).isEven ? 60.0 : 144.0;
}

class _FakeTimings implements PerfTimingSource {
  void Function(List<PerfSample>)? cb;
  @override
  void add(void Function(List<PerfSample>) onSamples) => cb = onSamples;
  @override
  void remove() => cb = null;
}

void main() {
  tearDown(() => PerfProbe.restore(rebuild: false));

  test('默认全开，A 就是现状', () {
    expect(PerfProbe.flags, PerfFlags.all);
    expect(PerfProbe.flags.isAll, isTrue);
    expect(PerfVariant.a.flags.isAll, isTrue);
    expect(PerfProbe.active.value, isNull);
    for (final b in PerfBlur.values) {
      expect(PerfProbe.flags.blur(b), isTrue);
    }
  });

  test('变体开关：D/E 只关一块、C 关所有模糊、H = B+C+F+G', () {
    expect(PerfVariant.d.flags.blur(PerfBlur.topBar), isFalse);
    expect(PerfVariant.d.flags.blur(PerfBlur.search), isTrue);
    expect(PerfVariant.e.flags.blur(PerfBlur.search), isFalse);
    expect(PerfVariant.e.flags.blur(PerfBlur.topBar), isTrue);
    expect(PerfBlur.values.every((b) => !PerfVariant.c.flags.blur(b)), isTrue);
    const h = PerfFlags(wallpaper: false, blurTopBar: false, blurSearch: false, blurOther: false, fade: false, translucentCards: false);
    expect(PerfVariant.h.flags, h);
    expect(PerfVariant.values.map((v) => v.code).join(), 'ABCDEFGH');
    PerfProbe.apply(PerfVariant.h, rebuild: false);
    expect(PerfProbe.flags, h);
    expect(PerfProbe.active.value, PerfVariant.h);
    PerfProbe.restore(rebuild: false);
    expect(PerfProbe.flags, PerfFlags.all);
    expect(PerfProbe.active.value, isNull);
  });

  test('统计：平均 / p90（最近秩）/ 最大 / 超预算占比 / 空', () {
    final s = PerfStats.of([for (var i = 1; i <= 10; i++) i.toDouble()], build: [0.5, 1.5], budgetMs: 8.3);
    expect(s.frames, 10);
    expect(s.rasterAvg, closeTo(5.5, 1e-9));
    expect(s.rasterP90, 9);
    expect(s.rasterMax, 10);
    expect(s.overBudget, closeTo(0.2, 1e-9)); // 9、10
    expect(s.buildAvg, 1.0);
    expect(s.buildMax, 1.5);
    expect(PerfStats.of([16.0]).rasterP90, 16);
    expect(PerfStats.of([]).frames, 0);
    final w = statsInWindow([
      (vsyncUs: 100, rasterMs: 50, buildMs: 0),
      (vsyncUs: 200, rasterMs: 4, buildMs: 0),
      (vsyncUs: 300, rasterMs: 6, buildMs: 0),
      (vsyncUs: 400, rasterMs: 50, buildMs: 0),
    ], 150, 350);
    expect(w.frames, 2);
    expect(w.rasterAvg, 5);
  });

  test('v3.5.4 withRate：fps = 帧数 / 时长，刷新率取最低 / 最高；读不到时显示“读不到”', () {
    final s = PerfStats.of(List.filled(153, 4.0)).withRate(durationUs: 2500000, hz: [60, 60, 120]);
    expect(s.fps, closeTo(61.2, 1e-9));
    expect(s.hzMin, 60);
    expect(s.hzMax, 120);
    expect(s.rasterAvg, 4);
    final none = PerfStats.of([4.0]).withRate(durationUs: 0);
    expect(none.fps, isNull);
    expect(none.hzMin, isNull);
    expect(perfHzLine(PerfReport(device: const {}, rows: [(PerfVariant.a, none)], budgetMs: 8.3)), '滑动中系统刷新率：读不到');
    expect(perfFlymeHint, contains('Flyme 若仍 60Hz'));
    // v3.5.5 提示只在滑动中刷新率 < 90Hz 时出：60 出、真机 120 不出、读不到不出
    PerfReport rep(List<double> hz) => PerfReport(device: const {}, rows: [(PerfVariant.a, PerfStats.of([4.0]).withRate(durationUs: 1, hz: hz))], budgetMs: 8.3);
    expect(perfNeedsHzHint(rep([60, 60, 120])), isTrue);
    expect(perfNeedsHzHint(rep([120, 120])), isFalse);
    expect(perfNeedsHzHint(rep([90])), isFalse);
    expect(perfNeedsHzHint(rep(const [])), isFalse);
  });

  testWidgets('切变体：各层真的换、不改树结构（状态不丢）、恢复回全开', (tester) async {
    await tester.pumpWidget(_layers());
    await tester.pump();
    expect(_skies(tester), 2, reason: '整屏壁纸 + 渐隐条');
    expect(_blurOn(tester, 'top') && _blurOn(tester, 'search') && _blurOn(tester, 'btn'), isTrue);
    final card0 = _cardColor(tester);
    expect(card0.a, lessThan(1));
    tester.state<_CounterState>(find.byType(_Counter)).n = 7;

    PerfProbe.apply(PerfVariant.d);
    await tester.pump();
    expect([_blurOn(tester, 'top'), _blurOn(tester, 'search'), _blurOn(tester, 'btn')], [false, true, true]);

    PerfProbe.apply(PerfVariant.e);
    await tester.pump();
    expect([_blurOn(tester, 'top'), _blurOn(tester, 'search'), _blurOn(tester, 'btn')], [true, false, true]);

    PerfProbe.apply(PerfVariant.c);
    await tester.pump();
    expect([_blurOn(tester, 'top'), _blurOn(tester, 'search'), _blurOn(tester, 'btn')], [false, false, false]);

    PerfProbe.apply(PerfVariant.b);
    await tester.pump();
    expect(_skies(tester), 1, reason: '整屏壁纸换纯色，渐隐条还在');

    PerfProbe.apply(PerfVariant.f);
    await tester.pump();
    expect(_skies(tester), 1, reason: '只剩整屏壁纸');
    expect(find.descendant(of: find.byType(BackdropFade), matching: find.byType(SkyLayer)), findsNothing);

    PerfProbe.apply(PerfVariant.g);
    await tester.pump();
    expect(_cardColor(tester).a, 1);
    expect(_cardColor(tester).withValues(alpha: card0.a), card0, reason: '同色，只改不透明度');

    PerfProbe.apply(PerfVariant.h);
    await tester.pump();
    expect(_skies(tester), 0);
    expect(tester.state<_CounterState>(find.byType(_Counter)).n, 7, reason: '切层不改树结构，子树状态保留');

    PerfProbe.restore();
    await tester.pumpAndSettle();
    expect(_skies(tester), 2);
    expect(_blurOn(tester, 'top') && _blurOn(tester, 'search') && _blurOn(tester, 'btn'), isTrue);
    expect(_cardColor(tester), card0);
    expect(tester.state<_CounterState>(find.byType(_Counter)).n, 7);
    expect(tester.takeException(), isNull);
  });

  testWidgets('runner：每个变体来回滚、按时间窗归帧、跑完恢复全开', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      home: _Marker(child: ListView(children: [for (var i = 0; i < 60; i++) SizedBox(height: 50, child: Text('$i'))])),
    ));
    final fake = _FakeTimings();
    final offsets = <double>{};
    // 每帧报一个假 FrameTiming：壁纸开着 12ms、关了 4ms（= 只看开关）；同时记下滚动位置
    SchedulerBinding.instance.addPersistentFrameCallback((_) {
      final cb = fake.cb;
      if (cb == null) return;
      final pos = tester.state<ScrollableState>(find.byType(Scrollable)).position;
      offsets.add(pos.pixels.roundToDouble());
      cb([(vsyncUs: SchedulerBinding.instance.currentSystemFrameTimeStamp.inMicroseconds, rasterMs: PerfProbe.flags.wallpaper ? 12.0 : 4.0, buildMs: 0.5)]);
    });
    final rates = _FakeRates();
    final runner = PerfProbeRunner(timings: fake, rates: rates, perVariant: const Duration(milliseconds: 1200));
    final seen = <PerfVariant?>[];
    void track() => seen.add(PerfProbe.active.value);
    PerfProbe.active.addListener(track);
    addTearDown(() => PerfProbe.active.removeListener(track));
    final done = runner.run(
      variants: const [PerfVariant.a, PerfVariant.b],
      budgetMs: 1000 / 120,
      locate: () => findScrollUnder<_Marker>(tester.binding.rootElement!),
    );
    PerfReport? report;
    done.then((r) => report = r);
    for (var i = 0; i < 600 && report == null; i++) {
      await tester.pump(const Duration(milliseconds: 16));
    }
    expect(report, isNotNull);
    final r = report!;
    expect(r.rows.map((e) => e.$1), [PerfVariant.a, PerfVariant.b]);
    final a = r.rows[0].$2, b = r.rows[1].$2;
    expect(a.frames, greaterThan(40));
    expect(b.frames, greaterThan(40));
    expect(a.rasterAvg, 12);
    expect(a.overBudget, 1);
    expect(b.rasterAvg, 4, reason: '切变体之后的重建/稳定期和上一个变体的帧不算进来');
    expect(b.overBudget, 0);
    expect(a.buildAvg, 0.5);
    // v3.5.4：滑动中约每 200ms 采一次系统刷新率；fps = 帧数 / 实际时长（测试里每 16ms 一帧 ≈ 62）
    expect(rates.calls, greaterThanOrEqualTo(2 * 5));
    expect(a.hzMin, 60);
    expect(a.hzMax, 144);
    expect(a.fps, closeTo(1000 / 16, 3));
    expect(perfHzLine(r), '滑动中系统刷新率：最低 60.0 Hz / 最高 144.0 Hz');
    expect(r.scrollExtent, 60 * 50 - 800);
    expect(offsets.contains(0) && offsets.contains(2200), isTrue, reason: '来回滚到两头');
    expect(seen, [PerfVariant.a, PerfVariant.b, null]);
    expect(PerfProbe.flags, PerfFlags.all, reason: '跑完恢复');
    expect(fake.cb, isNull, reason: '回调已摘');
    expect(PerfProbeRunner.last, same(r));
    expect(PerfProbeRunner.running, isFalse);
  });

  testWidgets('关于页：性能浮层打开时才有“性能自检”行', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(420, 1600);
    addTearDown(tester.view.reset);
    Future<void> pump(bool on) async {
      SharedPreferences.setMockInitialValues({PerfOverlayNotifier.key: on});
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(ProviderScope(
        overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(_Api()), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
        child: MaterialApp(theme: buildTheme(Brightness.light), home: const AboutScreen()),
      ));
      await tester.pumpAndSettle();
    }

    await pump(false);
    expect(find.text('性能自检'), findsNothing);
    await pump(true);
    expect(find.text('性能自检'), findsOneWidget);
  });
}

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
