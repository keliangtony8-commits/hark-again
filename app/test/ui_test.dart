import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/format.dart';
import 'package:assistant/ui/sheets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('formatSize / formatAgo', () {
    expect(formatSize(512), '512 B');
    expect(formatSize(2048), '2 KB');
    expect(formatSize(3 * 1024 * 1024), '3.0 MB');
    final now = DateTime(2026, 10, 11, 12);
    expect(formatAgo(now.subtract(const Duration(seconds: 10)), now: now), '刚刚');
    expect(formatAgo(now.subtract(const Duration(minutes: 5)), now: now), '5 分钟前');
    expect(formatAgo(now.subtract(const Duration(hours: 3)), now: now), '3 小时前');
    expect(formatAgo(DateTime(2026, 1, 2), now: now), '2026-01-02');
  });

  test('资源模型解析（脱敏保险箱、连接器、Page）', () {
    final s = SecretItem.fromJson({'id': '1', 'kind': 'login', 'name': '教务', 'username': 'me', 'hosts': ['a.edu'], 'preview': '••ab'});
    expect(s.isLogin, isTrue);
    expect(s.hosts, ['a.edu']);
    expect(Connector.fromJson({'id': 'github', 'name': 'GitHub', 'status': 'available', 'account': null}).connected, isFalse);
    final pg = PageItem.fromJson({'id': 'trip', 'slug': 'trip', 'title': '行程', 'url': 'https://x/p/trip/', 'updated': 1760000000.5});
    expect(pg.updatedAt, isNotNull);
  });

  testWidgets('表单弹层：必填为空不能提交，提交返回去空白的值', (tester) async {
    Map<String, String>? result;
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Builder(
        builder: (ctx) => Scaffold(
          body: TextButton(
            onPressed: () async => result = await showFormSheet(ctx, title: '新项目', fields: const [
              FieldSpec('name', '名称'),
              FieldSpec('note', '备注', required: false),
            ]),
            child: const Text('open'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    final save = find.widgetWithText(FilledButton, '保存');
    expect(tester.widget<FilledButton>(save).onPressed, isNull);
    await tester.enterText(find.byType(TextField).first, '  期末复习 ');
    await tester.pump();
    expect(tester.widget<FilledButton>(save).onPressed, isNotNull);
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(result, {'name': '期末复习', 'note': ''});
  });

  testWidgets('操作菜单：返回选中的值', (tester) async {
    String? picked;
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Builder(
        builder: (ctx) => Scaffold(
          body: TextButton(
            onPressed: () async => picked = await showActionSheet<String>(ctx, actions: const [
              SheetAction(Icons.key_rounded, 'API Key', value: 'api_key'),
              SheetAction(Icons.person_outline_rounded, '登录', value: 'login'),
            ]),
            child: const Text('open'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('登录'));
    await tester.pumpAndSettle();
    expect(picked, 'login');
  });
}
