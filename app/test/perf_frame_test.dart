// v3.3 B3 卡顿根因的帧成本守门（用户 10-16：16GB 手机也卡；不准删功能 / 效果）。
// flutter test 没有真 GPU 光栅，这里量的是能在沙盒里稳定复现的那几项，跑在真实的 App（AssistantApp + 路由 + 外壳）上：
//   - 聊天流式：每个 delta 一帧，重建了多少个元素、除最后一条以外的消息行重建了几次（应为 0）；
//   - 毛玻璃：场景里 BackdropFilterLayer 有几层、要“取背景”几次（无 key 的每层一次 + 每个共享 key 一次）；
//   - 离屏遮罩：ShaderMaskLayer 层数（原 TopFade 整页 dstIn）；
//   - 一级页面滚动：每帧重建元素数；
//   - “我的”页滚动（v3.4 顶部渐隐）：每帧重建元素数、渐隐条不跟着滚动重建、毛玻璃取背景次数、无 ShaderMask；
//   - CPU 侧 build + layout + paint + 合成的耗时中位数（测试引擎，只作相对比较）；
//   - 壁纸着色器（v3.5.1）：真着色器整屏 412×915 光栅一帧（测试引擎是软件光栅，比真机 GPU 慢几个数量级，只作新旧相对比较）。
// 数字打印出来（flutter test test/perf_frame_test.dart -r expanded 可见），断言只卡住“不能退回去”的那几条。
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/perf_probe.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/features/computer/computer_screen.dart';
import 'package:assistant/features/computer/computer_section.dart';
import 'package:assistant/features/home/home_screen.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/features/projects/projects_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/motion.dart';
import 'package:assistant/ui/sky.dart';
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
    final at = _t0.toUtc().toIso8601String();
    if (path == '/api/cards') {
      // 主页滚动用：几张面板卡（关键数字小块 + 文字），够翻一屏多
      return [
        for (var i = 0; i < 8; i++)
          {'id': 'p$i', 'kind': 'panel', 'title': '面板 $i', 'dismissed': false, 'unread': false, 'updated_at': at,
            'blocks': [
              {'type': 'stats', 'items': [{'label': '中间价', 'value': '7.12$i', 'note': '比昨天 −0.02%'}, {'label': '一周', 'value': '7.13–7.15'}]},
              {'type': 'text', 'text': '第 $i 张面板的说明文字，长一点，占两行左右，像真实的面板那样。'},
            ]},
      ];
    }
    if (path == '/api/projects') {
      return [for (var i = 0; i < 24; i++) {'id': 'w$i', 'name': '项目 $i：一个名字稍长一点的项目', 'updated_at': at, 'last_active_at': at, 'status': i % 3 == 0 ? 'running' : 'done'}];
    }
    if (path == '/api/usage') return {'currency': 'CNY', 'priced': [], 'today': {}, 'month': {'tokens': 3100000, 'calls': 420}};
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
({int backdrops, int flips, int shaderMasks, int opacity, int clips, int pictures}) _layers(WidgetTester tester) {
  var backdrops = 0, unkeyed = 0, masks = 0, opacity = 0, clips = 0, pictures = 0;
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
      if (l is ClipRRectLayer || l is ClipRectLayer || l is ClipPathLayer) clips++;
      if (l is PictureLayer) pictures++;
      if (l is ContainerLayer) walk(l.firstChild);
      l = l.nextSibling;
    }
  }

  walk(tester.binding.renderViews.first.debugLayer);
  return (backdrops: backdrops, flips: unkeyed + keys.length, shaderMasks: masks, opacity: opacity, clips: clips, pictures: pictures);
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

/// 一帧里真正重画（重新录制绘制指令）的 RenderObject 个数：干净的重绘边界直接复用、不算（= PaintingContext.paintChild 的判断）。
/// 只在 debug 下有（debugOnProfilePaint）。types 记下重画最多的类型，用来找“滚动时谁在跟着重画”。
class _Repaints {
  int total = 0;
  final types = <String, int>{};

  void start() {
    debugOnProfilePaint = (ro) {
      if (ro.isRepaintBoundary && !ro.debugNeedsPaint) return;
      total++;
      final t = ro.runtimeType.toString();
      types[t] = (types[t] ?? 0) + 1;
    };
  }

  void stop() => debugOnProfilePaint = null;

  String top([int n = 6]) {
    final e = types.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
    return e.take(n).map((x) => '${x.key}:${x.value}').join(',');
  }
}

double _median(List<int> xs) {
  final s = [...xs]..sort();
  return s.isEmpty ? 0 : s[s.length ~/ 2] / 1000.0;
}

void _report(String name, Map<String, Object> m) {
  // ignore: avoid_print
  print('[perf] $name ${m.entries.map((e) => '${e.key}=${e.value}').join(' ')}');
}

/// 拖着 [list] 滚 30 帧（缓起缓停，dy 每帧最多 12），量：每帧重建元素数、每帧重画的 RenderObject 数（+ 类型分布）、CPU 每帧耗时中位数，
/// 以及滚动中那一帧的合成层（毛玻璃 / 取背景次数 / ShaderMask / Opacity / Clip / Picture）。
Future<Map<String, Object>> _scroll(WidgetTester tester, Finder list, {double dir = -1, void Function(Element)? onRebuild}) async {
  final r = _Rebuilds()..start();
  if (onRebuild != null) {
    final hook = debugOnRebuildDirtyWidget!;
    debugOnRebuildDirtyWidget = (e, b) {
      hook(e, b);
      onRebuild(e);
    };
  }
  final rp = _Repaints()..start();
  final times = <int>[], perFrame = <int>[], paints = <int>[];
  final gesture = await tester.startGesture(tester.getCenter(list));
  ({int backdrops, int flips, int shaderMasks, int opacity, int clips, int pictures})? mid;
  for (var i = 0; i < 30; i++) {
    final before = r.total, pb = rp.total;
    await gesture.moveBy(Offset(0, dir * 12.0 * math.sin((i + 1) / 31 * math.pi)));
    final sw = Stopwatch()..start();
    await tester.pump(const Duration(milliseconds: 16));
    times.add(sw.elapsedMicroseconds);
    perFrame.add(r.total - before);
    paints.add(rp.total - pb);
    if (i == 15) mid = _layers(tester);
  }
  await gesture.up();
  r.stop();
  rp.stop();
  await _settle(tester);
  final l = mid!;
  return {
    'elementsPerFrame(median)': (perFrame..sort())[15],
    'repaintsPerFrame(median)': (paints..sort())[15],
    'repaintTypes': rp.top(),
    'cpuMsPerFrame(median)': _median(times).toStringAsFixed(2),
    'backdropLayers': l.backdrops,
    'backdropFlips': l.flips,
    'shaderMaskLayers': l.shaderMasks,
    'opacityLayers': l.opacity,
    'clipLayers': l.clips,
    'pictureLayers': l.pictures,
  };
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

    final list = find.byType(Scrollable).first;
    final m = await _scroll(tester, list, dir: 1); // 往上翻看历史（reverse 列表，手指往下拖）
    _report('shell-scroll', m);
    expect(m['shaderMaskLayers'], 0);
  });

  testWidgets('“我的”页滚动（v3.5.1 第四个分支，顶栏常驻）：渐隐条不随滚动重建、不加离屏层、取背景次数不超', (tester) async {
    final app = await _pump(tester);
    app.router.go('/me');
    await _settle(tester);

    var fadeRebuilds = 0;
    final list = find.descendant(of: find.byType(MeScreen), matching: find.byType(Scrollable)).first;
    final pos = tester.state<ScrollableState>(list).position;
    final m = await _scroll(tester, list, onRebuild: (e) {
      if (e.widget is BackdropFade) fadeRebuilds++; // v3.5.1 渐隐条由 ShellPage 出（和其他一级页面同一个）
    });
    _report('me-scroll', {...m, 'fadeRebuilds': fadeRebuilds});
    expect(pos.pixels, greaterThan(50), reason: '确实翻下去了');
    expect(fadeRebuilds, 0, reason: '渐隐条在列表外，滚动不应重建它');
    expect(m['shaderMaskLayers'], 0);
    expect(m['backdropFlips'] as int, lessThanOrEqualTo(2), reason: '顶栏组 + 内容组（搜索胶囊）：每帧最多取两次背景');
  });

  testWidgets('主页 / 项目列表滚动：每帧重画、合成层', (tester) async {
    final app = await _pump(tester);
    await _settle(tester);
    final home = find.descendant(of: find.byType(HomeScreen), matching: find.byType(Scrollable)).first;
    final hm = await _scroll(tester, home);
    _report('home-scroll', hm);
    app.router.go('/projects');
    await _settle(tester);
    final projects = find.descendant(of: find.byType(ProjectsScreen), matching: find.byType(Scrollable)).first;
    final pm = await _scroll(tester, projects);
    _report('projects-scroll', pm);
    expect(hm['shaderMaskLayers'], 0);
    expect(pm['shaderMaskLayers'], 0);
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

  testWidgets('壁纸着色器：整屏光栅一帧的耗时（新旧相对比较）', (tester) async {
    tester.view.physicalSize = const Size(412, 915);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final prog = await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky.frag'));
    final blit = await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky_blit.frag'));
    addTearDown(() => SkyShader.program = SkyShader.blit = null);
    addTearDown(SkyFrames.clear);
    final clock = SkyClock.forTest(frozen: true);
    await tester.pumpWidget(MaterialApp(theme: buildTheme(Brightness.light), home: SkyLayer(clock: clock)));
    final boundary = tester.renderObject<RenderRepaintBoundary>(find.descendant(of: find.byType(SkyLayer), matching: find.byType(RepaintBoundary)));
    final paint = tester.renderObject<RenderCustomPaint>(find.descendant(of: find.byType(SkyLayer), matching: find.byType(CustomPaint)));
    // step = 时钟走了一步（v3.5.2 要重画低分辨率图）；same = 时钟没走、只是重光栅（Impeller 滑动帧：没有 raster cache，每帧重放）
    Future<String> measure({required bool step}) async {
      final times = <int>[];
      for (var i = 0; i < 12; i++) {
        if (step || i == 0) {
          clock.time.value = 7.0 + i * 1.3;
        } else {
          paint.markNeedsPaint();
        }
        await tester.pump();
        await tester.runAsync(() async {
          final sw = Stopwatch()..start();
          final img = await boundary.toImage();
          await img.toByteData(); // 等它真画完
          times.add(sw.elapsedMicroseconds);
          img.dispose();
        });
      }
      return _median(times.sublist(2)).toStringAsFixed(2);
    }

    SkyShader.program = prog;
    SkyShader.blit = null;
    final direct = await measure(step: true);
    SkyShader.blit = blit;
    final renders0 = SkyFrames.renders;
    final stepped = await measure(step: true);
    final renders1 = SkyFrames.renders;
    final same = await measure(step: false);
    _report('sky-shader', {
      'frames': 10,
      'direct(v3.5.1) rasterMsPerFrame(median)': direct,
      'lowres clock-step rasterMsPerFrame(median)': stepped,
      'lowres same-step(scroll) rasterMsPerFrame(median)': same,
    });
    expect(renders1 - renders0, 12); // 每个时钟步一张
    expect(SkyFrames.renders - renders1, 1); // 时钟不走：只有第一帧换步，其余复用
    expect(SkyFrames.held, 1);
    expect(tester.takeException(), isNull);
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

  // v3.5.3 性能自检的沙盒参考：同样 A–H，在“我的”页上整屏软件光栅（OffsetLayer.toImage，含真壁纸着色器 + 低分辨率贴图 + 模糊）。
  // 软件光栅（Skia CPU）和真机 Impeller-GPU 的成本结构不同，只看相对大小；真机数字以 App 内自检为准。
  testWidgets('v3.5.3 性能自检 A–H：“我的”页整屏软件光栅（只作参考）', (tester) async {
    final prog = await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky.frag'));
    final blit = await tester.runAsync(() => ui.FragmentProgram.fromAsset('shaders/sky_blit.frag'));
    SkyShader.program = prog;
    SkyShader.blit = blit;
    SkyShader.loaded.value++;
    addTearDown(() => SkyShader.program = SkyShader.blit = null);
    addTearDown(SkyFrames.clear);
    addTearDown(() => PerfProbe.restore(rebuild: false));
    final app = await _pump(tester);
    app.router.go('/me');
    await _settle(tester);
    final list = find.descendant(of: find.byType(MeScreen), matching: find.byType(Scrollable)).first;
    final pos = tester.state<ScrollableState>(list).position;
    final root = tester.binding.renderViews.first;
    final rect = Offset.zero & root.size;
    final out = <String, Object>{'extent': pos.maxScrollExtent.round()};
    double? base;
    for (final v in PerfVariant.values) {
      PerfProbe.apply(v);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      final times = <int>[];
      for (var i = 0; i < 14; i++) {
        pos.jumpTo(pos.maxScrollExtent * (0.5 + 0.5 * math.sin(i / 3)));
        await tester.pump(const Duration(milliseconds: 8));
        final layer = root.debugLayer! as OffsetLayer;
        await tester.runAsync(() async {
          final sw = Stopwatch()..start();
          final img = await layer.toImage(rect);
          await img.toByteData();
          times.add(sw.elapsedMicroseconds);
          img.dispose();
        });
      }
      final med = _median(times.sublist(2));
      base ??= med;
      out[v.code] = '${med.toStringAsFixed(2)}ms(${(med / base * 100).round()}%)';
    }
    PerfProbe.restore();
    await tester.pump();
    _report('perf-probe-sandbox', out);
    expect(PerfProbe.flags, PerfFlags.all);
    expect(tester.takeException(), isNull);
  });

}
