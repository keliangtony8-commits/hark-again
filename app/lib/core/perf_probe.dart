// v3.5.3 性能自检（真机分层测光栅）：用户魅族 20 在“我的”页滑动 Raster ≈ 16ms/帧（120Hz 预算 8.3ms），UI 只有 0.4ms。
// 沙盒没有真 GPU，只能在真机上逐层关掉再量：关于页（性能浮层打开时）“性能自检 ›” → 回到“我的”页，
// 用程序化滚动来回匀速滑，每个变体约 2.5 秒，SchedulerBinding.addTimingsCallback 收 FrameTiming，统计光栅 平均 / p90 / 最大 / >8.3ms 占比。
//
// 调试开关全在 [PerfProbe]：生产路径只读几个静态 bool（默认全开 = 现状），没有监听、没有额外部件；
// 切变体时把所有元素标脏重建一次（[PerfProbe.apply]），跑完 [PerfProbe.restore] 回到全开。
// 切换不改部件树结构（壁纸换成同位置的纯色、模糊只 enabled:false、渐隐条换成空盒），页面状态（滚动位置、输入框）不丢。
import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

/// 毛玻璃属于哪一块（只用来按块关模糊）：顶栏胶囊、“我的”底部搜索胶囊、其他（圆钮等）。
enum PerfBlur { topBar, search, other }

/// 一组层开关；默认全开 = 现状。
@immutable
class PerfFlags {
  const PerfFlags({this.wallpaper = true, this.blurTopBar = true, this.blurSearch = true, this.blurOther = true, this.fade = true, this.translucentCards = true});

  /// 流光壁纸（整屏 SkyLayer）；关 = 同位置画纯色底。
  final bool wallpaper;

  /// 顶栏分段胶囊的 BackdropFilter。
  final bool blurTopBar;

  /// “我的”底部搜索胶囊的 BackdropFilter。
  final bool blurSearch;

  /// 其余 GlassSurface(blur)（左上 / 返回 / 右上圆钮等）的 BackdropFilter。
  final bool blurOther;

  /// 上 / 下渐隐条（BackdropFade）。
  final bool fade;

  /// 列表卡片半透明（p.card）；关 = 同色不透明。
  final bool translucentCards;

  static const all = PerfFlags();

  bool get isAll =>
      wallpaper && blurTopBar && blurSearch && blurOther && fade && translucentCards;

  bool blur(PerfBlur l) => switch (l) { PerfBlur.topBar => blurTopBar, PerfBlur.search => blurSearch, PerfBlur.other => blurOther };

  @override
  bool operator ==(Object other) =>
      other is PerfFlags &&
      other.wallpaper == wallpaper &&
      other.blurTopBar == blurTopBar &&
      other.blurSearch == blurSearch &&
      other.blurOther == blurOther &&
      other.fade == fade &&
      other.translucentCards == translucentCards;

  @override
  int get hashCode => Object.hash(wallpaper, blurTopBar, blurSearch, blurOther, fade, translucentCards);
}

/// 自检的变体：A 全开 … H 全关（B+C+F+G）。
enum PerfVariant {
  a('A', '全开（现状）', PerfFlags.all),
  b('B', '关壁纸（纯色底）', PerfFlags(wallpaper: false)),
  c('C', '关所有模糊', PerfFlags(blurTopBar: false, blurSearch: false, blurOther: false)),
  d('D', '只关顶栏模糊', PerfFlags(blurTopBar: false)),
  e('E', '只关搜索框模糊', PerfFlags(blurSearch: false)),
  f('F', '关渐隐条', PerfFlags(fade: false)),
  g('G', '卡片不透明', PerfFlags(translucentCards: false)),
  h('H', '全关（B+C+F+G）', PerfFlags(wallpaper: false, blurTopBar: false, blurSearch: false, blurOther: false, fade: false, translucentCards: false));

  const PerfVariant(this.code, this.label, this.flags);
  final String code, label;
  final PerfFlags flags;
}

/// 全局调试开关。生产路径：各层 build 里读 [flags] 的一个 bool，默认全开。
abstract final class PerfProbe {
  static PerfFlags _flags = PerfFlags.all;

  /// 此刻在跑的变体（null = 没在自检）。只给自检界面 / 测试看，生产部件不监听它。
  static final ValueNotifier<PerfVariant?> active = ValueNotifier(null);

  static PerfFlags get flags => _flags;

  /// 切到变体 [v] 并（默认）把所有元素标脏，下一帧按新开关重建。
  static void apply(PerfVariant v, {bool rebuild = true}) => _set(v.flags, v, rebuild);

  /// 回到全开（现状）。
  static void restore({bool rebuild = true}) => _set(PerfFlags.all, null, rebuild);

  static void _set(PerfFlags f, PerfVariant? v, bool rebuild) {
    final changed = f != _flags;
    _flags = f;
    active.value = v;
    if (changed && rebuild) rebuildAll();
  }

  /// 全树标脏（只在切变体时调一次）：开关是静态 bool，部件不监听，所以要这样让它们重新读。
  static void rebuildAll() {
    final root = WidgetsBinding.instance.rootElement;
    if (root == null) return;
    void mark(Element e) {
      e.markNeedsBuild();
      e.visitChildren(mark);
    }

    mark(root);
  }
}

/// 一个变体的统计（毫秒）。
@immutable
class PerfStats {
  const PerfStats({required this.frames, required this.rasterAvg, required this.rasterP90, required this.rasterMax, required this.overBudget, required this.buildAvg, required this.buildMax, this.fps, this.hzMin, this.hzMax});

  final int frames;
  final double rasterAvg, rasterP90, rasterMax;

  /// 光栅超预算（> [budgetMs]）的帧占比，0–1。
  final double overBudget;
  final double buildAvg, buildMax;

  /// v3.5.4 实测帧率 = 帧数 / 实际时长（秒）；没算时为 null。
  final double? fps;

  /// v3.5.4 滑动中每 200ms 采样的系统当前刷新率（display.mode.refreshRate）最低 / 最高；读不到为 null。
  final double? hzMin, hzMax;

  /// 补上实测帧率与刷新率采样（[durationUs] = 时间窗实际长度，微秒）。
  PerfStats withRate({required int durationUs, List<double> hz = const []}) => PerfStats(
        frames: frames,
        rasterAvg: rasterAvg,
        rasterP90: rasterP90,
        rasterMax: rasterMax,
        overBudget: overBudget,
        buildAvg: buildAvg,
        buildMax: buildMax,
        fps: durationUs > 0 ? frames * 1e6 / durationUs : null,
        hzMin: hz.isEmpty ? null : hz.reduce(math.min),
        hzMax: hz.isEmpty ? null : hz.reduce(math.max),
      );

  static const empty = PerfStats(frames: 0, rasterAvg: 0, rasterP90: 0, rasterMax: 0, overBudget: 0, buildAvg: 0, buildMax: 0);

  /// [raster] / [build] 每帧耗时（毫秒，一一对应或 build 为空）。p90 取最近秩（第 ceil(0.9n) 小）。
  static PerfStats of(List<double> raster, {List<double> build = const [], double budgetMs = 1000 / 120}) {
    if (raster.isEmpty) return empty;
    final s = [...raster]..sort();
    double avg(List<double> xs) => xs.isEmpty ? 0 : xs.reduce((a, b) => a + b) / xs.length;
    final p90 = s[math.max(0, (s.length * 0.9).ceil() - 1)];
    return PerfStats(
      frames: s.length,
      rasterAvg: avg(s),
      rasterP90: p90,
      rasterMax: s.last,
      overBudget: s.where((x) => x > budgetMs).length / s.length,
      buildAvg: avg(build),
      buildMax: build.isEmpty ? 0 : build.reduce(math.max),
    );
  }
}

/// 一帧的取样（毫秒；vsync 时间戳微秒，用来把帧归到变体的时间窗）。
typedef PerfSample = ({int vsyncUs, double rasterMs, double buildMs});

PerfSample sampleOf(ui.FrameTiming t) => (
      vsyncUs: t.timestampInMicroseconds(ui.FramePhase.vsyncStart),
      rasterMs: t.rasterDuration.inMicroseconds / 1000,
      buildMs: t.buildDuration.inMicroseconds / 1000,
    );

/// 只取 [startUs, endUs] 时间窗里的帧算统计。
PerfStats statsInWindow(List<PerfSample> all, int startUs, int endUs, {double budgetMs = 1000 / 120}) {
  final w = [for (final s in all) if (s.vsyncUs >= startUs && s.vsyncUs <= endUs) s];
  return PerfStats.of([for (final s in w) s.rasterMs], build: [for (final s in w) s.buildMs], budgetMs: budgetMs);
}

/// 帧耗时来源（默认 SchedulerBinding 的 timings 回调；测试注入假的）。
abstract class PerfTimingSource {
  void add(void Function(List<PerfSample>) onSamples);
  void remove();
}

class _BindingTimings implements PerfTimingSource {
  TimingsCallback? _cb;
  @override
  void add(void Function(List<PerfSample>) onSamples) {
    _cb = (ts) => onSamples([for (final t in ts) sampleOf(t)]);
    SchedulerBinding.instance.addTimingsCallback(_cb!);
  }

  @override
  void remove() {
    if (_cb != null) SchedulerBinding.instance.removeTimingsCallback(_cb!);
    _cb = null;
  }
}

/// v3.5.4 系统当前刷新率来源（默认 MethodChannel 读 display.mode.refreshRate；测试注入假的）。读不到返回 null。
abstract class PerfRateSource {
  Future<double?> sample();
}

class _ChannelRate implements PerfRateSource {
  @override
  Future<double?> sample() async {
    try {
      final v = await const MethodChannel('dev.assistant/perf').invokeMethod<num>('refreshRate');
      return v?.toDouble();
    } catch (_) {
      return null;
    }
  }
}

/// 自检结果：设备信息 + 每个变体一行。
class PerfReport {
  PerfReport({required this.device, required this.rows, required this.budgetMs, this.scrollExtent = 0, this.note});
  final Map<String, String> device;
  final List<(PerfVariant, PerfStats)> rows;
  final double budgetMs;
  final double scrollExtent;
  final String? note;
}

/// 跑一遍 A–H。[locate] 每个变体前找一次“我的”页的滚动位置（重建后对象可能换）。
class PerfProbeRunner {
  PerfProbeRunner({PerfTimingSource? timings, PerfRateSource? rates, this.perVariant = const Duration(milliseconds: 2500), this.settle = const Duration(milliseconds: 400), this.speed = 1500, this.rateEvery = const Duration(milliseconds: 200)})
      : timings = timings ?? _BindingTimings(),
        rates = rates ?? _ChannelRate();

  final PerfTimingSource timings;
  final PerfRateSource rates;

  /// 滑动中采样系统刷新率的间隔。
  final Duration rateEvery;
  final Duration perVariant, settle;

  /// 匀速滚动的速度（逻辑像素 / 秒）；页太短时每程至少 300ms。
  final double speed;

  /// 最近一次结果（结果页读它）。
  static PerfReport? last;
  static bool running = false;

  final _samples = <PerfSample>[];

  /// 当前帧的 vsync 时间戳（微秒）：在帧回调里读，和 FrameTiming 同一个时钟（引擎单调时钟）。
  static Future<int> _frameStamp() {
    final c = Completer<int>();
    SchedulerBinding.instance.addPostFrameCallback((_) => c.complete(SchedulerBinding.instance.currentSystemFrameTimeStamp.inMicroseconds));
    SchedulerBinding.instance.scheduleFrame();
    return c.future;
  }

  Future<PerfReport> run({required ScrollPosition? Function() locate, List<PerfVariant> variants = PerfVariant.values, Map<String, String> device = const {}, double? budgetMs}) async {
    final budget = budgetMs ?? 1000 / _refreshRate();
    running = true;
    final rows = <(PerfVariant, PerfStats)>[];
    var extent = 0.0;
    String? note;
    timings.add(_samples.addAll);
    try {
      for (final v in variants) {
        PerfProbe.apply(v);
        await Future<void>.delayed(settle); // 重建那一帧和它之后的稳定期不算
        final pos = locate();
        if (pos == null || !pos.hasContentDimensions) {
          note = '没找到“我的”页的滚动列表';
          rows.add((v, PerfStats.empty));
          continue;
        }
        if (pos.pixels != pos.minScrollExtent) pos.jumpTo(pos.minScrollExtent);
        await Future<void>.delayed(const Duration(milliseconds: 100));
        extent = pos.maxScrollExtent - pos.minScrollExtent;
        if (extent < 1) {
          note = '“我的”页在这块屏上不够长、滚不动，数字只反映静止重画';
        }
        final legMs = math.max(300, (extent / speed * 1000).round());
        final legs = math.max(2, (perVariant.inMilliseconds / legMs).round());
        final start = await _frameStamp();
        final hz = <double>[];
        void take() => rates.sample().then((v) {
              if (v != null && v.isFinite && v > 0) hz.add(v);
            });
        take();
        final ticker = Timer.periodic(rateEvery, (_) => take());
        for (var i = 0; i < legs; i++) {
          final to = i.isEven ? pos.maxScrollExtent : pos.minScrollExtent;
          if (extent < 1) {
            await Future<void>.delayed(Duration(milliseconds: legMs));
          } else {
            await pos.animateTo(to, duration: Duration(milliseconds: legMs), curve: Curves.linear);
          }
        }
        final end = await _frameStamp();
        ticker.cancel();
        // timings 是批量回来的（release 约每秒一批）：等到窗口末尾那帧到了再统计，最多等 2.5 秒
        for (var waited = 0; waited < 2500 && !_samples.any((s) => s.vsyncUs >= end); waited += 100) {
          await Future<void>.delayed(const Duration(milliseconds: 100));
        }
        rows.add((v, statsInWindow(_samples, start, end, budgetMs: budget).withRate(durationUs: end - start, hz: hz)));
      }
    } finally {
      timings.remove();
      PerfProbe.restore();
      running = false;
    }
    return last = PerfReport(device: device, rows: rows, budgetMs: budget, scrollExtent: extent, note: note);
  }

  static double _refreshRate() {
    final views = ui.PlatformDispatcher.instance.views;
    final hz = views.isEmpty ? 60.0 : views.first.display.refreshRate;
    return hz.isFinite && hz >= 30 ? hz : 60;
  }
}

/// [root] 下面第一个竖向、祖先里有 [T] 的 Scrollable 的位置（自检在“我的”页上滚）。
ScrollPosition? findScrollUnder<T extends Widget>(Element root) {
  ScrollPosition? found;
  void visit(Element e) {
    if (found != null) return;
    if (e is StatefulElement && e.state is ScrollableState) {
      final s = e.state as ScrollableState;
      if (s.widget.axis == Axis.vertical && e.findAncestorWidgetOfExactType<T>() != null) {
        found = s.position;
        return;
      }
    }
    e.visitChildren(visit);
  }

  visit(root);
  return found;
}

/// 设备与渲染信息（结果页顶部）。拿不到的写“未知”。
Future<Map<String, String>> perfDeviceInfo() async {
  final m = <String, String>{};
  final views = ui.PlatformDispatcher.instance.views;
  if (views.isNotEmpty) {
    final v = views.first;
    final d = v.display;
    m['Flutter 刷新率'] = '${d.refreshRate.toStringAsFixed(1)} Hz';
    m['设备像素比'] = v.devicePixelRatio.toStringAsFixed(2);
    m['分辨率'] = '${v.physicalSize.width.round()}×${v.physicalSize.height.round()}（逻辑 ${(v.physicalSize.width / v.devicePixelRatio).round()}×${(v.physicalSize.height / v.devicePixelRatio).round()}）';
  }
  m['Impeller'] = ui.ImageFilter.isShaderFilterSupported ? '已启用' : '未启用（Skia）';
  try {
    final r = await const MethodChannel('dev.assistant/perf').invokeMapMethod<String, Object?>('display');
    if (r != null) {
      String s(String k) => '${r[k] ?? '未知'}';
      m['系统当前模式'] = '${s('modeId')} · ${s('modeRefreshRate')} Hz · ${s('modeSize')}';
      m['窗口请求模式'] = '${s('preferredModeId')}（${s('preferredRefreshRate')} Hz）';
      m['窗口请求刷新率'] = '${s('windowRefreshRate')} Hz';
      m['Surface 帧率'] = s('surfaceFrameRate');
      m['可选模式'] = s('supported');
      m['Impeller 后端'] = s('impellerBackend');
      m['EnableImpeller'] = s('enableImpeller');
    }
  } catch (_) {
    m['系统当前模式'] = '未知（读不到 MainActivity）';
    m['Impeller 后端'] = '未知';
  }
  return m;
}
