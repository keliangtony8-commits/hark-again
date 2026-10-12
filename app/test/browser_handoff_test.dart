// 浏览器接管交还（v1.29）：models/browser_view.dart 规则 + BrowserBlock.handoff 解析 + 画面卡上的“需要你来”条
// （自动进入接管、完成/做不了回调 onForm、断线保留按钮、只读场景只显示说明、结束后一行结果）+ 只是看着 2 分钟后暂停、点一下继续。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/browser_view.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  final posts = <String>[];
  @override
  String fileUrl(String path) => 'http://test.invalid$path?token=t';
  @override
  Future<dynamic> post(String path, [Object? body]) async {
    posts.add(path);
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

Future<void> pump(WidgetTester tester, Map<String, dynamic> j, {bool Function(String, Map<String, String>?, bool)? onForm}) async {
  tester.view.physicalSize = const Size(500, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api())],
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
  test('规则：按钮文案、结果行、刷新节奏、暂停条件、读屏', () {
    expect(controlLabel(false), '接管');
    expect(controlLabel(true), '交还');
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
    expect(browserScreenSemantics(control: true, paused: false, site: 'taobao.com'), 'taobao.com 的浏览器实时画面，已接管，点哪里就点网页哪里');
    expect(browserScreenSemantics(control: false, paused: true), '浏览器画面已暂停，点一下继续');
  });

  test('解析：handoff 可选、坏数据当作没有', () {
    final b = Block.fromJson(card(state: 'pending')) as BrowserBlock;
    expect((b.handoff!.id, b.handoff!.reason, b.handoff!.pending), ('h1', '用淘宝 App 扫码登录', true));
    expect((Block.fromJson(card()) as BrowserBlock).handoff, isNull);
    expect((Block.fromJson({...card(), 'handoff': 'x'}) as BrowserBlock).handoff, isNull);
  });

  testWidgets('等你接管：自动进入接管（按钮变“交还”且不可点）、条上一句话；完成 → onForm(id, {})，按钮收起', (tester) async {
    final replies = <Reply>[];
    await pump(tester, card(state: 'pending'), onForm: (id, v, _) {
      replies.add((id, v));
      return true;
    });
    expect(find.text(handoffTitle), findsOneWidget);
    expect(find.text('用淘宝 App 扫码登录'), findsOneWidget);
    expect(find.text('交还'), findsOneWidget);
    expect(tester.widget<TextButton>(find.ancestor(of: find.text('交还'), matching: find.byWidgetPredicate((w) => w is TextButton))).onPressed, isNull);
    expect(find.byType(TextField), findsOneWidget); // 键盘输入框已出现
    await tester.tap(find.text(handoffDoneLabel));
    await frames(tester);
    expect(replies.single.$1, 'h1');
    expect(replies.single.$2, isEmpty);
    expect(find.text(handoffDoneLabel), findsNothing);
    expect(find.text('接管'), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('做不了 → onForm(id, null)；断线（返回 false）按钮留着', (tester) async {
    final replies = <Reply>[];
    var online = false;
    await pump(tester, card(state: 'pending'), onForm: (id, v, _) {
      replies.add((id, v));
      return online;
    });
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

  testWidgets('只读场景（没有 onForm）：只显示说明，没有按钮', (tester) async {
    await pump(tester, card(state: 'pending'));
    expect(find.text('用淘宝 App 扫码登录'), findsOneWidget);
    expect(find.text(handoffDoneLabel), findsNothing);
    await unmount(tester);
  });

  testWidgets('结束后一行结果，不再有条', (tester) async {
    await pump(tester, card(state: 'done'), onForm: (_, _, _) => true);
    expect(find.text('你已交还，助手接着做'), findsOneWidget);
    expect(find.text(handoffTitle), findsNothing);
    expect(find.text('接管'), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('只是看着超过 2 分钟 → 暂停；点一下继续', (tester) async {
    await pump(tester, card(), onForm: (_, _, _) => true);
    expect(find.text('画面已暂停，点一下继续'), findsNothing);
    for (var i = 0; i < 90; i++) {
      await tester.pump(Timing.screenIdle);
    }
    await frames(tester);
    expect(find.text('画面已暂停，点一下继续'), findsOneWidget);
    await tester.tap(find.text('画面已暂停，点一下继续'));
    await frames(tester);
    expect(find.text('画面已暂停，点一下继续'), findsNothing);
    await unmount(tester);
  });
}
