// v3.3 B3 卡顿根因的帧成本守门（用户 10-16：16GB 手机也卡；不准删功能 / 效果）。
// flutter test 没有真 GPU 光栅，这里量的是能在沙盒里稳定复现的那几项，跑在真实的 App（AssistantApp + 路由 + 外壳）上：
//   - 聊天流式：每个 delta 一帧，重建了多少个元素、除最后一条以外的消息行重建了几次（应为 0）；
//   - 毛玻璃：场景里 BackdropFilterLayer 有几层、要“取背景”几次（无 key 的每层一次 + 每个共享 key 一次）；
//   - 离屏遮罩：ShaderMaskLayer 层数（原 TopFade 整页 dstIn）；
//   - 一级页面滚动：每帧重建元素数；
//   - “我的”页滚动（v3.4 顶部渐隐）：每帧重建元素数、渐隐条不跟着滚动重建、毛玻璃取背景次数、无 ShaderMask；
//   - CPU 侧 build + layout + paint + 合成的耗时中位数（测试引擎，只作相对比较）。
// 数字打印出来（flutter test test/perf_frame_test.dart -r expanded 可见），断言只卡住“不能退回去”的那几条。
import 'dart:math' as math;

import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/features/computer/computer_screen.dart';
import 'package:assistant/features/computer/computer_section.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_controller_test.dart' show FakeSocket;
import 'support/computer_usage_fixture.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

final _t0 = DateTime.now().subtract(const Duration(hours: 1));

List<dynamic> _history(int n) => [
      for (var i = 0; i < n; i++)
        {
          'id': 'm$i',
          'role': i.isEven ? 'user' : 'assistant',
          'created_at': _t0.add(Duration(seconds: i)).toUtc().toIso8601String(),
          'blocks': [
            {
              'type': 'text',
              'text': i.isEven ? '第 $i 个问题：明天怎么安排？' : '## 第 $i 条回复\n\n- **八点** 出发，带上 `证件`\n- 路上约 *40 分钟*\n\n> 记得提前查天气。\n\n普通的一段说明文字，长一点，好占满一行再换行，像真实的回复那样。',
            }
          ],
        }
    ];

class _Api implements Api {
  _Api(this.messages);
  final List<dynamic> messages;
  int computerCalls = 0;
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    // v3.5.1 我的电脑 / 用量页滚动用例：每次轮询 CPU 和运行时长都变（= 真机上每 5 秒一次的样子）
    if (path == '/api/projects/me/computer') {
      computerCalls++;
      return computerFixture(cpu: 20.0 + computerCalls % 30, tick: computerCalls * 5);
    }
    if (path == '/api/browser/sessions') return browserSessionsFixture();
    if (path == '/api/host') return hostFixture();
    if (path == '/api/usage') return usageFixture();
    if (path.startsWith('/api/usage/days/')) return usageDayFixture();
    if (path.startsWith('/api/conversations/c1')) return {'id': 'c1', 'messages': messages};
    if (path == '/api/profile') {
      return {'username': 'keliang', 'display_name': null, 'assistant_name': null, 'assistant_default': 'Toyuis', 'avatar': null, 'greet': false};
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

typedef _App = ({ProviderContainer container, FakeSocket socket, GoRouter router});

Future<_App> _pump(WidgetTester tester, {int history = 30}) async {
  tester.view.physicalSize = const Size(412, 915);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final socket = FakeSocket();
  final container = ProviderContainer(overrides: [
    sessionProvider.overrideWith(_SignedIn.new),
    apiProvider.overrideWithValue(_Api(_history(history))),
    chatSocketProvider.overrideWithValue(socket),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AssistantApp()));
  await _settle(tester);
  return (container: container, socket: socket, router: container.read(routerProvider));
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// 场景里的层：毛玻璃层数、要取背景的次数（无 key 每层一次，同 key 合并一次）、ShaderMask 离屏层数、透明度层数。
({int backdrops, int flips, int shaderMasks, int opacity}) _layers(WidgetTester tester) {
  var backdrops = 0, unkeyed = 0, masks = 0, opacity = 0;
  final keys = <BackdropKey>{};
  void walk(Layer? l) {
    while (l != null) {
      if (l is BackdropFilterLayer) {
        backdrops++;
        final k = l.backdropKey;
        if (k == null) {
          unkeyed++;
        } else {
          keys.add(k);
        }
      }
      if (l is ShaderMaskLayer) masks++;
      if (l is OpacityLayer) opacity++;
      if (l is ContainerLayer) walk(l.firstChild);
      l = l.nextSibling;
    }
  }

  walk(tester.binding.renderViews.first.debugLayer);
  return (backdrops: backdrops, flips: unkeyed + keys.length, shaderMasks: masks, opacity: opacity);
}

/// 一帧里重建了哪些元素（Element.rebuild 的调试钩子，只在 debug 下有）。
class _Rebuilds {
  int total = 0;
  final rows = <String, int>{}; // MessageView 按消息 id

  void start() {
    debugOnRebuildDirtyWidget = (e, _) {
      total++;
      final w = e.widget;
      if (w is MessageView) rows[w.message.id] = (rows[w.message.id] ?? 0) + 1;
    };
  }

  void stop() => debugOnRebuildDirtyWidget = null;
}

double _median(List<int> xs) {
  final s = [...xs]..sort();
  return s.isEmpty ? 0 : s[s.length ~/ 2] / 1000.0;
}

void _report(String name, Map<String, Object> m) {
  // ignore: avoid_print
  print('[perf] $name ${m.entries.map((e) => '${e.key}=${e.value}').join(' ')}');
}

/// 场景里的层（细分）：PictureLayer（每块单独录制的画）、ClipRRect / ClipRect / ClipPath 层、透明度层、毛玻璃层与取背景次数。
Map<String, int> _layerCensus(WidgetTester tester) {
  final m = <String, int>{'picture': 0, 'clip': 0, 'opacity': 0, 'backdrop': 0, 'shaderMask': 0, 'total': 0};
  final keys = <BackdropKey>{};
  var unkeyed = 0;
  void walk(Layer? l) {
    while (l != null) {
      m['total'] = m['total']! + 1;
      if (l is PictureLayer) m['picture'] = m['picture']! + 1;
      if (l is ClipRRectLayer || l is ClipRectLayer || l is ClipPathLayer) m['clip'] = m['clip']! + 1;
      if (l is OpacityLayer) m['opacity'] = m['opacity']! + 1;
      if (l is ShaderMaskLayer) m['shaderMask'] = m['shaderMask']! + 1;
      if (l is BackdropFilterLayer) {
        m['backdrop'] = m['backdrop']! + 1;
        if (l.backdropKey == null) {
          unkeyed++;
        } else {
          keys.add(l.backdropKey!);
        }
      }
      if (l is ContainerLayer) walk(l.firstChild);
      l = l.nextSibling;
    }
  }

  walk(tester.binding.renderViews.first.debugLayer);
  m['flips'] = unkeyed + keys.length;
  return m;
}

int _elementCount(WidgetTester tester) {
  var n = 0;
  void visit(Element e) {
    n++;
    e.visitChildren(visit);
  }

  tester.binding.rootElement!.visitChildren(visit);
  return n;
}

/// 一页的滚动成本（v3.5.1 我的电脑 / 用量页）：滚 40 帧（缓起缓停，一路往下），每帧重建元素、paintChild 次数、CPU；
/// 再空闲 30 帧（只有页里的循环动画在走）看每帧重画；最后 [poll] 给了就模拟一次轮询到新数据，那一帧重建多少元素。
Future<Map<String, Object>> _scrollCost(WidgetTester tester, Finder scrollable, {Future<void> Function()? poll}) async {
  final layers = _layerCensus(tester);
  final elements = _elementCount(tester);
  final r = _Rebuilds()..start();
  var paints = 0;
  debugOnProfilePaint = (o) => paints++;
  final times = <int>[], perFrame = <int>[], paintFrame = <int>[];
  final pos = tester.state<ScrollableState>(scrollable).position;
  final gesture = await tester.startGesture(tester.getCenter(scrollable));
  for (var i = 0; i < 60; i++) {
    final before = r.total, p0 = paints;
    await gesture.moveBy(Offset(0, -36.0 * math.sin((i + 1) / 61 * math.pi))); // 一路往下约 1400px（≈ 一次中速连续滑动）
    final sw = Stopwatch()..start();
    await tester.pump(const Duration(milliseconds: 16));
    times.add(sw.elapsedMicroseconds);
    perFrame.add(r.total - before);
    paintFrame.add(paints - p0);
  }
  await gesture.up();
  final scrolled = pos.pixels;
  await _settle(tester);
  final idle = <int>[], idleBuild = <int>[];
  for (var i = 0; i < 30; i++) {
    final p0 = paints, b0 = r.total;
    await tester.pump(const Duration(milliseconds: 16));
    idle.add(paints - p0);
    idleBuild.add(r.total - b0);
  }
  var pollRebuilds = -1, pollPaints = -1, pollFrames = 0;
  if (poll != null) {
    await tester.runAsync(poll);
    // 轮询到新数据后 600ms（38 帧）：一共重建多少元素、有几帧在重建（换数字的淡入淡出 / 进度条过渡会拖出一串动画帧）
    final b0 = r.total, p0 = paints;
    for (var i = 0; i < 38; i++) {
      final b1 = r.total;
      await tester.pump(const Duration(milliseconds: 16));
      if (r.total > b1) pollFrames++;
    }
    pollRebuilds = r.total - b0;
    pollPaints = paints - p0;
    await _settle(tester);
  }
  debugOnProfilePaint = null;
  r.stop();
  int med(List<int> xs) => (xs..sort())[xs.length ~/ 2];
  int p90(List<int> xs) => (xs..sort())[(xs.length * 0.9).floor()];
  final cpuSorted = [...times]..sort();
  return {
    'scrolledPx': scrolled.round(),
    'maxScrollPx': pos.maxScrollExtent.round(),
    'elementsInTree': elements,
    'elementsPerFrame(median)': med(perFrame),
    'elementsPerFrame(p90)': p90(perFrame),
    'elementsPerFrame(max)': perFrame.reduce(math.max),
    'elementsTotal': perFrame.fold<int>(0, (a, b) => a + b),
    'paintsPerFrame(median)': med(paintFrame),
    'cpuMsPerFrame(median)': _median(times).toStringAsFixed(2),
    'cpuMsPerFrame(p90)': (cpuSorted[(cpuSorted.length * 0.9).floor()] / 1000).toStringAsFixed(2),
    'idlePaintsPerFrame(median)': med(idle),
    'idleBuildsPerFrame(median)': med(idleBuild),
    'pollRebuilds': pollRebuilds,
    'pollPaints': pollPaints,
    'pollBusyFrames': pollFrames,
    ...{for (final e in layers.entries) 'layers.${e.key}': e.value},
  };
}

void main() {
  testWidgets('聊天流式：每个 delta 只重建最后一条；毛玻璃取背景次数与离屏层', (tester) async {
    final app = await _pump(tester);
    app.router.go('/chat');
    await _settle(tester);
    final ctl = app.container.read(chatProvider('').notifier);
    await ctl.open('c1');
    await _settle(tester);

    ctl.send('再说一遍');
    await tester.pump();
    for (final e in [
      {'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u-new', 'title': ''},
      {'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': ''}},
    ]) {
      app.socket.ctl.add(e);
    }
    await _settle(tester);
    // 刚发出的那条有 1 秒“往上弹”窗口（按真实时钟）：等它过去，免得窗口结束那一下的正常重建算进流式里
    await tester.runAsync(() => Future<void>.delayed(Motion.sendFresh));
    app.socket.ctl.add({'type': 'block.delta', 'index': 0, 'text': '开头。'}); // 预热一帧：窗口结束后的那次重建发生在这里
    await tester.pump(const Duration(milliseconds: 16));

    final layers = _layers(tester);
    final r = _Rebuilds()..start();
    final times = <int>[];
    const n = 40;
    final perFrame = <int>[];
    for (var i = 0; i < n; i++) {
      final before = r.total;
      app.socket.ctl.add({'type': 'block.delta', 'index': 0, 'text': '第$i段，'});
      final sw = Stopwatch()..start();
      await tester.pump(const Duration(milliseconds: 16));
      times.add(sw.elapsedMicroseconds);
      perFrame.add(r.total - before);
    }
    r.stop();

    final pendingId = app.container.read(chatProvider('')).messages.last.id;
    final others = {for (final e in r.rows.entries) if (e.key != pendingId) e.key: e.value};
    final otherRebuilds = others.values.fold(0, (a, b) => a + b);
    _report('chat-stream', {
      'frames': n,
      'elementsPerFrame(median)': (perFrame..sort())[n ~/ 2],
      'otherRowRebuilds': otherRebuilds,
      'otherRows': others,
      'lastRowRebuilds': r.rows[pendingId] ?? 0,
      'cpuMsPerFrame(median)': _median(times).toStringAsFixed(2),
      'backdropLayers': layers.backdrops,
      'backdropFlips': layers.flips,
      'shaderMaskLayers': layers.shaderMasks,
      'opacityLayers': layers.opacity,
    });
    expect(otherRebuilds, 0, reason: '流式时除最后一条外的消息行不应重建：$others');
    expect(r.rows[pendingId] ?? 0, greaterThan(0));
    expect(layers.shaderMasks, 0, reason: '一级页面不再有整页 ShaderMask 离屏层');
    expect(layers.flips, lessThanOrEqualTo(2), reason: '顶栏组 + 输入组：每帧最多取两次背景');
  });

  testWidgets('一级页面滚动：每帧重建元素数、离屏层', (tester) async {
    final app = await _pump(tester, history: 60);
    app.router.go('/chat');
    await _settle(tester);
    await app.container.read(chatProvider('').notifier).open('c1');
    await _settle(tester);

    final layers = _layers(tester);
    final r = _Rebuilds()..start();
    final times = <int>[];
    final perFrame = <int>[];
    final list = find.byType(Scrollable).first;
    final gesture = await tester.startGesture(tester.getCenter(list));
    for (var i = 0; i < 30; i++) {
      final before = r.total;
      await gesture.moveBy(Offset(0, 12.0 * math.cos(i / 30 * math.pi))); // 往上翻看历史（reverse 列表，手指往下拖）
      final sw = Stopwatch()..start();
      await tester.pump(const Duration(milliseconds: 16));
      times.add(sw.elapsedMicroseconds);
      perFrame.add(r.total - before);
    }
    await gesture.up();
    r.stop();
    await _settle(tester);
    _report('shell-scroll', {
      'frames': 30,
      'elementsPerFrame(median)': (perFrame..sort())[15],
      'cpuMsPerFrame(median)': _median(times).toStringAsFixed(2),
      'backdropLayers': layers.backdrops,
      'backdropFlips': layers.flips,
      'shaderMaskLayers': layers.shaderMasks,
    });
    expect(layers.shaderMasks, 0);
  });

  testWidgets('“我的”页滚动：顶部渐隐条不随滚动重建、不加离屏层', (tester) async {
    final app = await _pump(tester);
    app.router.go('/me');
    await _settle(tester);

    final layers = _layers(tester);
    final r = _Rebuilds()..start();
    var fadeRebuilds = 0;
    final hook = debugOnRebuildDirtyWidget!;
    debugOnRebuildDirtyWidget = (e, b) {
      hook(e, b);
      if (e.widget.key == const Key('me-fade')) fadeRebuilds++;
    };
    final times = <int>[];
    final perFrame = <int>[];
    final list = find.descendant(of: find.byType(MeScreen), matching: find.byType(Scrollable)).first;
    final pos = tester.state<ScrollableState>(list).position;
    final gesture = await tester.startGesture(tester.getCenter(list));
    for (var i = 0; i < 30; i++) {
      final before = r.total;
      await gesture.moveBy(Offset(0, -12.0 * math.sin((i + 1) / 31 * math.pi))); // 一路往下翻（缓起缓停），假接口下内容不长，会翻到底
      final sw = Stopwatch()..start();
      await tester.pump(const Duration(milliseconds: 16));
      times.add(sw.elapsedMicroseconds);
      perFrame.add(r.total - before);
    }
    await gesture.up();
    r.stop();
    await _settle(tester);
    _report('me-scroll', {
      'frames': 30,
      'elementsPerFrame(median)': (perFrame..sort())[15],
      'cpuMsPerFrame(median)': _median(times).toStringAsFixed(2),
      'backdropLayers': layers.backdrops,
      'backdropFlips': layers.flips,
      'shaderMaskLayers': layers.shaderMasks,
      'fadeRebuilds': fadeRebuilds,
    });
    expect(pos.pixels, greaterThan(50), reason: '确实翻下去了');
    expect(find.byKey(const Key('me-fade')), findsOneWidget);
    expect(fadeRebuilds, 0, reason: '渐隐条在列表外，滚动不应重建它');
    expect(layers.shaderMasks, 0);
  });

  testWidgets('主页 / 项目页：毛玻璃取背景次数', (tester) async {
    final app = await _pump(tester);
    final home = _layers(tester);
    app.router.go('/projects');
    await _settle(tester);
    final projects = _layers(tester);
    _report('glass', {
      'home.backdropLayers': home.backdrops,
      'home.flips': home.flips,
      'home.shaderMasks': home.shaderMasks,
      'projects.backdropLayers': projects.backdrops,
      'projects.flips': projects.flips,
      'projects.shaderMasks': projects.shaderMasks,
    });
    expect(home.shaderMasks + projects.shaderMasks, 0);
    expect(home.flips, lessThanOrEqualTo(2));
    expect(projects.flips, lessThanOrEqualTo(2));
    expect(kDebugMode, isTrue); // 重建计数依赖 debug 钩子
  });

  testWidgets('v3.5.1 我的电脑：滚动 / 空闲 / 轮询的帧成本', (tester) async {
    final app = await _pump(tester);
    app.router.push('/me/computer');
    await _settle(tester);
    final list = find.descendant(of: find.byType(ComputerScreen), matching: find.byType(Scrollable)).first;
    final m = await _scrollCost(tester, list,
        poll: () => app.container.read(computerProvider('me').notifier).reload());
    _report('computer-scroll', m);
    expect(m['layers.shaderMask'], 0);
  });

  testWidgets('v3.5.1 用量与花费：滚动 / 空闲的帧成本', (tester) async {
    final app = await _pump(tester);
    app.router.push('/me/usage');
    await _settle(tester);
    final list = find.descendant(of: find.byType(UsageScreen), matching: find.byType(Scrollable)).first;
    final m = await _scrollCost(tester, list, poll: () => app.container.read(usageProvider.notifier).reload());
    _report('usage-scroll', m);
    expect(m['layers.shaderMask'], 0);
  });

}
