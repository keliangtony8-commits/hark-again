// v1.69 apply_patch：时间线一步改了几个文件（step.changes）——行尾合计，点开逐个文件（改名写 旧 → 新，删除写“已删除”，点开看删掉了什么），
// 再点某个文件看它的 diff；单个文件的老形状（step.change）不变。
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/diff_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _at = 'Mon 2026-10-13 1:00 AM CST (UTC+08:00)';

final _json = {
  'id': 'm1',
  'role': 'assistant',
  'blocks': [
    {'type': 'text', 'text': '改好了。'}
  ],
  'steps': [
    {
      'id': 'a', 'tool': 'apply_patch', 'title': '改文件', 'detail': 'hello.txt 等 3 个文件', 'state': 'done', 'at': _at, 'ms': 40,
      'changes': [
        {'path': 'hello.txt', 'added': 1, 'removed': 0, 'diff': '@@ -0,0 +1 @@\n+Hello world', 'created': true},
        {'path': 'src/main.py', 'added': 1, 'removed': 1, 'diff': '@@ -1,2 +1,2 @@\n def greet():\n-    print("Hi")\n+    print("Hello")', 'moved_from': 'src/app.py'},
        {'path': 'obsolete.txt', 'added': 0, 'removed': 2, 'diff': '@@ -1,2 +0,0 @@\n-a\n-b', 'deleted': true},
        'bad',
      ],
    },
  ],
};

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SingleChildScrollView(child: SizedBox(width: 400, child: MessageView(m)))),
      ),
    );

void main() {
  test('规则：changes 列表、合计、改名标签、读屏、单文件老形状', () {
    final s = Message.fromJson(_json).steps.single;
    expect(s.files.map((f) => f.path), ['hello.txt', 'src/main.py', 'obsolete.txt']); // 坏项跳过
    expect((s.change!.added, s.change!.removed, s.change!.path), (2, 3, ''));
    expect(s.expandable, isTrue);
    expect(s.files[1].label, 'src/app.py → src/main.py');
    expect(s.files[1].semantics, '从 src/app.py 改名，增加 1 行，删除 1 行');
    expect(stepFileTag(s.files[2]), '已删除');
    expect(stepFileTag(s.files[0]), isNull);
    expect(stepSemantics(s), '改文件 hello.txt 等 3 个文件，完成，改了 3 个文件，增加 2 行，删除 3 行，用时 0.0 秒');
    final one = ActivityStep.fromJson({'id': 'x', 'change': {'path': 'a', 'added': 1, 'diff': ''}});
    expect((one.files.length, one.change!.path, one.expandable), (1, 'a', false));
    expect(ActivityStep.fromJson({'id': 'y'}).change, isNull);
  });

  testWidgets('一步几个文件：合计、点开列文件、点文件看 diff（同时只开一个）', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(Message.fromJson(_json)));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('用了 1 步'));
    await tester.pumpAndSettle();
    expect(find.text('+2'), findsOneWidget);
    expect(find.text(' −3'), findsOneWidget);
    expect(find.byType(FileDiffRow), findsNothing);

    await tester.tap(find.text('hello.txt 等 3 个文件'));
    await tester.pumpAndSettle();
    expect(find.byType(FileDiffRow), findsNWidgets(3));
    expect(find.text('src/app.py → src/main.py'), findsOneWidget);
    expect(find.text('改名 '), findsOneWidget);
    expect(find.text('已删除'), findsOneWidget);
    expect(find.byType(DiffView), findsNothing);

    await tester.tap(find.text('src/app.py → src/main.py'));
    await tester.pumpAndSettle();
    expect(find.byType(DiffView), findsOneWidget);
    expect(tester.widget<Text>(find.text('+    print("Hello")')).style?.color, Palette.light.success);

    await tester.tap(find.text('hello.txt'));
    await tester.pumpAndSettle();
    expect(find.byType(DiffView), findsOneWidget); // 同时只开一个
    expect(find.text('+Hello world'), findsOneWidget);

    await tester.tap(find.text('obsolete.txt')); // 已删除：tag 代替 +N −M，点开看删掉了什么
    await tester.pumpAndSettle();
    expect(find.text('-a'), findsOneWidget);
    expect(find.text('+Hello world'), findsNothing);

    await tester.tap(find.text('hello.txt 等 3 个文件'));
    await tester.pumpAndSettle();
    expect(find.byType(FileDiffRow), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
