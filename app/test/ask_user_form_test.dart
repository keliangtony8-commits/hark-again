// info 表单卡（v0.87 ask_user：助手缺信息时问你）：解析 note / options / optional / answers；
// 点候选填进框里且高亮；必填填了就能提交（选填空着也行），带“记进记忆”；提示语说明内容交给助手；
// 提交后服务器写回 answers → 展示一问一答，不再有输入框；多行 / 电话键盘。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

typedef Reply = (String, Map<String, String>?, bool);

Future<void> pump(WidgetTester tester, Block b, {bool Function(String, Map<String, String>?, bool)? onForm}) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(body: BlockActions(onForm: onForm, child: SingleChildScrollView(child: BlockView(b)))),
  ));
  await tester.pumpAndSettle();
}

Map<String, dynamic> info(String state, {List<Map<String, String>>? answers}) => {
      'type': 'form',
      'id': 'f9',
      'purpose': 'info',
      'title': '订几位？',
      'note': '订座要人数和电话',
      'remember': true,
      'action': '告诉助手',
      'state': state,
      'fields': [
        {'name': 'q1', 'label': '人数', 'kind': 'text', 'options': ['2 位', '4 位']},
        {'name': 'q2', 'label': '电话', 'kind': 'phone'},
        {'name': 'q3', 'label': '备注', 'kind': 'multiline', 'optional': true},
      ],
      'answers': ?answers,
    };

void main() {
  test('解析 + 完整性只看必填', () {
    final b = Block.fromJson(info('pending')) as FormBlock;
    expect(b.note, '订座要人数和电话');
    expect(b.fields[0].options, ['2 位', '4 位']);
    expect(b.fields[2].optional, isTrue);
    expect(b.answers, isEmpty);
    expect(b.completeWith({'q1': '2 位', 'q2': '138'}), isTrue);
    expect(b.completeWith({'q1': '2 位', 'q2': ' '}), isFalse);
    final done = Block.fromJson(info('submitted', answers: [{'label': '人数', 'value': '4 位'}])) as FormBlock;
    expect(done.answers.single.value, '4 位');
    expect(copyText([done, const TextBlock('好')]), '好');
  });

  testWidgets('点候选 → 填进框并高亮；必填齐就能提交，带记住', (tester) async {
    final replies = <Reply>[];
    await pump(tester, Block.fromJson(info('pending')), onForm: (id, v, r) {
      replies.add((id, v, r));
      return true;
    });
    expect(find.text('订座要人数和电话'), findsOneWidget);
    expect(find.text('记进记忆，下次不用再问'), findsOneWidget);
    expect(find.textContaining('交给助手'), findsOneWidget);
    expect(find.textContaining('助手看不到'), findsNothing);
    expect(find.widgetWithText(TextField, '备注（选填）'), findsOneWidget);
    final phone = tester.widget<TextField>(find.widgetWithText(TextField, '电话'));
    expect(phone.keyboardType, TextInputType.phone);
    final note = tester.widget<TextField>(find.widgetWithText(TextField, '备注（选填）'));
    expect(note.maxLines, 4);
    expect(note.minLines, 1); // v0.92：多行框从一行起，边写边长
    expect(note.decoration!.isDense, isTrue); // 卡片里用紧凑输入框（compactField）
    expect(phone.decoration!.isDense, isTrue);

    await tester.tap(find.widgetWithText(ChoiceChip, '4 位'));
    await tester.pump();
    expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '4 位')).selected, isTrue);
    expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '2 位')).selected, isFalse);
    await tester.tap(find.text('告诉助手'));
    await tester.pump();
    expect(replies, isEmpty); // 电话还没填
    await tester.enterText(find.widgetWithText(TextField, '电话'), '13800001111');
    await tester.pump();
    await tester.tap(find.byType(Switch));
    await tester.pump();
    await tester.tap(find.text('告诉助手'));
    await tester.pumpAndSettle();
    expect(replies.single.$2, {'q1': '4 位', 'q2': '13800001111', 'q3': ''});
    expect(replies.single.$3, isTrue);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('提交后展示一问一答', (tester) async {
    await pump(tester, Block.fromJson(info('submitted', answers: [{'label': '人数', 'value': '4 位'}, {'label': '电话', 'value': '138'}])),
        onForm: (_, _, _) => true);
    expect(find.text('已填写'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(find.text('人数'), findsOneWidget);
    expect(find.text('4 位'), findsOneWidget);
    expect(find.text('138'), findsOneWidget);
  });
}
