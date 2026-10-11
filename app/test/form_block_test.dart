// 表单卡（v0.83 浏览器任务里的登录卡 / 验证码卡）：解析、不进复制；等填写时填满才能提交、回调带值和“记住”、
// 取消回调 null；发出后输入框收起并清空；断线（onForm 返回 false）保留输入；没有回调或已提交时不显示输入框；
// 密码默认遮住、可切换显示。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

typedef Reply = (String, Map<String, String>?, bool);

Future<void> pump(WidgetTester tester, Block b, {bool Function(String, Map<String, String>?, bool)? onForm}) async {
  tester.view.physicalSize = const Size(800, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(body: BlockActions(onForm: onForm, child: SingleChildScrollView(child: BlockView(b)))),
  ));
  await tester.pumpAndSettle();
}

Map<String, dynamic> login(String state, {bool remember = true}) => {
      'type': 'form',
      'id': 'f1',
      'purpose': 'login',
      'title': '登录以继续',
      'site': 'shop.example.com',
      'remember': remember,
      'action': '登录',
      'state': state,
      'fields': [
        {'name': 'username', 'label': '账号', 'kind': 'text'},
        {'name': 'password', 'label': '密码', 'kind': 'password'},
      ],
    };


void main() {
  test('解析 + 不进复制', () {
    final b = Block.fromJson(login('pending')) as FormBlock;
    expect(b.fields.map((f) => f.kind), ['text', 'password']);
    expect(b.remember, isTrue);
    expect(b.pending, isTrue);
    expect(copyText([b, const TextBlock('好了')]), '好了');
  });

  testWidgets('填满才能提交，带值和记住；发出后收起', (tester) async {
    final replies = <Reply>[];
    await pump(tester, Block.fromJson(login('pending')), onForm: (id, v, r) {
      replies.add((id, v, r));
      return true;
    });
    expect(find.text('等你填写'), findsOneWidget);
    expect(find.text('shop.example.com'), findsOneWidget);
    await tester.tap(find.text('登录'));
    await tester.pump();
    expect(replies, isEmpty); // 没填完
    await tester.enterText(find.widgetWithText(TextField, '账号'), 'me@x.com');
    await tester.enterText(find.widgetWithText(TextField, '密码'), 'pw');
    await tester.pump();
    final pwField = tester.widget<TextField>(find.widgetWithText(TextField, '密码'));
    expect(pwField.obscureText, isTrue);
    await tester.tap(find.byTooltip('显示密码'));
    await tester.pump();
    expect(tester.widget<TextField>(find.widgetWithText(TextField, '密码')).obscureText, isFalse);
    await tester.tap(find.byType(Switch));
    await tester.pump();
    await tester.tap(find.text('登录'));
    await tester.pumpAndSettle();
    expect(replies, hasLength(1));
    expect(replies[0].$1, 'f1');
    expect(replies[0].$2, {'username': 'me@x.com', 'password': 'pw'});
    expect(replies[0].$3, isTrue);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('取消 = null；断线保留输入', (tester) async {
    final replies = <Reply>[];
    var online = false;
    await pump(tester, Block.fromJson(login('pending', remember: false)), onForm: (id, v, r) {
      replies.add((id, v, r));
      return online;
    });
    expect(find.byType(Switch), findsNothing);
    await tester.enterText(find.widgetWithText(TextField, '账号'), 'a');
    await tester.enterText(find.widgetWithText(TextField, '密码'), 'b');
    await tester.pump();
    await tester.tap(find.text('登录'));
    await tester.pumpAndSettle();
    expect(find.text('a'), findsOneWidget); // 没发出去，输入还在
    online = true;
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(replies.last, ('f1', null, false));
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('已提交 / 没有回调：不显示输入框', (tester) async {
    await pump(tester, Block.fromJson(login('submitted')), onForm: (_, _, _) => true);
    expect(find.text('已填写'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    await pump(tester, Block.fromJson(login('pending')));
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('验证码卡：数字键盘', (tester) async {
    await pump(tester, Block.fromJson({
      'type': 'form', 'id': 'c', 'purpose': 'code', 'title': '短信验证码', 'action': '填入', 'state': 'pending',
      'fields': [{'name': 'code', 'label': '验证码', 'kind': 'code'}],
    }), onForm: (_, _, _) => true);
    final f = tester.widget<TextField>(find.byType(TextField));
    expect(f.keyboardType, TextInputType.number);
    expect(f.autofillHints, [AutofillHints.oneTimeCode]);
  });
}
