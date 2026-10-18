// v3.5.2 流光壁纸贴图 + 滑动暂停（ui/sky.dart SkyFrames / SkyScrollPause，ui/motion.dart SkyClock.hold）。
// 诊断见 jank-diagnosis 第 3、4 项：Impeller 没有 raster cache，原来滑动时每个 vsync 整屏重跑 5 次 exp 的着色器。
import 'dart:ui' as ui;

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:assistant/ui/sky.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _app(Widget child) => MaterialApp(theme: buildTheme(Brightness.light), home: child);

void main() {
  group('SkyClock.hold', () {
    testWidgets('暂停时停 Timer、秒表不走；放开后接着走；成对叠加', (tester) async {
      final c = SkyClock.forTest();
      c.acquire();
      expect(c.period, isNotNull);
      c.hold(true);
      c.hold(true);
      expect(c.period, isNull);
      expect(c.held, isTrue);
      final t = c.time.value;
      await tester.pump(const Duration(seconds: 1));
      expect(c.time.value, t, reason: '暂停期间不推进');
      c.hold(false);
      expect(c.period, isNull, reason: '还有一个暂停没放开');
      c.hold(false);
      expect(c.held, isFalse);
      expect(c.period, isNotNull);
      c.release();
      expect(c.period, isNull);
    });
  });

  group('SkyScrollPause', () {
    testWidgets('开始滚动就暂停，停下 300ms 后恢复；中途再滚取消恢复', (tester) async {
      final c = SkyClock.forTest();
      c.acquire();
      await tester.pumpWidget(_app(SkyScrollPause(
        clock: c,
        child: ListView(children: [for (var i = 0; i < 80; i++) SizedBox(height: 60, child: Text('行 $i'))]),
      )));
      final g = await tester.startGesture(tester.getCenter(find.byType(ListView)));
      await g.moveBy(const Offset(0, -40));
      await tester.pump();
      expect(c.held, isTrue);
      expect(c.period, isNull);
      await g.moveBy(const Offset(0, -40));
      await g.up();
      await tester.pumpAndSettle(); // 惯性滚完 → ScrollEnd
      expect(c.held, isTrue, reason: '停下后还要等 300ms');
      await tester.pump(const Duration(milliseconds: 200));
      // 300ms 内再滚：取消恢复
      await tester.drag(find.byType(ListView), const Offset(0, -30));
      await tester.pumpAndSettle();
      expect(c.held, isTrue);
      await tester.pump(SkyScrollPause.resumeAfter);
      expect(c.held, isFalse);
      expect(c.period, isNotNull);
      c.release();
    });

    testWidgets('滚到一半整棵树被拆掉：放开暂停', (tester) async {
      final c = SkyClock.forTest();
      c.acquire();
      await tester.pumpWidget(_app(SkyScrollPause(
        clock: c,
        child: ListView(children: [for (var i = 0; i < 80; i++) const SizedBox(height: 60)]),
      )));
      final g = await tester.startGesture(tester.getCenter(find.byType(ListView)));
      await g.moveBy(const Offset(0, -40));
      await tester.pump();
      expect(c.held, isTrue);
      await tester.pumpWidget(const SizedBox());
      expect(c.held, isFalse);
      await g.up();
      c.release();
    });
  });

  group('SkyFrames（真着色器）', () {
    late ui.FragmentProgram prog, blit;

    testWidgets('整屏 + 渐隐条同一时钟步共用一张 1/4 图；时钟不走只贴图不重画；时钟走一步换图、旧图释放', (tester) async {
      tester.view.physicalSize = const Size(400, 800);
      tester.view.devicePixelRatio = 2;
      addTearDown(tester.view.reset);
      prog = (await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky.frag')))!;
      blit = (await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky_blit.frag')))!;
      SkyShader.program = prog;
      SkyShader.blit = blit;
      addTearDown(() => SkyShader.program = SkyShader.blit = null);
      SkyFrames.clear();
      addTearDown(SkyFrames.clear);
      final c = SkyClock.forTest(frozen: true);
      c.time.value = 12;
      await tester.pumpWidget(_app(Stack(children: [
        Positioned.fill(child: SkyLayer(clock: c)),
        Positioned(top: 0, left: 0, right: 0, height: 120, child: SkyLayer(clock: c, fade: (60, 120))),
      ])));
      final r0 = SkyFrames.renders;
      expect(r0, 1, reason: '两层同一步只画一次低分辨率图');
      expect(SkyFrames.held, 1);

      // 只重光栅（滑动帧）：不重画
      for (final ro in tester.renderObjectList<RenderCustomPaint>(find.descendant(of: find.byType(SkyLayer), matching: find.byType(CustomPaint)))) {
        ro.markNeedsPaint();
      }
      await tester.pump();
      expect(SkyFrames.renders, r0);

      // 时钟走一步：两层又共用一张新图，仍只持有一张
      c.time.value = 12.033;
      await tester.pump();
      expect(SkyFrames.renders, r0 + 1);
      expect(SkyFrames.held, 1);

      // 真的画得出来（贴图 + 抖动 + 渐隐），尺寸 1/4
      final boundary = tester.renderObject<RenderRepaintBoundary>(find.descendant(of: find.byType(SkyLayer).first, matching: find.byType(RepaintBoundary)));
      await tester.runAsync(() async {
        final img = await boundary.toImage();
        final bytes = await img.toByteData();
        expect(bytes!.lengthInBytes, greaterThan(0));
        img.dispose();
      });
      expect(tester.takeException(), isNull);
    });

    testWidgets('多套键（明暗渐变、换屏幕尺寸）最多留 3 张', (tester) async {
      prog = (await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky.frag')))!;
      blit = (await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky_blit.frag')))!;
      SkyShader.program = prog;
      SkyShader.blit = blit;
      addTearDown(() => SkyShader.program = SkyShader.blit = null);
      SkyFrames.clear();
      addTearDown(SkyFrames.clear);
      final c = SkyClock.forTest(frozen: true);
      for (var w = 300.0; w < 360; w += 10) {
        tester.view.physicalSize = Size(w, 700);
        tester.view.devicePixelRatio = 1;
        await tester.pumpWidget(_app(SkyLayer(clock: c)));
      }
      tester.view.reset();
      expect(SkyFrames.held, lessThanOrEqualTo(3));
      expect(tester.takeException(), isNull);
    });
  });
}
