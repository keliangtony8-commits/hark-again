// `$技能` 点名（v1.81）：skill 块能解析；用户气泡上方一排技能小标签，文字照常显示；旧 App 认不出的块仍安静忽略。
import 'package:assistant/blocks/skill_chip.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SingleChildScrollView(child: SizedBox(width: 400, child: MessageView(m)))),
      ),
    );

void main() {
  test('skill 块解析', () {
    final b = Block.fromJson({'type': 'skill', 'id': 'writing', 'name': '写作'});
    expect(b, isA<SkillBlock>());
    expect((b as SkillBlock).name, '写作');
    expect((Block.fromJson({'type': 'skill'}) as SkillBlock).id, '');
  });

  testWidgets('用户气泡：技能标签 + 原文', (tester) async {
    final m = Message.fromJson({
      'id': 'u1',
      'role': 'user',
      'blocks': [
        {'type': 'text', 'text': r'$writing 帮我润色'},
        {'type': 'skill', 'id': 'writing', 'name': '写作'},
        {'type': 'skill', 'id': 'web-research', 'name': '网页调研'},
      ],
    });
    await tester.pumpWidget(_host(m));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byType(SkillChip), findsNWidgets(2));
    expect(find.text('写作'), findsOneWidget);
    expect(find.text('网页调研'), findsOneWidget);
    expect(find.text(r'$writing 帮我润色'), findsOneWidget);
  });

  testWidgets('没有技能的用户消息：不出标签', (tester) async {
    await tester.pumpWidget(_host(Message.fromJson({
      'id': 'u2',
      'role': 'user',
      'blocks': [
        {'type': 'text', 'text': '你好'}
      ],
    })));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byType(SkillChip), findsNothing);
  });
}
