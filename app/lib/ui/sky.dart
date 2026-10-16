// v3.3 流光壁纸（用户 10-15：随时间变化，夜里暗蓝紫灰、白天亮，柔和流动，且不能卡）。
// 一个片元着色器（shaders/sky.frag）整屏画一次：底色竖向渐变 + 三团柔光慢速漂移；颜色来自 tokens.dart SkyTable（按钟点插值）。
// 成本：自身是重绘边界，只有这一层按 SkyClock（≈30 帧/秒）重画，上面的内容不重建、不重绘；着色器每像素 3 次 exp。
// 回退（着色器没加载好 / 测试环境）：同色的竖向 LinearGradient，不闪。
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'motion.dart';

class SkyShader {
  static ui.FragmentProgram? program;
  static Future<void>? _loading;

  static void ensureLoaded() {
    if (SkyClock.frozen || _loading != null) return;
    _loading = ui.FragmentProgram.fromAsset('shaders/sky.frag').then((p) => program = p).catchError((_) => null);
  }
}

/// 整屏壁纸。fade != null 时只画上沿渐隐条（clear 以上不透明，到 solid 透明）。
class SkyLayer extends StatefulWidget {
  const SkyLayer({super.key, this.child, this.fade});
  final Widget? child;
  final (double clear, double solid)? fade;

  @override
  State<SkyLayer> createState() => _SkyLayerState();
}

class _SkyLayerState extends State<SkyLayer> {
  final _clock = SkyClock.instance;
  bool _animate = false;

  @override
  void initState() {
    super.initState();
    SkyShader.ensureLoaded();
    _clock.hour.addListener(_rebuild);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final want = TickerMode.valuesOf(context).enabled && !MediaQuery.disableAnimationsOf(context);
    if (want != _animate) {
      _animate = want;
      want ? _clock.acquire() : _clock.release();
    }
  }

  void _rebuild() => setState(() {});

  @override
  void dispose() {
    _clock.hour.removeListener(_rebuild);
    if (_animate) _clock.release();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final phase = p.sky.at(_clock.hour.value);
    return CustomPaint(
      isComplex: true,
      painter: _SkyPainter(phase: phase, time: _clock.time, screen: MediaQuery.sizeOf(context), fade: widget.fade, context: context),
      child: widget.child ?? const SizedBox.expand(),
    );
  }
}

class _SkyPainter extends CustomPainter {
  _SkyPainter({required this.phase, required this.time, required this.screen, required this.fade, required this.context}) : super(repaint: time);
  final SkyPhase phase;
  final ValueNotifier<double> time;
  final Size screen;
  final (double, double)? fade;
  final BuildContext context;

  @override
  void paint(Canvas canvas, Size size) {
    final ro = context.findRenderObject();
    final origin = ro is RenderBox && ro.attached && ro.hasSize ? ro.localToGlobal(Offset.zero) : Offset.zero;
    final rect = Offset.zero & size;
    final program = SkyShader.program;
    if (program != null && screen.height > 0) {
      final s = program.fragmentShader();
      var i = 0;
      void f(double v) => s.setFloat(i++, v);
      void c(Color x) {
        f(x.r);
        f(x.g);
        f(x.b);
      }
      f(size.width);
      f(size.height);
      f(origin.dx);
      f(origin.dy);
      f(screen.width);
      f(screen.height);
      f(time.value);
      for (final x in phase.colors) {
        c(x);
      }
      f(fade == null ? 0 : 1);
      f(fade?.$1 ?? 0);
      f(fade?.$2 ?? 0);
      canvas.drawRect(rect, Paint()..shader = s);
      return;
    }
    // 回退：同色竖向渐变（按 Sky.ramp 取 5 个色标，与着色器底色一致）
    final h = screen.height <= 0 ? size.height : screen.height;
    const n = 5;
    final colors = <Color>[], stops = <double>[];
    for (var k = 0; k < n; k++) {
      final y = k / (n - 1);
      final sy = (origin.dy + y * size.height) / h;
      var col = Color.lerp(phase.top, phase.bottom, Sky.ramp(sy))!;
      if (fade != null) col = col.withValues(alpha: Sky.fadeAlpha(origin.dy + y * size.height, fade!.$1, fade!.$2));
      colors.add(col);
      stops.add(y);
    }
    canvas.drawRect(rect, Paint()..shader = LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: colors, stops: stops).createShader(rect));
  }

  @override
  bool shouldRepaint(_SkyPainter old) => old.phase != phase || old.screen != screen || old.fade != fade;
}
