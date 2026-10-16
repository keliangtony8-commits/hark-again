// v3.3 SWR（core/swr.dart）：二次进入首帧就是上次的数据（不出骨架）/ 后台重取后替换 / 有缓存时出错仍显示旧数据 /
// 没缓存时出错才报错 / 退出登录清空缓存 / LRU 上限 / orNull 取不到给 null。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/core/swr.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Session extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://me.example', token: 't');

  @override
  Future<void> signOut() async => state = const AsyncData(Session(server: 'https://me.example'));
}

class _Api implements Api {
  int n = 0;
  bool fail = false;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add(path);
    if (fail) throw ApiError("服务器出错", 500);
    n++;
    return {'v': 'v$n'};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

final _thing = swrGet<String>('/api/thing', (raw) => jsonMap(raw)['v'] as String);
final _safe = swrGet<String?>('/api/version', (raw) => jsonMap(raw)['v'] as String, orNull: true);

ProviderContainer _container(_Api api) {
  final c = ProviderContainer(
    overrides: [sessionProvider.overrideWith(_Session.new), apiProvider.overrideWithValue(api)],
    retry: (_, _) => null, // 不让 Riverpod 自动重试干扰计数
  );
  addTearDown(c.dispose);
  return c;
}

/// 订阅一次 → 等数据 → 取消订阅（= 进页面再离开，autoDispose 释放 provider，数据留在 SwrCache）。
Future<void> _visit(ProviderContainer c, SwrProvider<String> p, Future<String> Function() future) async {
  final sub = c.listen(p, (_, _) {});
  await future();
  sub.close();
  await pumpEventQueue();
}

void main() {
  group('SwrNotifier', () {
    test('二次进入：同步给上次的数据（不经过加载态），后台重取后换成新数据', () async {
      final api = _Api();
      final c = _container(api);
      await _visit(c, _thing, () => c.read(_thing.future));
      expect(api.calls, ['/api/thing']);

      final seen = <AsyncValue<String>>[];
      final sub = c.listen(_thing, (_, v) => seen.add(v), fireImmediately: true);
      addTearDown(sub.close);
      expect(seen.first.isLoading, isFalse, reason: '首帧不能是加载态（骨架）');
      expect(seen.first.value, 'v1');

      await pumpEventQueue();
      expect(api.calls, ['/api/thing', '/api/thing'], reason: '后台重取一次');
      expect(c.read(_thing).value, 'v2');
    });

    test('数据没变不发新状态（不白白重建）', () async {
      final api = _Api();
      final c = _container(api);
      await _visit(c, _thing, () => c.read(_thing.future));
      api.n = 0; // 下一次仍返回 v1
      var changes = 0;
      final sub = c.listen(_thing, (_, _) => changes++);
      addTearDown(sub.close);
      await pumpEventQueue();
      expect(api.calls.length, 2);
      expect(changes, 0);
    });

    test('有缓存时后台出错：继续显示旧数据，不变成错误；reload 失败也不抛', () async {
      final api = _Api();
      final c = _container(api);
      await _visit(c, _thing, () => c.read(_thing.future));
      api.fail = true;
      final sub = c.listen(_thing, (_, _) {});
      addTearDown(sub.close);
      await pumpEventQueue();
      expect(c.read(_thing).hasError, isFalse);
      expect(c.read(_thing).value, 'v1');
      await c.read(_thing.notifier).reload(); // 下拉刷新失败：有数据就静默
      expect(c.read(_thing).value, 'v1');
    });

    test('没有缓存时出错：显示错误（页面给“加载失败 + 重试”）', () async {
      final api = _Api()..fail = true;
      final c = _container(api);
      final sub = c.listen(_thing, (_, _) {});
      addTearDown(sub.close);
      await pumpEventQueue();
      expect(c.read(_thing).hasError, isTrue);
      await expectLater(c.read(_thing.notifier).reload(), throwsA(isA<ApiError>()));
    });

    test('退出登录：缓存整个换新，再进页面重新请求', () async {
      final api = _Api();
      final c = _container(api);
      await _visit(c, _thing, () => c.read(_thing.future));
      final before = c.read(swrCacheProvider);
      expect(before.has('/api/thing'), isTrue);

      await c.read(sessionProvider.notifier).signOut();
      final after = c.read(swrCacheProvider);
      expect(identical(before, after), isFalse);
      expect(after.length, 0);

      final sub = c.listen(_thing, (_, _) {});
      addTearDown(sub.close);
      expect(c.read(_thing).isLoading, isTrue, reason: '换人后不能看到上一个人的数据');
    });

    test('orNull：接口取不到给 null，不报错', () async {
      final api = _Api()..fail = true;
      final c = _container(api);
      final sub = c.listen(_safe, (_, _) {});
      addTearDown(sub.close);
      expect(await c.read(_safe.future), isNull);
      expect(c.read(_safe).hasError, isFalse);
    });
  });

  test('SwrCache：最近最少用的先丢，读一次算“用过”', () {
    final m = SwrCache(max: 2);
    m.write('a', 1);
    m.write('b', 2);
    m.read('a');
    m.write('c', 3);
    expect([m.has('a'), m.has('b'), m.has('c')], [true, false, true]);
    expect(m.length, 2);
  });

  group('AsyncValue.swr', () {
    String view(AsyncValue<int> v) => v.swr(loading: () => 'skeleton', error: (_) => 'error', data: (x) => 'data $x');
    test('没数据：加载中 → 骨架、出错 → 错误；有数据 → 数据（刷新中 / 刷新失败由上面的 SwrNotifier 用例守）', () {
      expect(view(const AsyncLoading<int>()), 'skeleton');
      expect(view(AsyncError<int>('x', StackTrace.empty)), 'error');
      expect(view(const AsyncData(1)), 'data 1');
    });
  });

  testWidgets('页面：第一次进骨架，离开再进首帧就是内容', (tester) async {
    final api = _Api();
    final show = ValueNotifier(true);
    await tester.pumpWidget(ProviderScope(
      overrides: [sessionProvider.overrideWith(_Session.new), apiProvider.overrideWithValue(api)],
      retry: (_, _) => null,
      child: MaterialApp(
        home: ValueListenableBuilder<bool>(
          valueListenable: show,
          builder: (_, s, _) => s ? const _Page() : const SizedBox(),
        ),
      ),
    ));
    expect(find.text('骨架'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.text('v1'), findsOneWidget);

    show.value = false; // 离开页面
    await tester.pumpAndSettle();
    expect(find.byType(_Page), findsNothing);

    show.value = true; // 再进来：同一帧就是上次的内容
    await tester.pump();
    expect(find.text('骨架'), findsNothing);
    expect(find.text('v1'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.text('v2'), findsOneWidget, reason: '后台重取后静默替换');
  });
}

class _Page extends ConsumerWidget {
  const _Page();
  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      Text(ref.watch(_thing).swr(loading: () => '骨架', error: (e) => '出错', data: (v) => v));
}
