// 继续追问子助手（v1.97，服务器 agent/subagent_threads.py + agent_mentions.follow）：
// 规则（编号 / 第几轮解析、能不能追问、副标题加“第 n 轮”、气泡标签）；卡片：这一轮结束、带编号、聊天页给了 onFollowUp 才有“追问”，
// 点了弹输入框、发出去回调带编号 + 标题 + 问题；控制器：消息带追问标签、user.message 带 follow / follow_title，正在回答时排队等这一轮结束。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/skill_chip.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/delegate.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

DelegateBlock _d(List<Map<String, dynamic>> tasks, {bool live = false}) =>
    Block.fromJson({'type': 'delegate', 'tasks': tasks, 'live': live}) as DelegateBlock;

Future<void> _show(WidgetTester t, Widget child, {void Function(String, String, String)? onFollowUp}) => t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
          body: BlockActions(
              onFollowUp: onFollowUp, child: Padding(padding: const EdgeInsets.all(16), child: child))),
    ));

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) {
      return {
        'id': 'c1',
        'messages': [
          {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '查价格'}]},
          {'id': 'a1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '好'}]},
        ]
      };
    }
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle() async {
  for (var i = 0; i < 5; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test('规则：编号 / 轮次、能否追问、副标题、标签', () {
    final b = _d([
      {'id': 'sa_1a2b3c', 'title': '查价格', 'state': 'done', 'steps': 2, 'seconds': 5, 'result': '99 元', 'round': 2},
      {'id': 'sa_000001', 'title': '看评论', 'state': 'stopped'},
      {'title': '老卡', 'state': 'done', 'result': 'x'},
      {'id': 'sa_000002', 'title': '在做', 'state': 'running'},
    ]);
    expect(b.tasks[0].id, 'sa_1a2b3c');
    expect(b.tasks[0].round, 2);
    expect(b.tasks[2].round, 1);
    expect(delegateTaskLine(b.tasks[0]), '第 2 轮 · 2 步 · 5 秒');
    expect(delegateTaskLine(b.tasks[1]), '这一轮被停下了');
    expect([for (final t in b.tasks) delegateCanFollow(b, t)], [true, true, false, false]);
    expect([for (final t in b.tasks) delegateCanOpen(b, t)], [true, true, true, false]); // 被停的没结论也能展开（只有追问）
    final live = _d([{'id': 'sa_1a2b3c', 'title': 'a', 'state': 'done', 'result': 'x'}], live: true);
    expect(delegateCanFollow(live, live.tasks[0]), isFalse); // 这一轮还没结束
    expect(delegateSemantics(_d([{'id': 'sa_1a2b3c', 'title': 'a', 'state': 'done', 'steps': 1}])), '子助手，1 个都完成了；a，完成，1 步，可以追问');
    expect(delegateFollowTitle('查价格'), '追问「查价格」');

    final a = Block.fromJson({'type': 'agent', 'name': '子助手', 'target': 'sa_1a2b3c', 'title': '查价格'}) as AgentBlock;
    expect((a.target, a.title, a.gone), ('sa_1a2b3c', '查价格', false));
    expect(agentChipLabel(a), '追问 · 查价格');
    expect(agentChipSemantics(a), '追问子助手 查价格');
    final g = Block.fromJson({'type': 'agent', 'target': 'sa_1a2b3c', 'gone': true}) as AgentBlock;
    expect(agentChipLabel(g), '追问 · 子任务');
    expect(agentChipSemantics(g), contains('不在了'));
    const plain = AgentBlock();
    expect(agentChipLabel(plain), '子助手');
    expect(agentChipSemantics(plain), '交给子助手');
  });

  testWidgets('卡片：展开后“追问”→ 输入框 → 回调带编号、标题、问题', (t) async {
    final got = <(String, String, String)>[];
    await _show(t, BlockView(_d([{'id': 'sa_1a2b3c', 'title': '查价格', 'state': 'done', 'steps': 2, 'result': '最低 99 元'}])),
        onFollowUp: (id, title, text) => got.add((id, title, text)));
    await t.pumpAndSettle();
    expect(find.text('追问'), findsNothing);
    await t.tap(find.text('查价格'));
    await t.pumpAndSettle();
    expect(find.text('最低 99 元'), findsOneWidget);
    await t.tap(find.text('追问'));
    await t.pumpAndSettle();
    expect(find.text('追问「查价格」'), findsOneWidget);
    await t.enterText(find.byType(TextField), '  第四家的运费呢  ');
    await t.pump();
    await t.tap(find.widgetWithText(FilledButton, '发送'));
    await t.pumpAndSettle();
    expect(got, [('sa_1a2b3c', '查价格', '第四家的运费呢')]);
  });

  testWidgets('被停下的没结论也能追问；没给 onFollowUp（Home）/ 老卡片没编号：没有追问', (t) async {
    await _show(t, BlockView(_d([{'id': 'sa_000001', 'title': '看评论', 'state': 'stopped'}])), onFollowUp: (_, _, _) {});
    await t.pumpAndSettle();
    await t.tap(find.text('看评论'));
    await t.pumpAndSettle();
    expect(find.text('追问'), findsOneWidget);

    await _show(t, BlockView(_d([{'id': 'sa_000001', 'title': '看评论', 'state': 'stopped'}])));
    await t.pumpAndSettle();
    expect(find.byIcon(Icons.expand_more_rounded), findsNothing);
    await _show(t, BlockView(_d([{'title': '老卡', 'state': 'done', 'result': '结论'}])), onFollowUp: (_, _, _) {});
    await t.pumpAndSettle();
    await t.tap(find.text('老卡'));
    await t.pumpAndSettle();
    expect(find.text('结论'), findsOneWidget);
    expect(find.text('追问'), findsNothing);
  });

  testWidgets('气泡标签：追问 · 标题 / 断开图标', (t) async {
    await _show(t, const AgentChip(AgentBlock(target: 'sa_1a2b3c', title: '查价格')));
    expect(find.text('追问 · 查价格'), findsOneWidget);
    expect(find.byIcon(Icons.reply_rounded), findsOneWidget);
    await _show(t, const AgentChip(AgentBlock(target: 'sa_1a2b3c', title: '查价格', gone: true)));
    expect(find.byIcon(Icons.link_off_rounded), findsOneWidget);
  });

  test('控制器：追问消息带标签、线上带 follow；正在回答时排队，这一轮结束再发；编辑保留标签', () async {
    final socket = FakeSocket();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(_Api()),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.followUp('sa_1a2b3c', '查价格', '  运费呢 ');
    var sent = socket.sent.last;
    expect(sent['type'], 'user.message');
    expect(sent['text'], '运费呢');
    expect(sent['follow'], 'sa_1a2b3c');
    expect(sent['follow_title'], '查价格');
    expect(sent.containsKey('steer'), isFalse);
    final m = c.read(chatProvider('')).messages.last;
    expect(m.blocks.whereType<AgentBlock>().single.target, 'sa_1a2b3c');

    // 正在回答：不插进这一轮，排队
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't', 'turn_id': 'T', 'seq': 1});
    await _settle();
    final before = socket.sent.length;
    ctl.followUp('sa_1a2b3c', '查价格', '还有税呢');
    expect(socket.sent.length, before);
    socket.ctl.add({'type': 'message.done', 'turn_id': 'T', 'seq': 2,
      'message': {'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '运费 10 元'}]}});
    await _settle();
    sent = socket.sent.last;
    expect(sent['text'], '还有税呢');
    expect(sent['follow'], 'sa_1a2b3c');

    ctl.followUp('', '查价格', 'x'); // 没编号不发
    ctl.followUp('sa_1a2b3c', '查价格', '  ');
    expect(socket.sent.last['text'], '还有税呢');
  });
}
