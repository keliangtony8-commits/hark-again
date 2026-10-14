// 浏览器接管交还（v1.29 / v2.82）：models/browser_view.dart 规则 + BrowserBlock.handoff 解析 + 画面卡上的“需要你来”条
// （助手在等你 → 自动推出全屏接管页、完成/做不了回调 onForm 并关页、断线保留按钮、只读场景只显示说明不推页、结束后一行结果）
// + 只是看着 2 分钟后暂停、点一下继续 + 接管页手势（点、单指滚、长按拖、后退刷新、打字）发的请求 + 坐标换算。
import 'package:assistant/blocks/browser_block.dart';
import 'package:assistant/blocks/browser_takeover.dart';
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/browser_view.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeApi implements Api {
  final posts = <(String, Map)>[];
  @override
  String fileUrl(String path) => 'http://test.invalid$path?token=t';
  @override
  Future<dynamic> post(String path, [Object? body]) async {
    posts.add((path, body as Map));
    return {'ok': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> card({String? state, bool live = false}) => {
      'type': 'browser',
      'session': 'taobao-com',
      'site': 'taobao.com',
      if (live) 'live': true,
      if (state != null) 'handoff': {'id': 'h1', 'reason': '用淘宝 App 扫码登录', 'state': state},
    };

typedef Reply = (String, Map<String, String>?);

Future<void> pump(WidgetTester tester, Map<String, dynamic> j, {bool Function(String, Map<String, String>?, bool)? onForm, FakeApi? api}) async {
  tester.view.physicalSize = const Size(500, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api ?? FakeApi())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: BlockActions(onForm: onForm, child: SingleChildScrollView(child: BlockView(Block.fromJson(j))))),
    ),
  ));
  await tester.pump(const Duration(milliseconds: 400));
}

Future<void> frames(WidgetTester tester) async {
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  setUp(BrowserBlockView.autoOpened.clear);

  test('规则：按钮文案、结果行、刷新节奏、暂停条件、读屏', () {
    expect(takeoverLabel, '接管');
    const h = BrowserHandoff(id: 'h', reason: 'r');
    expect(handoffStateLine(h), '');
    expect(handoffStateLine(const BrowserHandoff(id: 'h', reason: 'r', state: 'done')), '你已交还，助手接着做');
    expect(handoffStateLine(const BrowserHandoff(id: 'h', reason: 'r', state: 'cancelled')), '你没有接管，助手会换个办法');
    expect(handoffStateLine(const BrowserHandoff(id: 'h', reason: 'r', state: 'expired')), '等太久没回应，已取消');
    expect(screenInterval(control: true, live: true), Timing.screenFast);
    expect(screenInterval(control: false, live: true), Timing.screenOpening);
    expect(screenInterval(control: false, live: false), Timing.screenIdle);
    expect(Timing.screenFast < Timing.screenOpening && Timing.screenOpening < Timing.screenIdle, isTrue);
    const long = Duration(minutes: 3);
    expect(screenShouldPause(idle: long, control: false, live: false, pending: false), isTrue);
    expect(screenShouldPause(idle: const Duration(seconds: 30), control: false, live: false, pending: false), isFalse);
    expect(screenShouldPause(idle: long, control: true, live: false, pending: false), isFalse);
    expect(screenShouldPause(idle: long, control: false, live: true, pending: false), isFalse);
    expect(screenShouldPause(idle: long, control: false, live: false, pending: true), isFalse);
    expect(browserScreenSemantics(takeover: true, paused: false, site: 'taobao.com'), 'taobao.com 的浏览器实时画面，已接管，点哪里就点网页哪里');
    expect(browserScreenSemantics(takeover: false, paused: false), '浏览器实时画面，点开接管');
    expect(browserScreenSemantics(takeover: false, paused: true), '浏览器画面已暂停，轻点继续');
  });

  test('接管页坐标：contain 留边、放大平移后换算、留边处不点、平移夹边、滚动比例', () {
    const tall = Size(400, 800); // 竖屏：画面上下留边
    final fit = takeoverFit(tall);
    expect(fit.width, 400);
    expect(fit.height, 250);
    expect(fit.top, 275);
    expect(takeoverPoint(const Offset(200, 400), tall), const Offset(0.5, 0.5));
    expect(takeoverPoint(const Offset(200, 100), tall), isNull); // 上方留边
    // 放大 2 倍、把画面左上角平移到屏幕左上：屏幕 (100, 0) 落在 scene (50+0, 275+0)… 用公式反推
    const pan = Offset(-200, -400);
    final p = takeoverPoint(const Offset(200, 400), tall, scale: 2, pan: pan)!;
    expect(p.dx, closeTo(0.5, 1e-9)); // 以中心放大：中心还是中心
    expect(p.dy, closeTo(0.5, 1e-9));
    final q = takeoverPoint(const Offset(0, 400), tall, scale: 2, pan: pan)!;
    expect(q.dx, closeTo(0.25, 1e-9));
    const wide = Size(1600, 800); // 宽屏：左右留边
    expect(takeoverFit(wide).left, 160);
    expect(takeoverPoint(const Offset(100, 400), wide), isNull);
    expect(takeoverClampPan(const Offset(50, -5000), tall, 2), const Offset(0, -800));
    expect(takeoverClampPan(const Offset(-30, -30), tall, 1), Offset.zero);
    expect(takeoverScrollPixels(-25, tall, 1), 80); // 手指上划 25 px（画面高 250 = 网页 800）→ 网页下滚 80
    expect(takeoverScrollPixels(-25, tall, 2), 40); // 放大后同一指滚得少
  });

  test('解析：handoff 可选、坏数据当作没有', () {
    final b = Block.fromJson(card(state: 'pending')) as BrowserBlock;
    expect((b.handoff!.id, b.handoff!.reason, b.handoff!.pending), ('h1', '用淘宝 App 扫码登录', true));
    expect((Block.fromJson(card()) as BrowserBlock).handoff, isNull);
    expect((Block.fromJson({...card(), 'handoff': 'x'}) as BrowserBlock).handoff, isNull);
  });

  testWidgets('等你接管：自动推出接管页（条在页上）；完成 → onForm(id, {})、关页、卡上按钮收起', (tester) async {
    final replies = <Reply>[];
    await pump(tester, card(state: 'pending'), onForm: (id, v, _) {
      replies.add((id, v));
      return true;
    });
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsOneWidget);
    expect(find.text(handoffTitle), findsOneWidget); // 卡被盖住（offstage），只数页上的
    expect(find.text('用淘宝 App 扫码登录'), findsOneWidget);
    expect(find.text(takeoverHint), findsOneWidget);
    await tester.tap(find.text(handoffDoneLabel));
    await frames(tester);
    expect(replies.single.$1, 'h1');
    expect(replies.single.$2, isEmpty);
    expect(find.byType(BrowserTakeoverPage), findsNothing);
    expect(find.text(handoffDoneLabel), findsNothing);
    expect(find.text(takeoverLabel), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('同一个 handoff 只自动推一次：关掉页后卡上条还在，点“接管”再进', (tester) async {
    await pump(tester, card(state: 'pending'), onForm: (_, _, _) => true);
    await frames(tester);
    await tester.tap(find.byTooltip('关闭'));
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsNothing);
    expect(find.text(handoffTitle), findsOneWidget); // 卡上的条
    await unmount(tester);
    await pump(tester, card(state: 'pending'), onForm: (_, _, _) => true); // 列表回收重建
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsNothing);
    await tester.tap(find.text(takeoverLabel));
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('接管页手势：点 → mouse；单指拖 → scroll；长按拖 → down/move/up；后退刷新；打字/空着 = 回车', (tester) async {
    final api = FakeApi();
    await pump(tester, card(), onForm: (_, _, _) => true, api: api);
    await tester.tap(find.text(takeoverLabel));
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsOneWidget);
    final stage = find.byType(AspectRatio).last;
    final c = tester.getCenter(stage);

    await tester.tapAt(c);
    await frames(tester);
    var (path, body) = api.posts.last;
    expect(path, '/api/browser/mouse');
    expect((body['x'] as double), closeTo(0.5, 0.01));
    expect((body['y'] as double), closeTo(0.5, 0.01));
    expect(body['session'], 'taobao-com');
    expect(body.containsKey('kind'), isFalse);
    api.posts.clear();
    await tester.dragFrom(c, const Offset(0, -120));
    await frames(tester);
    final scrolls = api.posts.where((p) => p.$1 == '/api/browser/scroll').toList();
    expect(scrolls, isNotEmpty);
    expect(scrolls.fold<double>(0, (a, p) => a + (p.$2['dy'] as double)), greaterThan(0)); // 上划 = 网页下滚

    api.posts.clear();
    final g = await tester.startGesture(c);
    await tester.pump(kLongPressTimeout + const Duration(milliseconds: 100));
    await g.moveBy(const Offset(60, 0));
    await tester.pump(const Duration(milliseconds: 200));
    await g.up();
    await frames(tester);
    final kinds = [for (final p in api.posts.where((p) => p.$1 == '/api/browser/mouse')) p.$2['kind']];
    expect(kinds.first, 'down');
    expect(kinds.last, 'up');
    expect(kinds, contains('move'));

    api.posts.clear();
    await tester.tap(find.byTooltip('后退'));
    await tester.tap(find.byTooltip('刷新'));
    await frames(tester);
    expect([for (final p in api.posts) p.$2['action']], ['back', 'reload']);

    api.posts.clear();
    await tester.enterText(find.byType(TextField), 'abc');
    await tester.tap(find.byTooltip('发到网页'));
    await frames(tester);
    await tester.tap(find.byTooltip('发到网页'));
    await frames(tester);
    expect(api.posts.map((p) => (p.$1, p.$2['text'], p.$2['key'])).toList(),
        [('/api/browser/keyboard', 'abc', null), ('/api/browser/keyboard', null, 'Enter')]);
    await unmount(tester);
  });

  testWidgets('做不了 → onForm(id, null)；断线（返回 false）按钮留着', (tester) async {
    final replies = <Reply>[];
    var online = false;
    await pump(tester, card(state: 'pending'), onForm: (id, v, _) {
      replies.add((id, v));
      return online;
    });
    await frames(tester);
    await tester.tap(find.byTooltip('关闭')); // 在卡上的条里答
    await frames(tester);
    await tester.tap(find.text(handoffCancelLabel));
    await frames(tester);
    expect(find.text(handoffCancelLabel), findsOneWidget); // 没发出去：还能再点
    online = true;
    await tester.tap(find.text(handoffCancelLabel));
    await frames(tester);
    expect(replies.last, ('h1', null));
    expect(find.text(handoffCancelLabel), findsNothing);
    await tester.pump(const Duration(seconds: 5)); // toast 走完
    await unmount(tester);
  });

  testWidgets('只读场景（没有 onForm）：只显示说明，没有按钮，不自动推页', (tester) async {
    await pump(tester, card(state: 'pending'));
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsNothing);
    expect(find.text('用淘宝 App 扫码登录'), findsOneWidget);
    expect(find.text(handoffDoneLabel), findsNothing);
    await unmount(tester);
  });

  testWidgets('结束后一行结果，不再有条', (tester) async {
    await pump(tester, card(state: 'done'), onForm: (_, _, _) => true);
    expect(find.text('你已交还，助手接着做'), findsOneWidget);
    expect(find.text(handoffTitle), findsNothing);
    expect(find.text(takeoverLabel), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('只是看着超过 2 分钟 → 暂停；点一下继续', (tester) async {
    await pump(tester, card(), onForm: (_, _, _) => true);
    expect(find.text('画面已暂停，轻点继续'), findsNothing);
    for (var i = 0; i < 90; i++) {
      await tester.pump(Timing.screenIdle);
    }
    await frames(tester);
    expect(find.text('画面已暂停，轻点继续'), findsOneWidget);
    await tester.tap(find.text('画面已暂停，轻点继续'));
    await frames(tester);
    expect(find.text('画面已暂停，轻点继续'), findsNothing);
    await unmount(tester);
  });
}
