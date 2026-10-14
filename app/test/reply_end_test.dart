// v1.56 回复怎么结束的（ReplyEnd）+ “继续”：解析五种 status、说明文案/图标、导出；
// 最后一条没正常说完的回复下有“继续”，点了就是发一句“继续”，发出后收起；正常说完的、不是最后一条的都没有。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/export.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/models/reply_end.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text, {String? status}) => {
      'id': id,
      'role': role,
      'blocks': [
        {'type': 'text', 'text': text}
      ],
      'status': ?status,
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

Future<(ProviderContainer, FakeSocket)> _chat(WidgetTester tester, List<dynamic> messages) async {
  final socket = FakeSocket();
  final container = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(_Api(messages)),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
  ));
  await container.read(chatProvider('').notifier).open('c1');
  await tester.pumpAndSettle();
  return (container, socket);
}

Widget _host(Message m, {VoidCallback? onContinue, double width = 400}) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(
            body: SingleChildScrollView(
                child: SizedBox(width: width, child: MessageView(m, onRegenerate: () {}, onSave: () {}, onContinue: onContinue)))),
      ),
    );

void main() {
  test('解析：五种 status，未知 / 缺省都是 done', () {
    expect(ReplyEnd.parse('wrapped'), ReplyEnd.wrapped);
    expect(ReplyEnd.parse('looped'), ReplyEnd.looped);
    expect(ReplyEnd.parse('interrupted'), ReplyEnd.interrupted);
    expect(ReplyEnd.parse('stopped'), ReplyEnd.stopped);
    expect(ReplyEnd.parse(null), ReplyEnd.done);
    expect(ReplyEnd.parse('weird'), ReplyEnd.done); // 新服务器多出来的值：老 App 当正常说完
    final m = Message.fromJson(_msg('a', 'assistant', 'x', status: 'wrapped'));
    expect(m.end, ReplyEnd.wrapped);
    expect(m.copyWith(pending: false).end, ReplyEnd.wrapped); // copyWith 不丢
    expect(m.cutShort, isFalse); // 内容完整，只是事没做完
    expect(m.stopped || m.interrupted, isFalse);
  });

  test('规则：哪些能继续、哪些算半截、哪些用警示色', () {
    expect(ReplyEnd.values.where((e) => e.continuable), [ReplyEnd.stopped, ReplyEnd.interrupted, ReplyEnd.wrapped, ReplyEnd.looped]);
    expect(ReplyEnd.values.where((e) => e.cutShort), [ReplyEnd.stopped, ReplyEnd.interrupted]);
    expect(ReplyEnd.values.where((e) => e.warn), [ReplyEnd.interrupted, ReplyEnd.looped]);
    expect(ReplyEnd.done.label, isNull);
    expect(ReplyEnd.wrapped.label, '步数用完，先停在这里');
    expect(ReplyEnd.looped.label, '原地打转，先停下了');
    expect(ReplyEnd.looped.continueHint, contains('换个做法'));
    expect(replyEndIcon(ReplyEnd.wrapped), Icons.hourglass_bottom_rounded);
    expect(replyEndIcon(ReplyEnd.looped), Icons.sync_problem_rounded);
    expect(continueText, '继续');
  });

  test('导出：预算用完的回复带说明', () {
    final m = Message.fromJson(_msg('a', 'assistant', '做了一半', status: 'wrapped'));
    expect(conversationMarkdown('t', [m]), contains('*（步数用完，先停在这里）*'));
  });

  testWidgets('MessageView：行尾说明 + 继续；点了回调一次；不给回调就没有按钮', (tester) async {
    var n = 0;
    await tester.pumpWidget(_host(Message.fromJson(_msg('a', 'assistant', '还差一步', status: 'wrapped')), onContinue: () => n++));
    await tester.pumpAndSettle();
    expect(find.text('步数用完，先停在这里'), findsOneWidget);
    expect(find.byIcon(Icons.hourglass_bottom_rounded), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('继续'));
    await tester.pumpAndSettle();
    expect(n, 1);

    await tester.pumpWidget(_host(Message.fromJson(_msg('a', 'assistant', '还差一步', status: 'looped'))));
    await tester.pumpAndSettle();
    expect(find.text('原地打转，先停下了'), findsOneWidget);
    expect(find.bySemanticsLabel('继续'), findsNothing);
  });

  testWidgets('窄屏：说明太长省略，不溢出', (tester) async {
    await tester.pumpWidget(_host(Message.fromJson(_msg('a', 'assistant', '半截', status: 'interrupted')), onContinue: () {}, width: 260));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.bySemanticsLabel('继续'), findsOneWidget);
  });

  testWidgets('ChatView：最后一条预算用完 → 继续 → 发一句“继续”，发出后按钮收起', (tester) async {
    final (container, socket) = await _chat(tester, [_msg('u1', 'user', '部署'), _msg('a1', 'assistant', '做到第 3 步', status: 'wrapped')]);
    expect(find.bySemanticsLabel('继续'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('继续'));
    await tester.pumpAndSettle();
    final sent = socket.sent.where((e) => e['type'] == 'user.message').toList();
    expect(sent, hasLength(1));
    expect(sent.single['text'], '继续');
    expect(container.read(chatProvider('')).messages.last.isUser, isTrue);
    expect(find.bySemanticsLabel('继续'), findsNothing); // 最后一条变成用户消息、在等回复
  });

  testWidgets('ChatView：正常说完的没有继续', (tester) async {
    await _chat(tester, [_msg('u1', 'user', 'a'), _msg('a1', 'assistant', '好了')]);
    expect(find.bySemanticsLabel('继续'), findsNothing);
  });

  testWidgets('ChatView：不是最后一条的没正常说完，没有继续', (tester) async {
    await _chat(tester, [
      _msg('u1', 'user', 'a'), _msg('a1', 'assistant', '半截', status: 'stopped'),
      _msg('u2', 'user', 'b'), _msg('a2', 'assistant', '好了'),
    ]);
    expect(find.bySemanticsLabel('继续'), findsNothing);
    expect(find.text('已停止'), findsOneWidget); // 较早的半截回复仍常驻说明
  });
}
