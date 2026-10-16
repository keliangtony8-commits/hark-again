// 全 App 唯一的“先给旧数据、后台再拉新的”（stale-while-revalidate）机制。v3.3 起所有读服务器的页面都走这里。
// 规则（= Web lib/swr.ts，两端一致）：
//  1. 第一次没有数据才显示骨架；之后再进页面（切 Tab、进子页面、返回）**首帧就是上次的数据**，后台静默重取，变了才换。
//  2. 有数据时后台出错 → 继续显示旧数据，不打扰；没数据时出错 → 页面显示“加载失败 + 重试”。
//  3. 缓存存服务器原样 JSON（模型不用写 toJson）：内存一份（SwrCache，有上限），给了 diskKey 的再落盘（core/cache.dart，冷启动也秒开）。
//     保险箱、钱包、两步验证、登录设备这类安全相关的**不给 diskKey**，只在内存。
//  4. 换服务器 / 退出登录 → SwrCache 整个换新（swrCacheProvider 跟着会话走）；磁盘由 SessionNotifier.signOut 清。
// 用法：只读资源一行 `swrGet` / `swrGetFamily`；带增删改的继承 SwrNotifier（列表资源见 core/resource.dart）。
// 页面渲染统一用 `value.swr(loading:, error:, data:)`，不要用 isLoading 判断骨架（下拉刷新时 isLoading 也为真）。
// 参考：Vercel SWR（MIT）、TanStack Query 的公开文档（只学做法，没有移植代码）。
import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show AsyncNotifierProviderFamily;

import 'api.dart';
import 'cache.dart';
import 'session.dart';

/// 进程内缓存：键 = 请求路径，值 = 服务器原样 JSON。最近最少用的先丢，最多 [max] 条。
class SwrCache {
  SwrCache({this.max = 64});
  final int max;
  final _m = <String, Object?>{}; // 字面量 Map 即 LinkedHashMap：按插入顺序

  bool has(String key) => _m.containsKey(key);

  Object? read(String key) {
    if (!_m.containsKey(key)) return null;
    final v = _m.remove(key);
    _m[key] = v; // 挪到最新
    return v;
  }

  void write(String key, Object? raw) {
    _m.remove(key);
    _m[key] = raw;
    while (_m.length > max) {
      _m.remove(_m.keys.first);
    }
  }

  void remove(String key) => _m.remove(key);
  void clear() => _m.clear();
  int get length => _m.length;
}

/// 跟着“服务器 + 是否登录”走：换服务器、退出、重新登录都会得到一份空缓存（换人看不到上一个人的数据）。
final swrCacheProvider = Provider<SwrCache>((ref) {
  ref.watch(sessionProvider.select((s) => (s.value?.server, s.value?.signedIn)));
  return SwrCache();
});

abstract class SwrNotifier<T> extends AsyncNotifier<T> {
  /// GET 的路径，也是内存缓存的键。
  String get path;

  /// 给了就落盘（冷启动秒开）；安全相关的数据保持 null。
  String? get diskKey => null;

  /// 为真：没登录不发请求，直接给 [signedOutValue]（会话还在读时保持加载中）。
  bool get requiresSession => false;
  T get signedOutValue => throw StateError('$runtimeType 需要 signedOutValue');

  /// 服务器 JSON → 状态。
  T parse(Object? raw);

  /// 默认 GET [path]；要兜底（老服务器没有这个接口 → null）的覆盖它。
  Future<Object?> fetch() => ref.read(apiProvider).get(path);

  Object? _raw;

  /// 当前状态对应的原样 JSON（增删改在它上面算新列表，再 [emit]）。
  Object? get raw => _raw;

  SwrCache get _mem => ref.read(swrCacheProvider);

  @override
  FutureOr<T> build() {
    if (requiresSession) {
      // 只看“读完没有 / 登没登录”：换发 token（退出其他设备、开两步验证）不重建、不闪旧数据
      final (ready, signedIn) = ref.watch(sessionProvider.select((s) => (s.hasValue, s.value?.signedIn ?? false)));
      if (!ready) return Completer<T>().future; // 会话读完会重建
      if (!signedIn) return signedOutValue;
    }
    final mem = _mem;
    if (mem.has(path)) {
      _raw = mem.read(path);
      _revalidateSoon();
      return parse(_raw); // 同步返回：首帧就是旧数据，不经过加载态
    }
    return _cold();
  }

  Future<T> _cold() async {
    final r = ref;
    final dk = diskKey;
    if (dk != null) {
      final disk = await ref.read(cacheStoreProvider).read(dk);
      if (disk != null && r.mounted) {
        _raw = disk;
        _mem.write(path, disk);
        _revalidateSoon();
        return parse(disk);
      }
    }
    final raw = await fetch();
    if (r.mounted) _store(raw);
    return parse(raw);
  }

  void _revalidateSoon() {
    final r = ref;
    Future.microtask(() async {
      try {
        final raw = await fetch();
        if (r.mounted) emit(raw);
      } catch (_) {} // 有数据时出错：保留旧数据，不打扰
    });
  }

  void _store(Object? raw) {
    _raw = raw;
    _mem.write(path, raw);
    final dk = diskKey;
    if (dk != null) unawaited(ref.read(cacheStoreProvider).write(dk, raw));
  }

  /// 新的原样 JSON → 缓存 + 状态。和当前一样就不发新状态（不白白重建、不重播动画）。
  void emit(Object? raw) {
    if (state.hasValue && _same(raw, _raw)) return;
    _store(raw);
    state = AsyncData(parse(raw));
  }

  static bool _same(Object? a, Object? b) {
    if (identical(a, b)) return true;
    try {
      return jsonEncode(a) == jsonEncode(b);
    } catch (_) {
      return false;
    }
  }

  /// 乐观改了 state（先从列表拿掉一行）之后调：后台把缓存也对齐服务器，下次进页面不会闪回旧行。
  void resync() => unawaited(reload().catchError((_) {}));

  /// 重取一次（下拉刷新、轮询、改完后同步）。有数据时失败保留旧数据不抛；没数据时把错误抛给调用方。
  Future<void> reload() async {
    final r = ref;
    try {
      final raw = await fetch();
      if (r.mounted) emit(raw);
    } catch (e) {
      if (!state.hasValue) rethrow;
    }
  }
}

/// 只读资源的通用实现：路径 + 解析函数。
class SwrGet<T> extends SwrNotifier<T> {
  SwrGet(this.path, this._parse, {this.diskKey, this.requiresSession = false, this.orNull = false});
  @override
  final String path;
  @override
  final String? diskKey;
  @override
  final bool requiresSession;

  /// 为真：请求失败（老服务器没有接口、断网）当作 null，不显示错误（T 必须可空）。
  final bool orNull;
  final T Function(Object? raw) _parse;

  @override
  T get signedOutValue => null as T;

  @override
  Future<Object?> fetch() async {
    if (!orNull) return super.fetch();
    try {
      return await super.fetch();
    } catch (_) {
      return null;
    }
  }

  @override
  T parse(Object? raw) => _parse(raw);
}

typedef SwrProvider<T> = AsyncNotifierProvider<SwrGet<T>, T>;
typedef SwrFamily<T, A> = AsyncNotifierProviderFamily<SwrGet<T>, T, A>;

/// 页面级只读资源：离开页面 provider 释放，数据留在 SwrCache，回来秒开。
SwrProvider<T> swrGet<T>(String path, T Function(Object? raw) parse,
        {String? diskKey, bool requiresSession = false, bool orNull = false}) =>
    AsyncNotifierProvider.autoDispose<SwrGet<T>, T>(
        () => SwrGet<T>(path, parse, diskKey: diskKey, requiresSession: requiresSession, orNull: orNull));

/// 按参数区分的只读资源（对话 id、日期…）：每个参数一条缓存。
SwrFamily<T, A> swrGetFamily<T, A>(String Function(A arg) path, T Function(Object? raw) parse) =>
    AsyncNotifierProvider.autoDispose.family<SwrGet<T>, T, A>((a) => SwrGet<T>(path(a), parse));

/// 解析一个 JSON 对象（常用）。
Map<String, dynamic> jsonMap(Object? raw) => (raw as Map).cast<String, dynamic>();

extension SwrView<T> on AsyncValue<T> {
  /// 有数据就显示数据（后台刷新中、刷新失败都不打扰）；没数据才骨架 / 出错。
  R swr<R>({required R Function() loading, required R Function(Object error) error, required R Function(T value) data}) =>
      hasValue ? data(value as T) : (hasError ? error(this.error!) : loading());
}
