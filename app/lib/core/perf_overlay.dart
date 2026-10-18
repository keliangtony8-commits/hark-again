// 隐藏的性能浮层（v3.5.2，jank 诊断方案 8）：“我的 → 关于”连点“版本”行 5 次切换 MaterialApp.showPerformanceOverlay，
// 再连点 5 次关掉。只存本机（SharedPreferences），重启保留。不提升性能，只是让用户能截到 UI / Raster 两条柱。
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

class PerfOverlayNotifier extends AsyncNotifier<bool> {
  static const key = 'perf_overlay';

  @override
  Future<bool> build() async => (await SharedPreferences.getInstance()).getBool(key) ?? false;

  /// 切换并落盘，返回切换后的状态。
  Future<bool> toggle() async {
    final on = !(state.value ?? false);
    state = AsyncData(on);
    await (await SharedPreferences.getInstance()).setBool(key, on);
    return on;
  }
}

final perfOverlayProvider = AsyncNotifierProvider<PerfOverlayNotifier, bool>(PerfOverlayNotifier.new);

/// 连点计数：两次点击间隔超过 [gap] 重新数，数到 [taps] 次触发一次并清零。
/// 用 Timer 计间隔（不读 DateTime.now），测试里的假时钟也对。用完 [dispose]。
class TapStreak {
  TapStreak({this.taps = 5, this.gap = const Duration(milliseconds: 800)});
  final int taps;
  final Duration gap;
  int _count = 0;
  Timer? _reset;

  /// 记一次点击；凑满 [taps] 次返回 true。
  bool tap() {
    _reset?.cancel();
    if (++_count >= taps) {
      _count = 0;
      _reset = null;
      return true;
    }
    _reset = Timer(gap, () => _count = 0);
    return false;
  }

  void dispose() => _reset?.cancel();
}
