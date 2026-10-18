// v3.3 流光壁纸（用户 10-15：随时间变化，夜里暗蓝紫灰、白天亮，柔和流动，且不能卡）。
// 一个片元着色器（shaders/sky.frag）整屏画一次：底色竖向渐变 + 五团柔光流动（漂移 + 旋转 + 伸缩，颜色在五个色相间轮转，v3.5.1）；
// 颜色来自 tokens.dart SkyTable（按钟点插值），每团的位置 / 形状 / 此刻颜色在画笔里每帧算一次（Sky.blobs、SkyPhase.hue）。
// 成本：自身是重绘边界，只有这一层按 SkyClock（≈30 帧/秒）重画，上面的内容不重建、不重绘；着色器每像素 5 次 exp（原 3 次）。
// 被盖住（不可见路由 / 后台 Tab / 外壳分支里的不透明子页进场完成后，见 SkyCover）：退订时钟、画笔不听时钟，恢复时直接取此刻（v3.3 B4）。
// 回退（着色器没加载好 / 测试环境）：同色的竖向 LinearGradient，不闪。
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'motion.dart';

class SkyShader {
  static ui.FragmentProgram? program;
  static Future<void>? _loading;

  /// 着色器加载完成时 +1：静止（减少动态）的壁纸也会立刻从回退渐变换成着色器。
  static final ValueNotifier<int> loaded = ValueNotifier(0);

  static void ensureLoaded() {
    if (SkyClock.inTest || _loading != null) return;
    _loading = ui.FragmentProgram.fromAsset('shaders/sky.frag').then<void>((p) {
      program = p;
      loaded.value++;
    }, onError: (Object _) {}); // 加载失败：一直用回退渐变
  }
}

/// 整屏壁纸（自身是重绘边界：每帧只有这一层重画）。fade != null 时只画上沿渐隐条（clear 以上不透明，到 solid 透明）。
/// 不驱动（不可见 / 被盖住）时画笔不听时钟：哪怕别的层还在让 SkyClock 走，这一层也不重画；恢复时重画一次，直接取时钟此刻的天色和柔光位置。
class SkyLayer extends StatefulWidget {
  const SkyLayer({super.key, this.fade, this.fadeLocal = false, this.clock, this.coverable = false});
  final (double clear, double solid)? fade;

  /// [fade] 是条自身的本地 y（底部浮条下的渐隐条，位置随布局变；画时加上条在屏幕上的位置）。默认是屏幕 y（上沿条从屏幕顶开始）。
  final bool fadeLocal;

  /// 测试注入；默认全 App 共用的 SkyClock.instance。
  final SkyClock? clock;

  /// 外壳那一层（ui/glass.dart Backdrop(coverable)）：上方 [SkyCoverScope] 报“被不透明子页完全盖住”时暂停。
  final bool coverable;

  @override
  State<SkyLayer> createState() => SkyLayerState();
}

enum _Drive { none, still, animate }

/// 画笔的重画信号：只在驱动时转发时钟（time / hour）的变化；从暂停回到驱动时补发一次。
class _SkyGate extends ChangeNotifier {
  _SkyGate(this.clock) {
    clock.time.addListener(_tick);
    clock.hour.addListener(_tick);
  }
  final SkyClock clock;
  bool _live = false;

  set live(bool v) {
    if (v == _live) return;
    _live = v;
    if (v) notifyListeners(); // 恢复：重画成此刻
  }

  void _tick() {
    if (_live) notifyListeners();
  }

  @override
  void dispose() {
    clock.time.removeListener(_tick);
    clock.hour.removeListener(_tick);
    super.dispose();
  }
}

class SkyLayerState extends State<SkyLayer> {
  late final SkyClock _clock = widget.clock ?? SkyClock.instance;
  late final _SkyGate _gate = _SkyGate(_clock);
  late final Listenable _repaint = Listenable.merge([_gate, SkyShader.loaded]);
  _Drive _drive = _Drive.none;
  _Drive _want = _Drive.none;
  ValueListenable<int>? _covers;

  /// 测试用：这一层此刻在不在跟着时钟走（订阅 SkyClock + 画笔听时钟）。
  @visibleForTesting
  bool get driving => _drive != _Drive.none;

  @override
  void initState() {
    super.initState();
    SkyShader.ensureLoaded();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 不可见（被盖住的路由、后台 Tab）不订阅；减少动态只订阅“换天色”，不漂移
    _want = !TickerMode.valuesOf(context).enabled
        ? _Drive.none
        : MediaQuery.disableAnimationsOf(context)
            ? _Drive.still
            : _Drive.animate;
    final covers = widget.coverable ? SkyCoverScope.coversOf(context) : null;
    if (covers != _covers) {
      _covers?.removeListener(_apply);
      _covers = covers;
      covers?.addListener(_apply);
    }
    _apply();
  }

  /// 不 setState：盖住计数可能在别处 build 期间变化，这里只换时钟订阅档和画笔开关（markNeedsPaint），不碰构建。
  void _apply() {
    final d = (_covers?.value ?? 0) > 0 ? _Drive.none : _want;
    if (d == _drive) return;
    if (_drive != _Drive.none) _clock.release(animate: _drive == _Drive.animate);
    _drive = d;
    if (d != _Drive.none) _clock.acquire(animate: d == _Drive.animate);
    _gate.live = d != _Drive.none;
  }

  @override
  void dispose() {
    _covers?.removeListener(_apply);
    _want = _Drive.none;
    _covers = null;
    _apply();
    _gate.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return RepaintBoundary(
      child: CustomPaint(
        painter: _SkyPainter(sky: p.sky, clock: _clock, repaint: _repaint, screen: MediaQuery.sizeOf(context), fade: widget.fade, fadeLocal: widget.fadeLocal, context: context),
        child: const SizedBox.expand(),
      ),
    );
  }
}

/// 外壳的“被盖住”计数（app_shell.dart 挂在外壳最外层）：外壳分支里的不透明子页（SubPage → [SkyCover]）进场完成后 +1，
/// 开始退场 / 不在台上时 −1；计数 > 0 时外壳那层壁纸（SkyLayer(coverable: true)）暂停。
class SkyCoverScope extends StatefulWidget {
  const SkyCoverScope({super.key, required this.child});
  final Widget child;

  /// 不建立依赖：计数变了不重建任何人，只通知监听者。
  static ValueNotifier<int>? coversOf(BuildContext context) => context.getInheritedWidgetOfExactType<_SkyCoverScope>()?.covers;

  @override
  State<SkyCoverScope> createState() => _SkyCoverScopeState();
}

class _SkyCoverScopeState extends State<SkyCoverScope> {
  final _covers = ValueNotifier<int>(0);

  @override
  void dispose() {
    _covers.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => _SkyCoverScope(covers: _covers, child: widget.child);
}

class _SkyCoverScope extends InheritedWidget {
  const _SkyCoverScope({required this.covers, required super.child});
  final ValueNotifier<int> covers;

  @override
  bool updateShouldNotify(_SkyCoverScope old) => covers != old.covers;
}

/// 包住一张自带不透明壁纸的整页（SubPage）：语义同 Flutter `TransitionRoute.opaque`——不透明路由进场转场完成后，下面的东西看不见了。
/// 报“盖住”的条件：本页路由 opaque、进场动画 completed、本页在台上（TickerMode 开：不在后台分支、没被更上面的页盖成 offstage）。
/// 转场中、返回手势 / pop 一开始（status 离开 completed）立刻撤销，外壳壁纸在这一帧之前就恢复。没有 [SkyCoverScope]（根导航器上的页）时什么也不做。
class SkyCover extends StatefulWidget {
  const SkyCover({super.key, required this.child});
  final Widget child;

  @override
  State<SkyCover> createState() => _SkyCoverState();
}

class _SkyCoverState extends State<SkyCover> {
  ValueNotifier<int>? _scope;
  ModalRoute<Object?>? _route;
  bool _onstage = false, _on = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final scope = SkyCoverScope.coversOf(context);
    if (scope != _scope) {
      _set(false);
      _scope = scope;
    }
    final route = ModalRoute.of(context);
    if (route != _route) {
      _route?.animation?.removeStatusListener(_onStatus);
      _route = route;
      route?.animation?.addStatusListener(_onStatus);
    }
    _onstage = TickerMode.valuesOf(context).enabled;
    _sync();
  }

  void _onStatus(AnimationStatus _) => _sync();

  void _sync() {
    final r = _route;
    _set(_scope != null && _onstage && r != null && r.opaque && (r.animation?.isCompleted ?? true));
  }

  void _set(bool on) {
    final scope = _scope;
    if (on == _on || scope == null) return;
    _on = on;
    scope.value += on ? 1 : -1;
  }

  @override
  void dispose() {
    _route?.animation?.removeStatusListener(_onStatus);
    _set(false);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

class _SkyPainter extends CustomPainter {
  _SkyPainter({required this.sky, required this.clock, required Listenable repaint, required this.screen, required this.fade, this.fadeLocal = false, required this.context}) : super(repaint: repaint);
  final SkyTable sky;
  final bool fadeLocal;
  final SkyClock clock;
  final Size screen;
  final (double, double)? fade;
  final BuildContext context;

  @override
  void paint(Canvas canvas, Size size) {
    final phase = sky.at(clock.hour.value);
    final time = clock.time;
    final ro = context.findRenderObject();
    final origin = ro is RenderBox && ro.attached && ro.hasSize ? ro.localToGlobal(Offset.zero) : Offset.zero;
    final rect = Offset.zero & size;
    final dy = fadeLocal ? origin.dy : 0.0;
    final fade = this.fade == null ? null : (this.fade!.$1 + dy, this.fade!.$2 + dy);
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
      f(fade == null ? 0 : 1);
      f(fade?.$1 ?? 0);
      f(fade?.$2 ?? 0);
      c(phase.top);
      c(phase.bottom);
      // 只跟时间有关的量每帧在这里算一次（5 团 × 几个 sin/cos），着色器每像素只做高斯
      final aspect = screen.width / screen.height;
      for (final b in Sky.blobs) {
        final at = b.at(time.value, aspect);
        f(at.x);
        f(at.y);
        // M = diag(kx, ky) · R(θ)：先转到这一团的方向，再按两条轴缩放
        f(at.kx * at.cos);
        f(at.kx * at.sin);
        f(-at.ky * at.sin);
        f(at.ky * at.cos);
        c(phase.hue(time.value / Sky.hueStep + b.hue));
        f(b.mix);
      }
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
      if (fade != null) col = col.withValues(alpha: Sky.fadeAlpha(origin.dy + y * size.height, fade.$1, fade.$2));
      colors.add(col);
      stops.add(y);
    }
    canvas.drawRect(rect, Paint()..shader = LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: colors, stops: stops).createShader(rect));
  }

  @override
  bool shouldRepaint(_SkyPainter old) => old.sky != sky || old.clock != clock || old.screen != screen || old.fade != fade || old.fadeLocal != fadeLocal;
}
