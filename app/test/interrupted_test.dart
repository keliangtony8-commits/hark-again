// v1.52 崩溃恢复：服务器重启打断的回复（status=interrupted）——解析、行尾说明（和“已停止”区分）、导出、
// 结果未知的步骤显示服务器给的说明。
import 'package:assistant/features/chat/activity_view.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/export.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _note = '服务器重启时它还在跑，结果没记下来，可能已经执行了一部分';

Map<String, dynamic> _json(String? status) => {
      'id': 'm1',
      'role': 'assistant',
      'blocks': [
        {'type': 'text', 'text': '开始装。'}
      ],
      'status': ?status,
      'steps': [
        {
          'id': 'a', 'tool': 'run_command', 'title': '运行命令', 'detail': 'pip install x', 'state': 'stopped',
          'at': '2026-10-12T11:00:00+00:00', 'note': _note, 'code': 'TOOL_OUTCOME_UNKNOWN'
        }
      ],
    };

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SingleChildScrollView(child: SizedBox(width: 400, child: MessageView(m)))),
      ),
    );

void main() {
  test('解析：interrupted / stopped / 完整 三种', () {
    final cut = Message.fromJson(_json('interrupted'));
    expect(cut.interrupted, isTrue);
    expect(cut.stopped, isFalse);
    expect(cut.cutShort, isTrue);
    expect(cut.endLabel, '服务器重启，回答被打断');
    expect(cut.copyWith(pending: false).interrupted, isTrue); // copyWith 不丢
    final stopped = Message.fromJson(_json('stopped'));
    expect(stopped.endLabel, '已停止');
    expect(stopped.interrupted, isFalse);
    final done = Message.fromJson(_json(null));
    expect(done.cutShort, isFalse);
    expect(done.endLabel, isNull);
    expect(cut.steps.single.state, ActivityState.stopped);
    expect(cut.steps.single.note, _note);
    expect(conversationMarkdown('t', [cut]), contains('开始装。\n\n*（服务器重启，回答被打断）*'));
    expect(conversationMarkdown('t', [stopped]), contains('*（已停止）*'));
  });

  testWidgets('界面：行尾标“服务器重启，回答被打断”，展开步骤看到结果未知的说明', (tester) async {
    await tester.pumpWidget(_host(Message.fromJson(_json('interrupted'))));
    await tester.pumpAndSettle();
    expect(find.text('服务器重启，回答被打断'), findsOneWidget);
    expect(find.text('已停止'), findsNothing);
    expect(find.byIcon(Icons.power_off_outlined), findsOneWidget);
    await tester.tap(find.byType(StepCapsule));
    await tester.pumpAndSettle();
    expect(find.text(_note), findsOneWidget);
  });

  testWidgets('界面：用户停止的仍是“已停止”', (tester) async {
    await tester.pumpWidget(_host(Message.fromJson(_json('stopped'))));
    await tester.pumpAndSettle();
    expect(find.text('已停止'), findsOneWidget);
    expect(find.byIcon(Icons.power_off_outlined), findsNothing);
  });
}
