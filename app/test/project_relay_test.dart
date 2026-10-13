// 跨项目转交（v2.23，服务器 app/project_relay.py）：origin / relay 块解析与文案；转交卡单独成卡；
// 卡片和“来自 X”标签在聊天页给了 onOpenConversation 时可点（回调带对话 + 项目），Home 上没给就不可点、没有箭头。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/skill_chip.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _show(WidgetTester t, Widget child, {void Function(String, String?)? onOpen}) => t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: BlockActions(onOpenConversation: onOpen, child: Padding(padding: const EdgeInsets.all(16), child: child))),
    ));

void main() {
  final relay = Block.fromJson({
    'type': 'relay', 'project_id': 'p1', 'name': '毕业论文', 'emoji': '🎓', 'conversation_id': 'c9',
    'text': '这是提纲初稿，帮我扩成三级目录。', 'files': ['提纲.md', '参考.pdf'], 'new_conversation': true,
  }) as RelayBlock;
  final origin = Block.fromJson({'type': 'origin', 'name': '主聊天', 'emoji': '💬', 'project_id': null, 'conversation_id': 'm1', 'depth': 1})
      as OriginBlock;

  test('解析与文案', () {
    expect(relay.projectId, 'p1');
    expect(relay.meta, '新开了一段对话 · 带了 提纲.md 等 2 个文件');
    expect((Block.fromJson({'type': 'relay', 'project_id': 'p', 'name': 'x', 'conversation_id': 'c', 'files': ['a.md']}) as RelayBlock).meta,
        '接在最近的对话里 · 带了 a.md');
    expect((Block.fromJson({'type': 'relay', 'project_id': 'p', 'name': 'x', 'conversation_id': 'c'}) as RelayBlock).meta, '接在最近的对话里');
    expect(origin.label, '来自 💬 主聊天');
    expect(origin.projectId, isNull);
    expect(origin.semantics, contains('点按打开原对话'));
    expect((Block.fromJson({'type': 'origin', 'name': '旅行'}) as OriginBlock).semantics, '旅行 转交来的消息');
    expect(standsAlone(relay), isTrue);
    expect(standsAlone(origin), isFalse);
    expect(plainText([origin, const TextBlock('你好')]), '你好');
  });

  testWidgets('转交卡：可点时回调带对话和项目', (t) async {
    String? id, pid;
    await _show(t, BlockView(relay), onOpen: (a, b) {
      id = a;
      pid = b;
    });
    expect(find.text('已交给 · 毕业论文'), findsOneWidget);
    expect(find.text('🎓'), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsOneWidget);
    await t.tap(find.text('已交给 · 毕业论文'));
    await t.pumpAndSettle();
    expect((id, pid), ('c9', 'p1'));
  });

  testWidgets('Home 上没有回调：不可点、没有箭头', (t) async {
    await _show(t, BlockView(relay));
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
    expect(find.bySemanticsLabel(RegExp('已交给项目 毕业论文')), findsOneWidget);
  });

  testWidgets('来自 X 标签：点一下回到来源对话（主聊天 = 项目为空）', (t) async {
    String? id;
    String? pid = 'x';
    await _show(t, OriginChip(origin), onOpen: (a, b) {
      id = a;
      pid = b;
    });
    expect(find.text('来自 💬 主聊天'), findsOneWidget);
    await t.tap(find.text('来自 💬 主聊天'));
    await t.pumpAndSettle();
    expect((id, pid), ('m1', null));
  });
}
