// 计划模式（v1.71，后端 app/plan_mode.py）：方案卡解析与显示规则；卡片——等批准时两个按钮走 onApproval、
// 有结果后按钮收起、默认收成一行可展开、长方案“展开全部”；controller——打开对话取 mode、开关随模型选择 PATCH、
// 新对话随第一条消息带 mode、conversation.mode 事件把钮关掉；输入框计划钮开 / 关。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/plan_review.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

PlanReviewBlock _card({String state = 'pending', String? plan}) => Block.fromJson({
      'type': 'plan_review',
      'id': 'r1',
      'title': '改 a.txt',
      'plan': plan ?? '# 改 a.txt\n\n## 概要\n把原文改成新文\n\n## 验证\ncat a.txt',
      'state': state,
    }) as PlanReviewBlock;

Future<void> _show(WidgetTester t, PlanReviewBlock b, {void Function(String, bool)? reply}) => t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: BlockActions(
          onApproval: reply,
          child: Padding(padding: const EdgeInsets.all(16), child: SingleChildScrollView(child: BlockView(b))),
        ),
      ),
    ));

class _Api implements Api {
  String mode = 'plan';
  final patches = <Map<String, dynamic>>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/catalog/models') {
      return {'default': 'fast', 'models': [{'id': 'fast', 'label': '快速'}, {'id': 'smart', 'label': '深度'}]};
    }
    if (path.startsWith('/api/conversations/')) {
      return {'id': 'c1', 'mode': mode, 'messages': [{'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '嗨'}]}]};
    }
    if (path.startsWith('/api/conversations')) {
      return [{'id': 'c1', 'title': '旧对话', 'mode': 'plan', 'updated_at': 'Sun 2026-10-11 12:00 AM CST (UTC+08:00)'}];
    }
    return null;
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    patches.add((body as Map).cast<String, dynamic>());
    return {'id': 'c1'};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle() async {
  for (var i = 0; i < 8; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test('规则', () {
    final b = _card();
    expect(b.pending, isTrue);
    expect(standsAlone(b), isTrue);
    expect(planReviewLabel(b), '等你批准');
    expect(planReviewBody(b).startsWith('## 概要'), isTrue); // 去掉与卡头相同的 # 标题
    expect(planReviewBody(_card(plan: '# 别的\n内容')), '# 别的\n内容');
    expect(planReviewLong(b), isFalse);
    expect(planReviewLong(_card(plan: '# 改 a.txt\n${List.filled(20, '- 一步').join('\n')}')), isTrue);
    expect(planReviewCollapsedByDefault(b), isFalse);
    expect(planReviewCollapsedByDefault(_card(state: 'approved')), isTrue);
    expect(planReviewLabel(_card(state: 'rejected')), '要改');
    expect(planReviewHint(_card(state: 'approved')), contains('退出计划模式'));
    expect(planReviewSemantics(b), contains('方案：改 a.txt'));
    expect(ConversationSummary.fromJson({'id': 'x', 'mode': 'plan'}).planMode, isTrue);
    expect(ConversationSummary.fromJson({'id': 'x'}).planMode, isFalse);
    expect(ConversationSummary.fromJson({'id': 'x', 'mode': 'plan'}).withTitle('t').planMode, isTrue);
  });

  testWidgets('等批准：正文 + 两个按钮走 onApproval；有结果后按钮收起、卡片收成一行可展开', (t) async {
    final replies = <(String, bool)>[];
    await _show(t, _card(), reply: (id, ok) => replies.add((id, ok)));
    await t.pumpAndSettle();
    expect(find.text('改 a.txt'), findsOneWidget);
    expect(find.text('把原文改成新文'), findsOneWidget);
    await t.tap(find.text('批准，开始执行'));
    await t.tap(find.text('再改改'));
    expect(replies, [('r1', true), ('r1', false)]);
    await _show(t, _card(state: 'approved'), reply: (id, ok) => replies.add((id, ok)));
    await t.pumpAndSettle();
    expect(find.text('已批准'), findsOneWidget);
    expect(find.text('批准，开始执行'), findsNothing);
    expect(find.text('把原文改成新文'), findsNothing); // 收起
    await t.tap(find.text('改 a.txt'));
    await t.pumpAndSettle();
    expect(find.text('把原文改成新文'), findsOneWidget);
  });

  testWidgets('长方案先露一截，“展开全部”切换', (t) async {
    await _show(t, _card(plan: '# 改 a.txt\n${List.generate(30, (i) => '- 第$i步').join('\n')}'), reply: (_, _) {});
    await t.pumpAndSettle();
    expect(find.text('展开全部'), findsOneWidget);
    await t.tap(find.text('展开全部'));
    await t.pumpAndSettle();
    expect(find.text('收起'), findsOneWidget);
  });

  test('controller：打开取 mode；开关 PATCH；conversation.mode 关掉；新对话随消息带 mode', () async {
    final socket = FakeSocket();
    final api = _Api();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(api),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    c.listen(chatProvider(''), (_, _) {});
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    await ctl.open('c1');
    expect(c.read(chatProvider('')).planMode, isTrue);
    ctl.send('改好它');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': '旧对话'});
    socket.ctl.add({'type': 'conversation.mode', 'conversation_id': 'c1', 'mode': 'default'});
    await _settle();
    expect(c.read(chatProvider('')).planMode, isFalse);
    socket.ctl.add({'type': 'message.done', 'message': {'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '好'}]}});
    await _settle();
    await ctl.setPlanMode(true);
    expect(api.patches.last['mode'], 'plan');
    await ctl.setPlanMode(false);
    expect(api.patches.last['mode'], 'default');
    await ctl.open(null);
    expect(c.read(chatProvider('')).planMode, isFalse);
    await ctl.setPlanMode(true);
    ctl.send('先规划');
    await _settle();
    final sent = socket.sent.lastWhere((m) => m['type'] == 'user.message');
    expect(sent['mode'], 'plan');
  });

  testWidgets('输入框计划钮：关着只有图标，点开显示“计划”', (t) async {
    final socket = FakeSocket();
    final api = _Api()..mode = 'default';
    await t.pumpWidget(ProviderScope(
      overrides: [
        chatSocketProvider.overrideWithValue(socket),
        apiProvider.overrideWithValue(api),
        cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
      ],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    await t.pumpAndSettle();
    expect(find.byIcon(Icons.map_outlined), findsOneWidget);
    expect(find.text('计划'), findsNothing);
    await t.tap(find.bySemanticsLabel(RegExp('计划模式已关')));
    await t.pumpAndSettle();
    expect(find.text('计划'), findsOneWidget);
    expect(find.byIcon(Icons.map_rounded), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('计划模式已开')), findsOneWidget);
    await t.pump(const Duration(seconds: 5)); // toast 退场
  });
}
