// 要环境变量卡（v1.88 request_env，purpose=env）：解析 min_length；钥匙图标 + “只存进保险箱”；
// v2.49 token（mcp_servers 要 MCP 令牌）同样钥匙图标 + 不让密码管理器存 + 自己的去向说明；
// 太短时框下提示且不能提交，够长才回调（不带“记住”）；发出后清空收起；提交后状态“已存好”。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/form_block.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> env(String state) => {
      'type': 'form',
      'id': 'e1',
      'purpose': 'env',
      'title': '需要TELEGRAM_BOT_TOKEN',
      'note': '在 @BotFather 创建机器人后给的 Token',
      'action': '存进保险箱',
      'state': state,
      'fields': [
        {'name': 'value', 'label': 'TELEGRAM_BOT_TOKEN 的值', 'kind': 'password', 'min_length': 6},
      ],
    };

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

void main() {
  test('解析 min_length + 完整性', () {
    final b = Block.fromJson(env('pending')) as FormBlock;
    final f = b.fields.single;
    expect(f.minLength, 6);
    expect(f.tooShort(''), isFalse);
    expect(f.tooShort('abc'), isTrue);
    expect(f.tooShort('abcdef'), isFalse);
    expect(b.completeWith({'value': 'abc'}), isFalse);
    expect(b.completeWith({'value': 'abcdef'}), isTrue);
    expect(FormBlockView.iconOf(b), Icons.key_rounded);
    expect(FormBlockView.privacyNote('env'), contains('保险箱'));
    expect((Block.fromJson({...env('pending'), 'fields': [{'name': 'a', 'label': 'A'}]}) as FormBlock).fields.single.minLength, 0);
    expect(b.asksKey, isTrue);
  });

  testWidgets('MCP 令牌卡：钥匙图标、说明去向、不让密码管理器存', (tester) async {
    final t = Block.fromJson({...env('pending'), 'purpose': 'token', 'title': '添加 MCP「notion」需要令牌',
      'site': 'mcp.notion.com', 'action': '连接'}) as FormBlock;
    expect(t.asksKey, isTrue);
    expect((Block.fromJson({...env('pending'), 'purpose': 'login'}) as FormBlock).asksKey, isFalse);
    expect(FormBlockView.iconOf(t), Icons.key_rounded);
    await pump(tester, t, onForm: (_, _, _) => true);
    expect(find.textContaining('只用来连接这台 MCP 服务器'), findsOneWidget);
    expect(find.textContaining('保险箱'), findsNothing);
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.autofillHints, isNull);
    expect(field.obscureText, isTrue);
  });

  testWidgets('太短提示、够长才提交，发出后清空', (tester) async {
    final replies = <(String, Map<String, String>?, bool)>[];
    await pump(tester, Block.fromJson(env('pending')), onForm: (id, v, r) {
      replies.add((id, v, r));
      return true;
    });
    expect(find.byIcon(Icons.key_rounded), findsOneWidget);
    expect(find.textContaining('只存进保险箱'), findsOneWidget);
    expect(find.textContaining('记住'), findsNothing);
    await tester.enterText(find.byType(TextField), 'abc');
    await tester.pumpAndSettle();
    expect(find.text('至少 6 个字符'), findsOneWidget);
    await tester.tap(find.text('存进保险箱'));
    await tester.pump();
    expect(replies, isEmpty);
    await tester.enterText(find.byType(TextField), 'tg-123456:ABC');
    await tester.pumpAndSettle();
    expect(find.text('至少 6 个字符'), findsNothing);
    await tester.tap(find.text('存进保险箱'));
    await tester.pumpAndSettle();
    final (id, values, remember) = replies.single;
    expect(id, 'e1');
    expect(values, {'value': 'tg-123456:ABC'});
    expect(remember, isFalse);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('提交后显示已存好、不带值', (tester) async {
    await pump(tester, Block.fromJson(env('submitted')), onForm: (_, _, _) => true);
    expect(find.text('已存好'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
  });
}
