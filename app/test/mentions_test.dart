// 输入框 @文件（v1.79，features/chat/mentions.dart）：规则（何时算在打 @、排序、补全文字、带空格的路径加引号）
// + 输入框里打 @ 出候选、边打边筛、点一下补成 `@路径 `、邮箱不弹、!命令 不弹；@子助手（v1.91）没有工作区也列。
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/features/chat/mentions.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/projects/p1/files') {
      return [
        {'path': 'notes/大纲.md', 'name': '大纲.md', 'size': 2048, 'mime': 'text/markdown', 'modified': 100},
        {'path': 'plan.md', 'name': 'plan.md', 'size': 10, 'mime': 'text/markdown', 'modified': 50},
        {'path': 'src/planner.py', 'name': 'planner.py', 'size': 10, 'mime': 'text/x-python', 'modified': 200},
        {'path': 'my notes.txt', 'name': 'my notes.txt', 'size': 3, 'mime': 'text/plain', 'modified': 10},
      ];
    }
    if (path == '/api/catalog/skills') {
      return [
        {'id': 'web-research', 'name': '网页调研', 'description': '查资料时用', 'body': '', 'builtin': true},
        {'id': 'writing', 'name': '写作', 'description': '润色文字', 'body': '', 'builtin': true},
        {'id': 'off', 'name': '停用的', 'description': '', 'body': '', 'builtin': false, 'enabled': false},
      ];
    }
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

ProjectFile _f(String path, {int t = 0}) =>
    ProjectFile(path: path, name: path.split('/').last, size: 1, mime: 'text/plain', modified: DateTime.fromMillisecondsSinceEpoch(t));

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<List<String>> _pump(WidgetTester tester, {String? workspace = 'p1'}) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final sent = <String>[];
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api()), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: Composer(workspace: workspace, busy: false, onSend: (t, _) => sent.add(t)),
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

Skill _s(String id, String name, {String desc = '', bool on = true}) =>
    Skill(id: id, name: name, description: desc, body: '', builtin: false, enabled: on);

void main() {
  test(r'$技能：开头 / 空格后 / 中文后算；US$5、$$ 不算；只认传进来的符号', () {
    const both = {fileSigil, skillSigil};
    expect(mentionAt(r'$', 1, sigils: both), const MentionQuery(0, 1, '', sigil: skillSigil));
    expect(mentionAt(r'按$wr', 4, sigils: both), const MentionQuery(1, 4, 'wr', sigil: skillSigil));
    expect(mentionAt(r'US$5', 4, sigils: both), isNull);
    expect(mentionAt(r'$$w', 3, sigils: both), isNull);
    expect(mentionAt(r'$wr', 3), isNull); // 默认只认 @
    expect(mentionAt(r'$wr 好', 5, sigils: both), isNull);
    expect(applyMention(r'按$wr', const MentionQuery(1, 4, 'wr', sigil: skillSigil), 'writing'), (r'按$writing ', 10));
  });

  test('技能排序：id / 名字开头 > 包含 > 描述包含；停用的不列；同分保持原顺序', () {
    final skills = [_s('b-write', '改写'), _s('writing', '写作'), _s('x', '杂项', desc: '写邮件 writing'), _s('w-off', '停', on: false)];
    expect(rankSkills(skills, 'writ').map((s) => s.id), ['writing', 'b-write', 'x']);
    expect(rankSkills(skills, '写').map((s) => s.id), ['writing', 'b-write', 'x']);
    expect(rankSkills(skills, '').map((s) => s.id), ['b-write', 'writing', 'x']);
    expect(rankSkills(skills, 'zzz'), isEmpty);
  });

  test('何时算在打 @：开头 / 空格后 / 中文后算；邮箱、标点隔开、光标不在后面不算', () {
    expect(mentionAt('@', 1), const MentionQuery(0, 1, ''));
    expect(mentionAt('看看@pl', 5), const MentionQuery(2, 5, 'pl'));
    expect(mentionAt('a @notes/x', 10), const MentionQuery(2, 10, 'notes/x'));
    expect(mentionAt('mail a@b', 8), isNull);
    expect(mentionAt('@plan 然后', 9), isNull);
    expect(mentionAt('@plan，然后', 8), isNull);
    expect(mentionAt('@plan', 3), const MentionQuery(0, 3, 'pl'));
    expect(mentionAt('没有', 2), isNull);
    expect(mentionAt('x', 5), isNull);
  });

  test('排序：文件名开头 > 包含 > 路径包含 > 按顺序出现；同分新的在前；空查询 = 最近改的', () {
    final files = [_f('a/plan.md', t: 1), _f('src/planner.py', t: 2), _f('my-plan.txt', t: 3), _f('plans/x.md', t: 4), _f('p-l-a-n.md', t: 5), _f('zzz.md', t: 6)];
    expect(rankMentions(files, 'plan', max: 10).map((f) => f.path), ['src/planner.py', 'a/plan.md', 'my-plan.txt', 'plans/x.md', 'p-l-a-n.md']);
    expect(rankMentions(files, 'PLAN', max: 2).map((f) => f.path), ['src/planner.py', 'a/plan.md']);
    expect(rankMentions(files, '').first.path, 'zzz.md');
    expect(rankMentions(files, '').length, mentionMax);
    expect(rankMentions(files, 'qq'), isEmpty);
  });

  test('补全：换掉正在打的 @xxx，后面补一个空格；带空格的路径加引号', () {
    expect(applyMention('看看@pl', const MentionQuery(2, 5, 'pl'), 'plan.md'), ('看看@plan.md ', 11));
    expect(applyMention('@pl 再说', const MentionQuery(0, 3, 'pl'), 'plan.md'), ('@plan.md 再说', 9));
    expect(mentionToken('my notes.txt'), '@"my notes.txt"');
    expect(mentionToken('notes/大纲.md'), '@notes/大纲.md');
  });

  testWidgets('打 @ 出候选、边打边筛、点一下补成 @路径 并发出原文', (tester) async {
    final sent = await _pump(tester);
    expect(find.byType(MentionList), findsNothing);
    await _type(tester, '看看@');
    expect(find.byType(MentionList), findsOneWidget);
    expect(find.text('子助手'), findsOneWidget); // 刚打 @：子助手在第一行
    expect(find.text('planner.py'), findsOneWidget);
    expect(find.text('大纲.md'), findsOneWidget);
    await _type(tester, '看看@大');
    expect(find.text('planner.py'), findsNothing);
    await tester.tap(find.text('大纲.md'));
    await _settle(tester);
    expect(find.byType(MentionList), findsNothing);
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, '看看@notes/大纲.md ');
    await tester.tap(find.bySemanticsLabel('发送'));
    await _settle(tester);
    expect(sent, ['看看@notes/大纲.md ']);
  });

  testWidgets('对不上：一行说明；邮箱 / !命令 不弹', (tester) async {
    await _pump(tester);
    await _type(tester, '@qqq');
    expect(find.textContaining('没有对得上的文件'), findsOneWidget);
    await _type(tester, '发到 a@b');
    expect(find.byType(MentionList), findsNothing);
    await _type(tester, '!cat @pl');
    expect(find.byType(MentionList), findsNothing);
  });

  testWidgets('没有工作区（首页快捷输入框）：@ 只列子助手，对不上给一行说明', (tester) async {
    final sent = await _pump(tester, workspace: null);
    await _type(tester, '@pl');
    expect(find.textContaining('打 @子助手'), findsOneWidget);
    expect(find.text('plan.md'), findsNothing);
    await _type(tester, '@子');
    await tester.tap(find.text('子助手'));
    await _settle(tester);
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, '@子助手 ');
    await _type(tester, '@子助手 查三家价格');
    await tester.tap(find.bySemanticsLabel('发送'));
    await _settle(tester);
    expect(sent, ['@子助手 查三家价格']);
  });

  test('子助手：候选匹配与消息里认不认（同服务器 agent_mentions）', () {
    expect(agentMatches(''), isTrue);
    expect(agentMatches('子'), isTrue);
    expect(agentMatches('AG'), isTrue);
    expect(agentMatches('sub'), isTrue);
    expect(agentMatches('pl'), isFalse);
    expect(mentionsAgent('@子助手 查'), isTrue);
    expect(mentionsAgent('请@agent。'), isTrue);
    expect(mentionsAgent('@SubAgent go'), isTrue);
    expect(mentionsAgent('me@agent.com'), isFalse);
    expect(mentionsAgent('@agent.md'), isFalse);
    expect(mentionsAgent('@agents'), isFalse);
    expect(mentionsAgent('`@agent`'), isFalse);
    expect(mentionsAgent('没有'), isFalse);
  });

  testWidgets(r'打 $ 出技能（没有工作区也行）、停用的不列、点一下补成 $id；!命令 不弹', (tester) async {
    final sent = await _pump(tester, workspace: null);
    await _type(tester, r'帮我$');
    expect(find.byType(MentionList), findsOneWidget);
    expect(find.text('网页调研'), findsOneWidget);
    expect(find.text('停用的'), findsNothing);
    await _type(tester, r'帮我$写');
    expect(find.text('网页调研'), findsNothing);
    await tester.tap(find.text('写作'));
    await _settle(tester);
    expect(find.byType(MentionList), findsNothing);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, r'帮我$writing ');
    await tester.tap(find.bySemanticsLabel('发送'));
    await _settle(tester);
    expect(sent, [r'帮我$writing ']);
    await _type(tester, r'$qqq');
    expect(find.textContaining('没有对得上的技能'), findsOneWidget);
    await _type(tester, r'!echo $HO');
    expect(find.byType(MentionList), findsNothing);
  });
}
