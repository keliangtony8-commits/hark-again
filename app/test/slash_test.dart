// 输入框 /命令（v1.85，models/slash.dart；服务器 app/init_command.py）：规则（何时弹、候选、补全、/init 认法和服务器一致）
// + 输入框开头打 / 出候选、点一下补成 `/init `、顶部提示条（带补充要求）、句中 / 不弹、生成中不能当补充发。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/features/chat/mentions.dart';
import 'package:assistant/features/chat/slash_actions.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/models/slash.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async => const [];

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<List<String>> _pump(WidgetTester tester, {bool busy = false, List<SlashCall>? slashes}) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final sent = <String>[];
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: Composer(
              workspace: 'p1',
              busy: busy,
              streaming: busy,
              canSteer: busy,
              onStop: () {},
              onSend: (t, _) => sent.add(t),
              onSlash: slashes == null ? null : (c, _) => slashes.add(c)),
        ),
      ),
    ),
  ));
  await _settle(tester);
  return sent;
}

Future<void> _type(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await _settle(tester);
}

void main() {
  test('何时算在打 /：整段开头、只有字母、光标在最后', () {
    expect(slashQueryAt('/', 1), '');
    expect(slashQueryAt('/in', 3), 'in');
    expect(slashQueryAt('/IN', 3), 'in');
    expect(slashQueryAt(' /in', 4), isNull);
    expect(slashQueryAt('a/in', 4), isNull);
    expect(slashQueryAt('/init ', 6), isNull);
    expect(slashQueryAt('/in x', 3), isNull);
    expect(slashQueryAt('/src/a', 6), isNull);
    expect(slashQueryAt('', 0), isNull);
  });

  test('候选与补全', () {
    expect(rankSlash('').map((c) => c.name), ['init', 'new', 'compact', 'plan', 'copy', 'status']);
    expect(rankSlash('', local: false).map((c) => c.name), ['init']);
    expect(rankSlash('in').map((c) => c.name), ['init']);
    expect(rankSlash('c').map((c) => c.name), ['compact', 'copy']);
    expect(rankSlash('x'), isEmpty);
    expect(applySlash(initCommand), ('/init ', 6));
  });

  test('/init 认法和服务器 init_command.parse 一致', () {
    expect(initNoteOf('/init'), '');
    expect(initNoteOf('  /INIT  '), '');
    expect(initNoteOf('/Init\n重点写测试'), '重点写测试');
    expect(initNoteOf('/initial'), isNull);
    expect(initNoteOf('请 /init'), isNull);
    expect(initNoteOf(''), isNull);
    expect(initBarText(''), contains('生成 AGENTS.md'));
    expect(initBarText('写中文'), endsWith('补充：写中文'));
  });

  testWidgets('开头打 / 出候选，点一下补成 /init，提示条随补充要求变，发出原文', (tester) async {
    final sent = await _pump(tester);
    await _type(tester, '/');
    expect(find.byType(MentionList), findsOneWidget);
    expect(find.text('/init'), findsOneWidget);
    await tester.tap(find.text('/init'));
    await _settle(tester);
    expect(find.byType(MentionList), findsNothing);
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, '/init ');
    expect(find.text(initBarText('')), findsOneWidget);
    await _type(tester, '/init 写中文');
    expect(find.text(initBarText('写中文')), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('发送'));
    await _settle(tester);
    expect(sent, ['/init 写中文']);
  });

  testWidgets('句中的 / 和对不上的命令不弹', (tester) async {
    await _pump(tester);
    await _type(tester, '看看 /in');
    expect(find.byType(MentionList), findsNothing);
    await _type(tester, '/xyz');
    expect(find.byType(MentionList), findsNothing);
  });

  testWidgets('生成中：/init 不能当补充发（按钮不是“补充”）', (tester) async {
    await _pump(tester, busy: true);
    await _type(tester, '/init');
    expect(find.bySemanticsLabel('补充给正在进行的回答'), findsNothing);
    await _type(tester, '再短一点');
    expect(find.bySemanticsLabel('补充给正在进行的回答'), findsOneWidget);
  });

  test('本机命令认法（Codex：不接话的命令后面带了字 = 普通文字）', () {
    expect(slashOf('/new'), const SlashCall(newCommand, ''));
    expect(slashOf(' /COMPACT '), const SlashCall(compactCommand, ''));
    expect(slashOf('/new 帮我写诗'), isNull);
    expect(slashOf('/plan 先看看代码\n再说'), const SlashCall(planCommand, '先看看代码\n再说'));
    expect(slashOf('/newer'), isNull);
    expect(slashOf('/copy', local: false), isNull);
    expect(slashOf('/init 写中文', local: false), const SlashCall(initCommand, '写中文'));
    expect(slashOf('/init。'), isNull);
    expect(slashOf('看 /new'), isNull);
  });

  test('生成中能不能用 + 提示条文案', () {
    const plan = SlashCall(planCommand, '');
    expect(slashBlocked(plan, busy: true), isTrue);
    expect(slashBlocked(plan, busy: false), isFalse);
    expect(slashBlocked(const SlashCall(copyCommand, ''), busy: true), isFalse);
    expect(slashBarText(plan, busy: true), '计划模式 · 回答结束后再用');
    expect(slashBarText(const SlashCall(planCommand, '做个网站')), '计划模式 · 打开并发出去');
    expect(slashBarText(const SlashCall(initCommand, '写中文')), initBarText('写中文'));
    expect(slashBarText(const SlashCall(newCommand, '')), startsWith('新对话 · '));
    expect(slashSubtitle(newCommand, busy: true), endsWith('回答结束后再用'));
    expect(slashSubtitle(copyCommand, busy: true), '复制上一条回答');
  });

  test('/copy 取最近一条有内容的助手回答', () {
    Message m(String role, String text) =>
        Message.fromJson({'id': text, 'role': role, 'blocks': text.isEmpty ? [] : [{'type': 'text', 'text': text}]});
    expect(lastReplyText([m('user', '问'), m('assistant', '答一'), m('user', '再问'), m('assistant', '')]), '答一');
    expect(lastReplyText([m('user', '问')]), isNull);
    expect(lastReplyText(const []), isNull);
  });

  testWidgets('没有 onSlash 的输入框：本机命令不弹、当普通文字发', (tester) async {
    final sent = await _pump(tester);
    await _type(tester, '/');
    expect(find.text('/new'), findsNothing);
    await _type(tester, '/new');
    await tester.tap(find.bySemanticsLabel('发送'));
    await _settle(tester);
    expect(sent, ['/new']);
  });

  testWidgets('点不接话的本机命令直接执行；/plan 补成 /plan 、接话发出去走 onSlash', (tester) async {
    final calls = <SlashCall>[];
    final sent = await _pump(tester, slashes: calls);
    await _type(tester, '/co');
    expect(find.text('/compact'), findsOneWidget);
    await tester.tap(find.text('/copy'));
    await _settle(tester);
    expect(calls, [const SlashCall(copyCommand, '')]);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '');
    await _type(tester, '/pl');
    await tester.tap(find.text('/plan'));
    await _settle(tester);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '/plan ');
    await _type(tester, '/plan 先出方案');
    expect(find.text('计划模式 · 打开并发出去'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('执行 /plan'));
    await _settle(tester);
    expect(calls.last, const SlashCall(planCommand, '先出方案'));
    expect(sent, isEmpty);
  });

  testWidgets('生成中：/copy 能执行（停止钮让位），/new 灰掉并提示回答结束后再用', (tester) async {
    final calls = <SlashCall>[];
    await _pump(tester, busy: true, slashes: calls);
    await _type(tester, '/new');
    expect(find.text('新对话 · 回答结束后再用'), findsOneWidget);
    expect(find.bySemanticsLabel('停止生成'), findsOneWidget);
    await _type(tester, '/copy');
    expect(find.bySemanticsLabel('停止生成'), findsNothing);
    await tester.tap(find.bySemanticsLabel('执行 /copy'));
    await _settle(tester);
    expect(calls, [const SlashCall(copyCommand, '')]);
    await _type(tester, '/');
    expect(find.text('新对话 · 回答结束后再用'), findsOneWidget);
  });
}
