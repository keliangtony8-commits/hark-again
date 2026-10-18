// v3.3 流光壁纸（v3.5.1 五团柔光流动 + 五色轮转）：关键帧插值、柔光流动幅度 / 色相轮转 / 与网页同一组测试向量、浅 / 深两套正文与次要字 text2 对壁纸任意一处 ≥ 4.5、最次要字 text3 ≥ 3（v3.3 B2）、SkyClock 单 Timer（测试环境不起、无订阅 / 后台停、
// 减少动态只换天色不漂移）、着色器加载不了时回退竖向渐变。
import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/motion.dart';
import 'package:assistant/ui/sky.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

double _contrast(Color a, Color b) {
  final x = a.computeLuminance(), y = b.computeLuminance();
  return (math.max(x, y) + 0.05) / (math.min(x, y) + 0.05);
}

/// 壁纸上真实会出现的颜色（v3.5.1 五色轮转）：底色按 Sky.ramp 取 11 个高度，再叠上
/// ①每个色相、②相邻两色相过渡的中点，各按每团柔光的强度；③任意两团以最大强度先后重叠（sRGB 混合会比两色都暗 / 亮）。
/// = 网页 scripts/check-contrast.mjs 与 tests/sky.test.ts 同一采样。
Iterable<(String, Color)> _samples(SkyPhase ph) sync* {
  final hues = ph.hues;
  final tones = [...hues, for (var j = 0; j < hues.length; j++) ph.hue(j + 0.5)];
  final mixes = {for (final b in Sky.blobs) b.mix}.toList()..sort();
  final top = mixes.last;
  for (var i = 0; i <= 10; i++) {
    final y = i / 10;
    final base = Color.lerp(ph.top, ph.bottom, Sky.ramp(y))!;
    yield ('底色 y=$y', base);
    for (final m in mixes) {
      for (var k = 0; k < tones.length; k++) {
        yield ('色相$k×$m y=$y', Color.lerp(base, tones[k], m)!);
      }
    }
    for (var a = 0; a < hues.length; a++) {
      for (var b = 0; b < hues.length; b++) {
        if (a != b) yield ('重叠$a+$b y=$y', Color.lerp(Color.lerp(base, hues[a], top)!, hues[b], top)!);
      }
    }
  }
}

Widget _host(Widget child, {bool reduceMotion = false, bool tickers = true}) => MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Builder(
        builder: (ctx) => MediaQuery(
          data: MediaQuery.of(ctx).copyWith(disableAnimations: reduceMotion),
          child: TickerMode(enabled: tickers, child: child),
        ),
      ),
    );

void main() {
  group('SkyTable 关键帧插值', () {
    for (final (name, t) in [('浅色', SkyTable.light), ('深色', SkyTable.dark)]) {
      test('$name：关键帧处等于该时段，之间线性过渡，跨午夜连续', () {
        expect(t.at(0), t.night);
        expect(t.at(3), t.night);
        expect(t.at(4.5), t.night);
        expect(t.at(6), t.dawn);
        expect(t.at(8), t.day);
        expect(t.at(12), t.day);
        expect(t.at(16.5), t.day);
        expect(t.at(18.5), t.dusk);
        expect(t.at(20.5), t.night);
        expect(t.at(5.25), SkyPhase.lerp(t.night, t.dawn, 0.5));
        expect(t.at(7), SkyPhase.lerp(t.dawn, t.day, 0.5));
        expect(t.at(17.5), SkyPhase.lerp(t.day, t.dusk, 0.5));
        expect(t.at(19.5), SkyPhase.lerp(t.dusk, t.night, 0.5));
        expect(t.at(24), t.at(0));
        expect(t.at(25.5), t.at(1.5));
      });
    }

    test('Palette 主题切换时 sky 一起插值', () {
      final mid = Palette.lerp(Palette.light, Palette.dark, 0.5);
      expect(mid.sky.day, SkyPhase.lerp(SkyTable.light.day, SkyTable.dark.day, 0.5));
    });

    test('Sky.ramp / fadeAlpha 端点', () {
      expect(Sky.ramp(0), 0);
      expect(Sky.ramp(1), 1);
      expect(Sky.ramp(0.5), greaterThan(0.5), reason: '比线性更早变淡');
      expect(Sky.fadeAlpha(10, 20, 40), 1);
      expect(Sky.fadeAlpha(40, 20, 40), 0);
      expect(Sky.fadeAlpha(30, 20, 40), closeTo(0.5, 1e-9));
    });
  });

  // 网页 scripts/check-contrast.mjs 与 tests/sky.test.ts 用同一采样、同一阈值（两端同一张色表）。
  group('文字对壁纸对比度（全天每 15 分钟 × 底色 × 柔光色相 / 过渡 / 两团重叠）：正文 / 次要字 ≥ 4.5，最次要字 ≥ 3', () {
    for (final (name, p) in [('浅色', Palette.light), ('深色', Palette.dark)]) {
      for (final (what, fg, min) in [('正文 text', p.text, 4.5), ('次要字 text2', p.text2, 4.5), ('最次要字 text3', p.text3, 3.0)]) {
        test('$name $what ≥ $min', () {
          var worst = double.infinity;
          var where = '';
          for (var q = 0; q < 24 * 4; q++) {
            final h = q / 4;
            for (final (at, c) in _samples(p.sky.at(h))) {
              final r = _contrast(fg, c);
              if (r < worst) {
                worst = r;
                where = '$h 点 $at';
              }
            }
          }
          expect(worst, greaterThanOrEqualTo(min), reason: '$name $what 最差 ${worst.toStringAsFixed(2)} @ $where');
        });
      }
    }
  });

  group('柔光流动（v3.5.1：肉眼清楚可见、多色轮转）', () {
    test('五团柔光，周期在 18–45 秒、两两不同；强度不超过 0.8', () {
      expect(Sky.blobs, hasLength(5));
      final periods = [for (final b in Sky.blobs) ...[b.tx, b.ty]];
      expect(periods.every((p) => p >= 18 && p <= 45), isTrue);
      expect(periods.toSet(), hasLength(periods.length), reason: '漂移周期两两不同，叠在一起不整齐重复');
      expect(Sky.blobs.every((b) => b.mix <= 0.8), isTrue);
      expect({for (final b in Sky.blobs) b.hue}, {0.0, 1.0, 2.0, 3.0, 4.0}, reason: '五团各从不同色相起步：任何时刻五色都在屏上');
    });

    test('10 秒内每一团都明显移动（≥ 屏高的 4%）或明显换色', () {
      const aspect = 0.45;
      for (var i = 0; i < Sky.blobs.length; i++) {
        final b = Sky.blobs[i];
        for (final t0 in [0.0, 13.0, 47.0, 120.0]) {
          final p = b.at(t0, aspect), q = b.at(t0 + 10, aspect);
          final moved = math.sqrt(math.pow(p.x - q.x, 2) + math.pow(p.y - q.y, 2));
          final ph = SkyTable.light.day;
          final c0 = ph.hue(t0 / Sky.hueStep + b.hue), c1 = ph.hue((t0 + 10) / Sky.hueStep + b.hue);
          final dc = ((c0.r - c1.r).abs() + (c0.g - c1.g).abs() + (c0.b - c1.b).abs()) * 255;
          expect(moved >= 0.04 || dc >= 12, isTrue, reason: '第 $i 团 t=$t0 → +10s 位移 ${moved.toStringAsFixed(3)}、色差 ${dc.toStringAsFixed(1)}');
        }
      }
    });

    test('色相轮转：整数点就是那个色相，五步一圈，之间连续', () {
      final ph = SkyTable.light.day;
      expect(ph.hue(0), ph.a);
      expect(ph.hue(1), ph.b);
      expect(ph.hue(4), ph.e);
      expect(ph.hue(5), ph.a);
      expect(ph.hue(-1), ph.e);
      expect(ph.hue(0.5), Color.lerp(ph.a, ph.b, 0.5));
      final hues = {for (final x in ph.hues) x.toARGB32()};
      expect(hues, hasLength(5), reason: '白天五种不同颜色');
    });

    test('与网页 lib/sky.ts skyBlobAt 同一组测试向量（t = 10s、aspect = 0.5，第 0 / 3 团）', () {
      final a = Sky.blobs[0].at(10, 0.5), d = Sky.blobs[3].at(10, 0.5);
      expect(a.x, closeTo(0.14781, 1e-4));
      expect(a.y, closeTo(0.15790, 1e-4));
      expect(a.cos, closeTo(0.63332, 1e-4));
      expect(a.kx, closeTo(2.67028, 1e-4));
      expect(d.x, closeTo(0.39651, 1e-4));
      expect(d.sin, closeTo(-0.85731, 1e-4));
      expect(d.ky, closeTo(4.23114, 1e-4));
    });
  });

  group('SkyClock', () {
    test('测试环境（FLUTTER_TEST）：共用时钟冻结，订阅了也不起 Timer', () {
      final c = SkyClock.instance;
      expect(SkyClock.inTest, isTrue);
      expect(c.frozen, isTrue);
      c.acquire();
      expect(c.period, isNull);
      c.release();
    });

    testWidgets('单 Timer：动画档 30fps、只剩静止订阅者降到每分钟、没人订阅 / 进后台就停', (tester) async {
      final c = SkyClock.forTest();
      expect(c.period, isNull);

      c.acquire();
      expect(c.period, Sky.frame);
      final t0 = c.time.value;
      await tester.pump(const Duration(milliseconds: 200));
      expect(c.time.value, greaterThan(t0), reason: '动画档推进漂移');

      c.acquire(animate: false);
      expect(c.period, Sky.frame, reason: '还有动画订阅者，仍按最高档跑一个 Timer');
      c.release();
      expect(c.period, Sky.recolor, reason: '只剩减少动态：只换天色');
      final t1 = c.time.value;
      await tester.pump(const Duration(seconds: 5));
      expect(c.time.value, t1, reason: '静止档柔光不动');

      c.didChangeAppLifecycleState(AppLifecycleState.paused);
      expect(c.period, isNull, reason: '后台不跑');
      c.didChangeAppLifecycleState(AppLifecycleState.resumed);
      expect(c.period, Sky.recolor);

      c.release(animate: false);
      expect(c.period, isNull, reason: '没有订阅者不跑');
    });

    testWidgets('SkyLayer 按可见性 / 减少动态选档，卸载后归零', (tester) async {
      final c = SkyClock.forTest();
      await tester.pumpWidget(_host(SkyLayer(clock: c)));
      expect(c.period, Sky.frame);

      await tester.pumpWidget(_host(SkyLayer(clock: c), reduceMotion: true));
      expect(c.period, Sky.recolor, reason: '减少动态：不漂移，只随钟点换天色');

      await tester.pumpWidget(_host(SkyLayer(clock: c), tickers: false));
      expect(c.period, isNull, reason: '看不见（被盖住的路由）不订阅');

      await tester.pumpWidget(_host(SkyLayer(clock: c)));
      expect(c.period, Sky.frame);
      await tester.pumpWidget(_host(const SizedBox()));
      expect(c.period, isNull);
    });
  });

  group('SkyLayer 画法', () {
    testWidgets('测试环境不加载着色器 → 回退竖向渐变，整屏一个矩形，自身是重绘边界', (tester) async {
      await tester.pumpWidget(_host(const SkyLayer()));
      expect(SkyShader.program, isNull);
      expect(tester.takeException(), isNull);
      final paint = find.descendant(of: find.byType(SkyLayer), matching: find.byType(CustomPaint));
      expect(tester.renderObject(paint), paints..rect(rect: Offset.zero & tester.view.physicalSize / tester.view.devicePixelRatio));
      expect(find.descendant(of: find.byType(SkyLayer), matching: find.byType(RepaintBoundary)), findsOneWidget);
    });

    testWidgets('渐隐条（fade）回退同样能画', (tester) async {
      await tester.pumpWidget(_host(const Align(alignment: Alignment.topCenter, child: SizedBox(height: 80, child: SkyLayer(fade: (40, 80))))));
      expect(tester.takeException(), isNull);
      final paint = find.descendant(of: find.byType(SkyLayer), matching: find.byType(CustomPaint));
      expect(tester.renderObject(paint), paints..rect());
    });

    testWidgets('Backdrop 的壁纸就是 SkyLayer', (tester) async {
      await tester.pumpWidget(_host(const Backdrop(child: Text('x'))));
      expect(find.byType(SkyLayer), findsOneWidget);
      expect(find.text('x'), findsOneWidget);
    });

    testWidgets('着色器能编译加载，且 uniform 个数与画法对得上（真走着色器那条路径画一帧不报错）', (tester) async {
      final prog = await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky.frag'));
      expect(prog, isNotNull);
      SkyShader.program = prog;
      addTearDown(() => SkyShader.program = null);
      await tester.pumpWidget(_host(const SkyLayer()));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(_host(const SizedBox(height: 80, child: SkyLayer(fade: (40, 80)))));
      expect(tester.takeException(), isNull);
    });
  });

  group('被不透明子页盖住时暂停（v3.3 B4）', () {
    // 外壳 = SkyCoverScope + 一层 coverable 壁纸（独立时钟，便于数订阅）+ 导航器；子页 = SubPage 同款 SkyCover + Backdrop。
    Widget shell(SkyClock c, GlobalKey<NavigatorState> nav) => _host(SkyCoverScope(
          child: Stack(children: [
            Positioned.fill(child: SkyLayer(coverable: true, clock: c)),
            Navigator(key: nav, onGenerateRoute: (_) => PageRouteBuilder<void>(opaque: false, pageBuilder: (_, _, _) => const SizedBox.expand())),
          ]),
        ));
    Route<void> sub() => MaterialPageRoute<void>(builder: (_) => const SkyCover(child: Backdrop(child: Text('子页'))));
    RenderObject paintOf(WidgetTester t) => t.renderObject(find.descendant(of: find.byWidgetPredicate((w) => w is SkyLayer && w.coverable), matching: find.byType(CustomPaint)));

    testWidgets('进场转场中照常；完成后外壳订阅数归零、时钟走也不重画；返回第一帧就恢复并重画；全程无异常', (tester) async {
      final c = SkyClock.forTest(frozen: true); // 不起 Timer，只数订阅
      final nav = GlobalKey<NavigatorState>();
      await tester.pumpWidget(shell(c, nav));
      expect(c.subscribers, 1);

      unawaited(nav.currentState!.push(sub()));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100)); // 转场中：子页还没完全盖住
      expect(c.subscribers, 1, reason: '转场中外壳壁纸必须照常显示和流动');
      c.time.value += 0.1;
      expect(paintOf(tester).debugNeedsPaint, isTrue);

      await tester.pumpAndSettle();
      expect(c.subscribers, 0, reason: '进场完成、被不透明子页完全盖住：外壳退订');
      await tester.pump();
      c.time.value += 0.1;
      c.hour.value += 0.5;
      expect(paintOf(tester).debugNeedsPaint, isFalse, reason: '暂停期间时钟照走，外壳那层不重画');

      nav.currentState!.pop();
      expect(c.subscribers, 1, reason: 'pop 一开始（status 离开 completed）就恢复，先于第一帧转场');
      expect(paintOf(tester).debugNeedsPaint, isTrue, reason: '恢复时重画一次，直接取时钟此刻的天色和柔光位置');
      await tester.pumpAndSettle();
      expect(c.subscribers, 1);
      expect(find.text('子页'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('子页上再压一层子页、半透明路由、根导航器（无 Scope）都不出错；卸载后计数回零', (tester) async {
      final c = SkyClock.forTest(frozen: true);
      final nav = GlobalKey<NavigatorState>();
      await tester.pumpWidget(shell(c, nav));
      unawaited(nav.currentState!.push(sub()));
      await tester.pumpAndSettle();
      unawaited(nav.currentState!.push(sub()));
      await tester.pumpAndSettle();
      expect(c.subscribers, 0, reason: '上面那层接着盖，下面那层 offstage 后撤销');
      nav.currentState!.pop();
      await tester.pump();
      expect(c.subscribers, 0, reason: '下面那层子页回到台上，仍然盖住');
      await tester.pumpAndSettle();
      expect(c.subscribers, 0);

      // 半透明（opaque: false）的路由盖不住：不暂停
      unawaited(nav.currentState!.push(PageRouteBuilder<void>(opaque: false, pageBuilder: (_, _, _) => const SkyCover(child: SizedBox.expand()))));
      await tester.pumpAndSettle();
      expect(c.subscribers, 0, reason: '下面的不透明子页仍在台上');
      nav.currentState!.pop();
      await tester.pumpAndSettle();
      nav.currentState!.pop();
      await tester.pumpAndSettle();
      expect(c.subscribers, 1);

      unawaited(nav.currentState!.push(PageRouteBuilder<void>(opaque: false, pageBuilder: (_, _, _) => const SkyCover(child: SizedBox.expand()))));
      await tester.pumpAndSettle();
      expect(c.subscribers, 1, reason: '半透明路由透得出外壳壁纸，不暂停');

      await tester.pumpWidget(_host(const SkyCover(child: SizedBox()))); // 没有 Scope：什么也不做
      expect(c.subscribers, 0);
      expect(tester.takeException(), isNull);
    });
  });
}
