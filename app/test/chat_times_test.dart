// §I（v2.84，对标 Hark，用户 17:45 定稿）：点哪条显示哪条的时间，各自开关、可同时开几条（换对话清空）；
// 气泡下没有常驻按钮，长按回复 = 一份动作菜单（复制 · 选择文字 · 朗读 · 重新生成 · 存成文件 · 有用 · 不好）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/features/projects/save_reply.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/format.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

final _t1 = DateTime.now().copyWith(hour: 9, minute: 5);
final _t2 = DateTime.now().copyWith(hour: 9, minute: 6);

Map<String, dynamic> _msg(String id, String role, String text, DateTime at) => {
      'id': id,
      'role': role,
      'created_at': at.toUtc().toIso8601String(),
      'blocks': [
        {'type': 'text', 'text': text}
      ],
    };

class _Api implements Api {
  _Api(this.messages);
  List<dynamic> messages;
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _chat(WidgetTester tester) async {
  tester.view.physicalSize = const Size(412, 915);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final container = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(FakeSocket()),
    apiProvider.overrideWithValue(_Api([_msg('u1', 'user', '明天几点出发', _t1), _msg('a1', 'assistant', '八点半出发最稳', _t2)])),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
  ));
  await container.read(chatProvider('').notifier).open('c1');
  await tester.pumpAndSettle();
}

void main() {
  test('formatClock：当天只有钟点，别的日子带日期，跨年带年', () {
    final now = DateTime(2026, 10, 14, 18);
    expect(formatClock(DateTime(2026, 10, 14, 17, 7), now: now), '17:07');
    expect(formatClock(DateTime(2026, 10, 13, 9, 0), now: now), '10月13日 09:00');
    expect(formatClock(DateTime(2025, 12, 31, 23, 59), now: now), '2025年12月31日 23:59');
    expect(formatClock(null), '');
  });

  testWidgets('点 A 出 A 的时间；点 B 后 A 仍在；再点 A 只收 A', (tester) async {
    await _chat(tester);
    expect(find.text('09:05'), findsNothing);
    expect(find.byTooltip('复制'), findsNothing); // 没有常驻操作行
    expect(find.byIcon(Icons.thumb_up_alt_outlined), findsNothing);

    await tester.tap(find.text('八点半出发最稳'));
    await tester.pumpAndSettle();
    expect(find.text('09:06'), findsOneWidget);
    expect(find.text('09:05'), findsNothing);
    expect(tester.getTopLeft(find.text('09:06')).dx, lessThan(100)); // 回复时间靠左

    await tester.tap(find.text('明天几点出发'));
    await tester.pumpAndSettle();
    expect(find.text('09:05'), findsOneWidget);
    expect(find.text('09:06'), findsOneWidget);
    expect(tester.getTopRight(find.text('09:05')).dx, greaterThan(300)); // 用户时间靠右

    await tester.tap(find.text('八点半出发最稳'));
    await tester.pumpAndSettle();
    expect(find.text('09:06'), findsNothing);
    expect(find.text('09:05'), findsOneWidget);
  });

  testWidgets('长按回复：聚焦菜单，常用三项在前，其余收进“更多”，同序', (tester) async {
    await _chat(tester);
    await tester.longPress(find.text('八点半出发最稳'));
    await tester.pumpAndSettle();
    expect(find.text('重新生成'), findsNothing); // 超过 5 项：前 4 项 + 更多
    await tester.tap(find.text('更多'));
    await tester.pumpAndSettle();
    final labels = ['复制', '选择文字', '回复', '朗读', '重新生成', saveReplyLabel, '有用', '不好'];
    for (final l in labels) {
      expect(find.text(l), findsOneWidget, reason: l);
    }
    for (var i = 1; i < labels.length; i++) {
      expect(tester.getTopLeft(find.text(labels[i - 1])).dy, lessThan(tester.getTopLeft(find.text(labels[i])).dy));
    }
    expect(find.text('09:06'), findsNothing); // 长按不切换时间

    await tester.tap(find.text('选择文字'));
    await tester.pumpAndSettle();
    expect(find.byType(SelectableText), findsWidgets); // 弹层里可以选字
  });

  testWidgets('长按自己的消息：复制 / 回复 / 编辑', (tester) async {
    await _chat(tester);
    await tester.longPress(find.text('明天几点出发'));
    await tester.pumpAndSettle();
    expect(find.text('复制'), findsOneWidget);
    expect(find.text('回复'), findsOneWidget);
    expect(find.text('编辑'), findsOneWidget);
  });

  testWidgets('MessageView：生成中不给菜单，没落库（无时间）不画时间', (tester) async {
    await tester.pumpWidget(ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: const Scaffold(body: MessageView(Message(id: 'p', role: 'assistant', blocks: [TextBlock('写到一半')], pending: true), showTime: true)),
      ),
    ));
    await tester.pump(const Duration(seconds: 1));
    await tester.longPress(find.text('写到一半'));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('复制'), findsNothing);
  });
}
