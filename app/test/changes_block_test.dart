// 改动卡（v1.68）：解析、合计与小字规则、独立成卡；卡片行为——点文件展开 diff、撤销要确认、
// 成功不提示、失败把原因 toast 出来、已撤销没有按钮且文件名划掉、没有撤销入口时不显示按钮。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/changes.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/diff_view.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

ChangesBlock _card({String token = 'abc123', bool undone = false, int more = 0, List<Map<String, dynamic>>? files}) =>
    Block.fromJson({
      'type': 'changes',
      'token': token,
      'undone': undone,
      'more': more,
      'files': files ??
          [
            {'path': 'notes.md', 'added': 1, 'removed': 1, 'diff': '@@ -1,2 +1,2 @@\n 第一行\n-第二行\n+第二行（改）'},
            {'path': 'out/report.md', 'added': 2, 'removed': 0, 'diff': '+# 报告\n+x', 'created': true},
            {'path': 'big.bin', 'added': 3, 'big': true},
          ],
    }) as ChangesBlock;

Future<void> _show(WidgetTester t, ChangesBlock b, {Future<String?> Function(String)? undo}) => t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: BlockActions(
          onUndoChanges: undo,
          child: Padding(padding: const EdgeInsets.all(16), child: SingleChildScrollView(child: BlockView(b))),
        ),
      ),
    ));

void main() {
  test('规则', () {
    final b = _card(more: 2);
    expect(b.files.length, 3);
    expect(b.files[1].created, isTrue);
    expect(b.files[2].big, isTrue);
    expect(changesCount(b), 5);
    expect(changesTitle(b), '改了 5 个文件');
    expect(changesTotals(b), (6, 1));
    expect(changesUndoable(b), isTrue);
    expect(changesNote(b), '1 个大文件不能撤销');
    expect(changeTag(b.files[2]), '大文件');
    expect(changeTag(b.files[0]), isNull);
    expect(standsAlone(b), isTrue);
    final u = _card(undone: true);
    expect(changesTitle(u), '已撤销 3 个文件的改动');
    expect(changesUndoable(u), isFalse);
    expect(changesNote(u), '文件已回到这一轮之前的样子');
    expect(changesUndoable(_card(token: '')), isFalse);
    expect(changesNote(_card(token: '')), '文件太大，没有留撤销记录');
    expect(changesSemantics(_card()), contains('增加 6 行，删除 1 行：notes.md、out/report.md、big.bin'));
    expect((Block.fromJson({'type': 'changes'}) as ChangesBlock).files, isEmpty);
  });

  test('v2.14 命令改的文件：解析 + 小字', () {
    final c = _card(files: [
      {'path': 'a.txt', 'added': 1, 'command': true},
      {'path': 'made.txt', 'added': 1, 'created': true, 'command': true},
      {'path': 'big.bin', 'added': 3, 'big': true, 'command': true},
    ]);
    expect(c.files[0].command, isTrue);
    expect(changesNote(c), '1 个大文件不能撤销 · 其中 3 个是命令改的');
    expect(changesNote(_card(files: [{'path': 'a.txt', 'added': 1, 'command': true}])), '其中 1 个是命令改的');
    expect(_card().files[0].command, isFalse);
  });

  testWidgets('点文件展开 diff；撤销先确认，失败 toast 原因', (t) async {
    final calls = <String>[];
    await _show(t, _card(), undo: (tok) async {
      calls.add(tok);
      return '这些文件之后又被改过，撤销会冲掉新的改动：notes.md';
    });
    await t.pumpAndSettle();
    expect(find.text('改了 3 个文件'), findsOneWidget);
    expect(find.byType(DiffView), findsNothing);
    await t.tap(find.text('notes.md'));
    await t.pumpAndSettle();
    expect(find.byType(DiffView), findsOneWidget);
    await t.tap(find.text('notes.md'));
    await t.pumpAndSettle();
    expect(find.byType(DiffView), findsNothing);

    await t.tap(find.text('撤销'));
    await t.pumpAndSettle();
    expect(find.text('撤销这一轮的文件改动？'), findsOneWidget);
    await t.tap(find.text('取消'));
    await t.pumpAndSettle();
    expect(calls, isEmpty);

    await t.tap(find.text('撤销'));
    await t.pumpAndSettle();
    await t.tap(find.widgetWithText(PillButton, '撤销'));
    await t.pumpAndSettle();
    expect(calls, ['abc123']);
    expect(find.textContaining('之后又被改过'), findsOneWidget);
    await t.pump(const Duration(seconds: 5));
    await t.pumpAndSettle();
  });

  testWidgets('已撤销：没有按钮，换标题；没有撤销入口也不显示按钮', (t) async {
    await _show(t, _card(undone: true), undo: (_) async => null);
    await t.pumpAndSettle();
    expect(find.text('已撤销 3 个文件的改动'), findsOneWidget);
    expect(find.text('撤销'), findsNothing);
    final style = t.widget<DefaultTextStyle>(find.ancestor(of: find.text('notes.md'), matching: find.byType(DefaultTextStyle)).first).style;
    expect(style.decoration, TextDecoration.lineThrough);
    await _show(t, _card());
    await t.pumpAndSettle();
    expect(find.text('撤销'), findsNothing);
  });
}
