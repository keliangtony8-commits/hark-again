// v1.34 改文件：时间线里改了文件的步骤带 “+N −M”，点开看 diff（新增绿、删除红）；像密钥的文件只有数字不能展开。
import 'package:assistant/features/chat/activity_view.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _at = '2026-10-12T05:00:00+00:00';

final _json = {
  'id': 'm1',
  'role': 'assistant',
  'blocks': [
    {'type': 'text', 'text': '改好了。'}
  ],
  'steps': [
    {
      'id': 'a', 'tool': 'edit_file', 'title': '改文件', 'detail': 'src/app.py', 'state': 'done', 'at': _at, 'ms': 30,
      'change': {'path': 'src/app.py', 'added': 2, 'removed': 1, 'diff': '@@ -1,3 +1,4 @@\n x = 1\n-y = 2\n+y = 3\n+z = 4\n x = 1'},
    },
    {
      'id': 'b', 'tool': 'write_file', 'title': '写文件', 'detail': '.env', 'state': 'done', 'at': _at, 'ms': 10,
      'change': {'path': '.env', 'added': 1, 'removed': 0, 'diff': '', 'created': true, 'hidden': true},
    },
    {'id': 'c', 'tool': 'edit_file', 'title': '改文件', 'detail': 'b.py', 'state': 'error', 'at': _at, 'ms': 5, 'note': '匹配到 2 处，不唯一'},
  ],
};

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SingleChildScrollView(child: SizedBox(width: 400, child: MessageView(m)))),
      ),
    );

void main() {
  test('规则：解析 change、diff 行分类、读屏', () {
    final m = Message.fromJson(_json);
    final c = m.steps[0].change!;
    expect((c.added, c.removed, c.expandable, c.created), (2, 1, true, false));
    expect(m.steps[1].change!.expandable, isFalse);
    expect(m.steps[2].change, isNull);
    expect(diffLines(c.diff).map((e) => e.$1).toList(),
        [DiffKind.hunk, DiffKind.context, DiffKind.remove, DiffKind.add, DiffKind.add, DiffKind.context]);
    expect(diffLines('… 还有 3 行改动没显示').single.$1, DiffKind.note);
    expect(stepSemantics(m.steps[0]), '改文件 src/app.py，完成，增加 2 行，删除 1 行，用时 0.0 秒');
    expect(m.steps[1].change!.semantics, '新建，增加 1 行');
  });

  testWidgets('改文件的步骤显示 +2 −1，点开看 diff，再点收起', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(Message.fromJson(_json)));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('用了 3 步'));
    await tester.pumpAndSettle();
    expect(find.text('+2'), findsOneWidget);
    expect(find.text(' −1'), findsOneWidget);
    expect(find.text('新建 '), findsOneWidget);
    expect(find.byType(DiffView), findsNothing);
    final ex0 = tester.takeException(); if (ex0 != null) debugPrint('BEFORE ${(ex0 as FlutterError).toStringDeep()}');
    final add = tester.widget<Text>(find.text('+2'));
    expect(add.style?.color, Palette.light.success);

    await tester.tap(find.text('src/app.py'));
    await tester.pumpAndSettle();
    expect(find.byType(DiffView), findsOneWidget);
    expect(tester.widget<Text>(find.text('+z = 4')).style?.color, Palette.light.success);
    expect(tester.widget<Text>(find.text('-y = 2')).style?.color, Palette.light.danger);
    final ex = tester.takeException(); if (ex != null) debugPrint('AFTER ${(ex as FlutterError).toStringDeep()}');

    await tester.tap(find.text('.env')); // 密钥文件：没有 diff，点了不展开第二个
    await tester.pumpAndSettle();
    expect(find.byType(DiffView), findsOneWidget);

    await tester.tap(find.text('src/app.py'));
    await tester.pumpAndSettle();
    expect(find.byType(DiffView), findsNothing);
    expect(find.text('匹配到 2 处，不唯一'), findsOneWidget);
  });
}
