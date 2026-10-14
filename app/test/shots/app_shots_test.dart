// App 截图（v2.78）：真字体（文泉驿正黑 = 中文 + 拉丁，MaterialIcons 来自 Flutter SDK）把整个 App 外壳画成 PNG，
// 对照 Hark 截图自查。默认跳过；要出图：
//   SHOTS_DIR=/tmp/shots/app CJK_FONT=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc flutter test test/shots/app_shots_test.dart
// 出：home-light / home-dark / home-end-light / new-panel-light / chat-drawer-light（手机 412×915 逻辑像素，2.625 倍）。
import 'dart:io';
import 'dart:ui' as ui;

import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../chat_controller_test.dart' show FakeSocket;

final _out = Platform.environment['SHOTS_DIR'];
final _cjk = Platform.environment['CJK_FONT'] ?? '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

String _wire(DateTime t) => t.toUtc().toIso8601String();

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    final now = DateTime.now();
    final today8 = DateTime(now.year, now.month, now.day, 8);
    if (path == '/api/inbox') return {'unread': 1, 'latest': null};
    if (path == '/api/cards') {
      return [
        {'id': 'p1', 'kind': 'panel', 'task_id': 't7', 'title': '美元兑人民币', 'dismissed': false, 'unread': false, 'updated_at': _wire(today8),
          'blocks': [{'type': 'stats', 'items': [{'label': '中间价', 'value': '7.1268', 'note': '比昨天 −0.02%'}, {'label': '一周', 'value': '7.13–7.15'}]}]},
        {'id': 'r1', 'kind': 'report', 'conversation_id': 'c1', 'task_id': 't2', 'title': '早间简报', 'dismissed': false, 'unread': true,
          'headline': '两节课', 'gist': '下午 3 点交实验报告。', 'blocks': [{'type': 'text', 'text': '今天有两节课。'}], 'updated_at': _wire(today8)},
        {'id': 'x1', 'kind': 'panel', 'title': '上海天气', 'dismissed': true, 'revivable': true, 'removed_at': _wire(today8), 'blocks': [], 'updated_at': _wire(today8)},
      ];
    }
    if (path == '/api/tasks') {
      return [
        {'id': 't2', 'name': '早间简报', 'prompt': '帮我准备今天', 'cron': '0 8 * * *', 'active': true, 'output': 'report',
          'run_requested': false, 'last_run_at': _wire(today8), 'last_status': 'ok'},
        {'id': 't3', 'name': '晚间复盘', 'prompt': '复盘', 'cron': '30 23 * * *', 'active': true, 'output': 'report', 'run_requested': false},
        {'id': 't7', 'name': '美元兑人民币', 'prompt': '汇率', 'cron': '0 8 * * *', 'active': true, 'output': 'panel', 'run_requested': false},
      ];
    }
    if (path == '/api/conversations/c2') {
      final at = now.subtract(const Duration(minutes: 3));
      Map<String, dynamic> step(String id, String title, String detail, int ms, int sec) =>
          {'id': id, 'tool': 'run_command', 'title': title, 'detail': detail, 'state': 'done', 'at': _wire(at.add(Duration(seconds: sec))), 'ms': ms};
      return {'id': 'c2', 'messages': [
        for (var i = 0; i < 6; i++) ...[
          {'id': 'u$i', 'role': 'user', 'created_at': _wire(at), 'blocks': [{'type': 'text', 'text': '第 $i 个问题：这款耳机降噪怎么样？'}]},
          {'id': 'a$i', 'role': 'assistant', 'created_at': _wire(at), 'blocks': [{'type': 'text', 'text': '索尼 WH-1000XM5 的降噪在同价位里最强，地铁里基本听不到报站。\n\n续航 30 小时，京东今天 ¥1899。'}],
            if (i == 5) 'steps': [step('s1', '搜索', '索尼 XM5 价格', 2400, 0), step('s2', '打开网页', 'item.jd.com/100012', 3100, 3), step('s3', '读文件', 'notes/耳机.md', 12, 7)]},
        ],
      ]};
    }
    if (path.startsWith('/api/conversations')) {
      return [
        {'id': 'c1', 'title': '早间简报', 'updated_at': _wire(today8), 'created_at': _wire(today8)},
        {'id': 'c2', 'title': '帮我比价降噪耳机', 'updated_at': _wire(today8), 'created_at': _wire(today8)},
      ];
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _font(String family, String path) async {
  final loader = FontLoader(family)..addFont(Future.value(ByteData.sublistView(File(path).readAsBytesSync())));
  await loader.load();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _shot(WidgetTester tester, String name) async {
  final ro = tester.binding.renderViews.first.child!;
  // 根渲染对象没有 layer 时找第一个有 layer 的 RepaintBoundary
  RenderRepaintBoundary? b;
  void find(RenderObject o) {
    if (b != null) return;
    if (o is RenderRepaintBoundary && o.debugLayer != null) {
      b = o;
      return;
    }
    o.visitChildren(find);
  }

  find(ro);
  await tester.runAsync(() async {
    final img = await b!.toImage(pixelRatio: 2.625);
    final png = await img.toByteData(format: ui.ImageByteFormat.png);
    File('$_out/$name.png').writeAsBytesSync(png!.buffer.asUint8List());
  });
}

late ProviderContainer _container;

Future<GoRouter> _pump(WidgetTester tester, {required bool dark}) async {
  tester.view.physicalSize = const Size(412, 915);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.platformBrightnessTestValue = dark ? Brightness.dark : Brightness.light;
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
  SharedPreferences.setMockInitialValues({});
  final container = ProviderContainer(overrides: [
    sessionProvider.overrideWith(_SignedIn.new),
    apiProvider.overrideWithValue(_Api()),
    chatSocketProvider.overrideWithValue(FakeSocket()),
  ]);
  addTearDown(container.dispose);
  _container = container;
  await tester.pumpWidget(RepaintBoundary(child: UncontrolledProviderScope(container: container, child: const AssistantApp())));
  await _settle(tester);
  await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 300))); // 假接口/缓存是真异步
  await _settle(tester);
  return container.read(routerProvider);
}

void main() {
  setUpAll(() async {
    if (_out == null) return;
    Directory(_out!).createSync(recursive: true);
    for (final f in ['Roboto', 'serif', 'Noto Serif CJK SC']) {
      await _font(f, _cjk);
    }
    await _font('MaterialIcons', '${Platform.environment['FLUTTER_ROOT'] ?? '/tmp/flutter'}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf');
  });

  testWidgets('home light + new panel sheet + end', (tester) async {
    await _pump(tester, dark: false);
    await _shot(tester, 'home-light');
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -900));
    await _settle(tester);
    await _shot(tester, 'home-end-light');
    await tester.tap(find.byTooltip('新建面板'));
    await _settle(tester);
    await _shot(tester, 'new-panel-light');
  }, skip: _out == null);

  testWidgets('home dark', (tester) async {
    await _pump(tester, dark: true);
    await _shot(tester, 'home-dark');
  }, skip: _out == null);

  testWidgets('chat history drawer', (tester) async {
    final router = await _pump(tester, dark: false);
    router.go('/chat');
    await _settle(tester);
    await tester.tap(find.byTooltip('历史').first);
    await _settle(tester);
    await _shot(tester, 'chat-drawer-light');
  }, skip: _out == null);

  // v2.79：步骤收成一行（不到 1 秒不写用时）+ 往上翻出现“回到最新”
  testWidgets('chat steps + jump latest', (tester) async {
    final router = await _pump(tester, dark: false);
    router.go('/chat');
    await _settle(tester);
    await tester.runAsync(() => _container.read(chatProvider('').notifier).open('c2'));
    await _settle(tester);
    await _shot(tester, 'chat-steps-light');
    await tester.tap(find.textContaining('做了 3 步'));
    await _settle(tester);
    await _shot(tester, 'chat-steps-open-light');
    await tester.drag(find.byType(ListView).first, const Offset(0, 700));
    await _settle(tester);
    await _shot(tester, 'chat-jump-latest-light');
  }, skip: _out == null);
}
