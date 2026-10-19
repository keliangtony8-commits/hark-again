// 浏览器接管交还（v1.29 / v2.82）：models/browser_view.dart 规则 + BrowserBlock.handoff 解析 + 画面卡上的“需要你来”条
// （助手在等你 → 自动推出全屏接管页、完成/做不了回调 onForm 并关页、断线保留按钮、只读场景只显示说明不推页、结束后一行结果）
// + v2.89 实时画面连接（一条 WS：首帧、断线留着最后一帧重连、浏览器已关闭 → 重新打开 open=1、卡片拆掉就断）
// + 接管页手势（点、单指滚、长按拖、后退刷新、打字）在同一条连接上发的消息 + 坐标换算
// + v3.5.x 点哪落哪（竖屏 / 横屏 / 放大后，按画面实际画出来的位置验）、点一下带真实按住时长 hold、外接鼠标悬停 = move。
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:assistant/blocks/browser_block.dart';
import 'package:assistant/blocks/browser_live.dart';
import 'package:assistant/blocks/browser_takeover.dart';
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/browser_view.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeApi implements Api {
  @override
  String fileUrl(String path) => 'http://test.invalid$path?token=t';

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

/// 假的实时画面连接：记下连了哪些地址、发了哪些消息；push 一帧、hangUp(code) 模拟服务器关。
class FakeLive implements LiveSocket {
  FakeLive(this.uri);
  final Uri uri;
  final _ctl = StreamController<dynamic>();
  final sent = <Map<String, dynamic>>[];
  @override
  int? closeCode;
  bool closed = false;
  @override
  Future<void> get ready => Future.value();
  @override
  Stream<dynamic> get stream => _ctl.stream;
  @override
  void send(String message) => sent.add(jsonDecode(message) as Map<String, dynamic>);
  @override
  void close() {
    closed = true;
    _ctl.close();
  }

  void push(List<int> bytes) => _ctl.add(Uint8List.fromList(bytes));
  void hangUp(int? code) {
    closeCode = code;
    _ctl.close();
  }
}

class FakeLives {
  final all = <FakeLive>[];
  FakeLive get last => all.last;
  LiveSocket connect(Uri uri) => (all..add(FakeLive(uri))).last;
  List<Map<String, dynamic>> get input => [for (final l in all) ...l.sent.where((m) => m['t'] != 'view')];
}

/// 1×1 透明 PNG：Image.memory 能解出来。
const onePixel = [
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00,
  0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63,
  0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
];

Map<String, dynamic> card({String? state, bool live = false}) => {
      'type': 'browser',
      'session': 'taobao-com',
      'site': 'taobao.com',
      if (live) 'live': true,
      if (state != null) 'handoff': {'id': 'h1', 'reason': '用淘宝 App 扫码登录', 'state': state},
    };

typedef Reply = (String, Map<String, String>?);

Future<void> pump(WidgetTester tester, Map<String, dynamic> j,
    {bool Function(String, Map<String, String>?, bool)? onForm, FakeLives? lives, Size size = const Size(500, 1000)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(FakeApi()), liveConnectProvider.overrideWithValue((lives ?? FakeLives()).connect)],
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
    expect(browserScreenSemantics(takeover: true, site: 'taobao.com'), 'taobao.com 的浏览器实时画面，已接管，点哪里就点网页哪里');
    expect(browserScreenSemantics(takeover: false), '浏览器实时画面，点开接管');
  });

  test('实时画面规则：关闭码 → 状态、退避、状态句', () {
    expect(liveStateAfterClose(liveCloseNotOpen, opening: false), LiveState.closed);
    expect(liveStateAfterClose(liveCloseNotOpen, opening: true), LiveState.reconnecting); // 还在打开：接着连
    expect(liveStateAfterClose(liveCloseDown, opening: false), LiveState.down);
    expect(liveStateAfterClose(liveCloseUnauthorized, opening: true), LiveState.closed);
    expect(liveStateAfterClose(null, opening: false), LiveState.reconnecting);
    expect(liveStateAfterClose(1006, opening: false), LiveState.reconnecting);
    expect([for (var i = 0; i < 7; i++) liveRetryDelay(i).inSeconds], [1, 2, 4, 8, 15, 15, 15]);
    expect(liveStatusLine(LiveState.live, hasFrame: true, opening: false), isNull);
    expect(liveStatusLine(LiveState.connecting, hasFrame: false, opening: true, site: 'a.com'), '正在打开 a.com…');
    expect(liveStatusLine(LiveState.reconnecting, hasFrame: true, opening: false), '正在重连…');
    expect(liveStatusLine(LiveState.closed, hasFrame: true, opening: false), liveClosedTitle);
    expect(liveCanReopen(LiveState.closed) && liveCanReopen(LiveState.down) && !liveCanReopen(LiveState.reconnecting), isTrue);
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

  testWidgets('接管页手势：同一条连接上发 点 / 滚 / 长按拖 / 后退刷新 / 打字 / 回车', (tester) async {
    final lives = FakeLives();
    await pump(tester, card(), onForm: (_, _, _) => true, lives: lives);
    await tester.tap(find.text(takeoverLabel));
    await frames(tester);
    expect(find.byType(BrowserTakeoverPage), findsOneWidget);
    expect(lives.all, hasLength(1)); // 接管页复用卡片的连接，不开第二条
    final stage = find.byType(AspectRatio).last;
    final c = tester.getCenter(stage);

    await tester.tapAt(c);
    await frames(tester);
    final click = lives.input.last;
    expect((click['t'], click['kind']), ('mouse', 'click'));
    expect(click['x'] as double, closeTo(0.5, 0.01));
    expect(click['y'] as double, closeTo(0.5, 0.01));
    lives.last.sent.clear();
    await tester.dragFrom(c, const Offset(0, -120));
    await frames(tester);
    final wheels = lives.input.where((m) => m['t'] == 'wheel').toList();
    expect(wheels, isNotEmpty);
    expect(wheels.fold<double>(0, (a, m) => a + (m['dy'] as num)), greaterThan(0)); // 上划 = 网页下滚

    lives.last.sent.clear();
    final g = await tester.startGesture(c);
    await tester.pump(kLongPressTimeout + const Duration(milliseconds: 100));
    await g.moveBy(const Offset(60, 0));
    await tester.pump(const Duration(milliseconds: 200));
    await g.up();
    await frames(tester);
    final kinds = [for (final m in lives.input.where((m) => m['t'] == 'mouse')) m['kind']];
    expect(kinds.first, 'down');
    expect(kinds.last, 'up');
    expect(kinds, contains('move'));

    lives.last.sent.clear();
    await tester.tap(find.byTooltip('后退'));
    await tester.tap(find.byTooltip('刷新'));
    await frames(tester);
    expect([for (final m in lives.input) m['action']], ['back', 'reload']);

    lives.last.sent.clear();
    await tester.enterText(find.byType(TextField), 'abc');
    await tester.tap(find.byTooltip('发到网页'));
    await frames(tester);
    await tester.tap(find.byTooltip('发到网页'));
    await frames(tester);
    expect(lives.input, [
      {'t': 'text', 'text': 'abc'},
      {'t': 'key', 'key': 'Enter'},
    ]);
    await tester.tap(find.byTooltip('关闭'));
    await frames(tester);
    expect(lives.last.closed, isFalse); // 关了接管页，卡片还在看
    expect(lives.last.sent.last, {'t': 'view', 'px': 498}); // 换回卡片的宽度（卡片宽 498 物理像素）
    await unmount(tester);
    expect(lives.last.closed, isTrue); // 卡片拆掉：断开
  });

  for (final size in const [Size(500, 1000), Size(1600, 700)]) {
    testWidgets('接管页点哪落哪 + 按住时长 + 鼠标悬停（${size.width.toInt()}×${size.height.toInt()}）', (tester) async {
      final lives = FakeLives();
      await pump(tester, card(), onForm: (_, _, _) => true, lives: lives, size: size);
      await tester.tap(find.text(takeoverLabel));
      await frames(tester);
      final screen = tester.getRect(find.byType(AspectRatio).last); // 画面实际画在这里
      expect(screen.width / screen.height, closeTo(browserAspect, 0.01));
      Offset on(double fx, double fy) => Offset(screen.left + fx * screen.width, screen.top + fy * screen.height);

      // 点一下：按下 → 抬起相隔 137ms，坐标按画面换算
      lives.last.sent.clear();
      final g = await tester.createGesture();
      await g.down(on(0.2, 0.7), timeStamp: const Duration(seconds: 10));
      await tester.pump(const Duration(milliseconds: 137));
      await g.up(timeStamp: const Duration(seconds: 10, milliseconds: 137));
      await frames(tester);
      final click = lives.input.single;
      expect((click['kind'], click['hold']), ('click', 137));
      expect(click['x'] as double, closeTo(0.2, 0.005));
      expect(click['y'] as double, closeTo(0.7, 0.005));

      // 外接鼠标没按住时移动 = 悬停 move，不点
      lives.last.sent.clear();
      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      await mouse.addPointer(location: on(0.5, 0.5));
      await mouse.moveTo(on(0.9, 0.1));
      await frames(tester);
      final moves = lives.input;
      expect(moves, isNotEmpty);
      expect(moves.every((m) => m['kind'] == 'move'), isTrue);
      expect(moves.last['x'] as double, closeTo(0.9, 0.005));
      expect(moves.last['y'] as double, closeTo(0.1, 0.005));
      await mouse.removePointer();
      await tester.tap(find.byTooltip('关闭'));
      await frames(tester);
      await unmount(tester);
    });
  }

  test('按住时长：缺一头不带，负数夹到 0', () {
    expect(takeoverHoldMs(null, const Duration(seconds: 1)), isNull);
    expect(takeoverHoldMs(const Duration(milliseconds: 5), const Duration(microseconds: 98600)), 94);
    expect(takeoverHoldMs(const Duration(seconds: 2), const Duration(seconds: 1)), 0);
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

  testWidgets('实时画面：首帧；断线留着最后一帧、正在重连、退避后重连；浏览器已关闭 → 重新打开带 open=1', (tester) async {
    final lives = FakeLives();
    await pump(tester, card(), onForm: (_, _, _) => true, lives: lives);
    expect(lives.all, hasLength(1));
    expect(lives.last.uri.toString(), 'ws://test.invalid/api/browser/live?token=t&session=taobao-com');
    expect(lives.last.sent.first, {'t': 'view', 'px': 498});
    expect(find.byType(Image), findsNothing);
    lives.last.push(onePixel);
    await frames(tester);
    expect(find.byType(Image), findsOneWidget);
    expect(find.byType(PulseDot), findsOneWidget);

    lives.last.hangUp(1006); // 网断了
    await frames(tester);
    expect(find.text('正在重连…'), findsOneWidget);
    expect(find.byType(Image), findsOneWidget); // 最后一帧还在
    await tester.pump(liveRetryDelay(0));
    expect(lives.all, hasLength(2));
    lives.last.push(onePixel);
    await frames(tester);
    expect(find.text('正在重连…'), findsNothing);

    lives.last.hangUp(liveCloseNotOpen); // 空闲回收 / 服务重启
    await frames(tester);
    expect(find.text(liveClosedTitle), findsOneWidget);
    await tester.pump(const Duration(seconds: 20));
    expect(lives.all, hasLength(2)); // 关了不自己重连
    await tester.tap(find.text(liveReopenLabel));
    await frames(tester);
    expect(lives.all, hasLength(3));
    expect(lives.last.uri.queryParameters['open'], '1');
    await unmount(tester);
  });

  testWidgets('还在打开（block.live）时浏览器没开 = 还没好：接着连，不说已关闭', (tester) async {
    final lives = FakeLives();
    await pump(tester, card(live: true), onForm: (_, _, _) => true, lives: lives);
    expect(find.text('正在打开 taobao.com…'), findsOneWidget);
    lives.last.hangUp(liveCloseNotOpen);
    await frames(tester);
    expect(find.text(liveClosedTitle), findsNothing);
    expect(find.text('正在打开 taobao.com…'), findsOneWidget);
    await tester.pump(liveRetryDelay(0));
    expect(lives.all, hasLength(2));
    await unmount(tester);
  });
}
