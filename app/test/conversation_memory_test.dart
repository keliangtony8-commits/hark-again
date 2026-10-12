// 对话记忆卡：解析容错 + 措辞；卡片显示原文占比 / 摘要覆盖；展开摘要；“整理上文”发 POST、原地换新值并提示；
// 正在回复（409）把后端原因转述；没什么可整理时按钮不可点；空对话不显示。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/chat/conversation_memory.dart';
import 'package:assistant/models/conversation_context.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> state({int summarized = 0, int raw = 8, int chars = 6000, int compactable = 6, String summary = ''}) => {
      'messages': summarized + raw,
      'summarized': summarized,
      'raw': raw,
      'raw_chars': chars,
      'budget': 24000,
      'summary': summary,
      'compactable': compactable,
    };

class FakeApi implements Api {
  Map<String, dynamic> body = state();
  Object? postResult;
  int posts = 0;

  @override
  Future<dynamic> get(String path) async => body;

  @override
  Future<dynamic> post(String path, [Object? b]) async {
    posts++;
    expect(path, '/api/conversations/c1/compact');
    final r = postResult;
    if (r is Exception) throw r;
    return r;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(body: SingleChildScrollView(child: ConversationMemoryCard(id: 'c1'))),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('解析容错与措辞', () {
    final c = ConversationContext.fromJson(state(summarized: 4, chars: 12345));
    expect(c.fill, closeTo(12345 / 24000, 1e-9));
    expect(c.tight, isFalse);
    expect(ConversationContext.fromJson(state(chars: 20000)).tight, isTrue);
    expect(contextLine(c), '最近 8 条原文 · 约 1.2 万字，上限 2.4 万字');
    expect(summaryLine(c), '更早的 4 条已压成摘要');
    expect(summaryLine(ConversationContext.fromJson(state())), isNull);
    // 字段类型不对（别的接口的数据）也不炸
    expect(ConversationContext.fromJson({'messages': [1, 2], 'summary': 3}).messages, 0);
    final before = ConversationContext.fromJson(state());
    expect(compactToast(before, CompactResult.fromJson({...state(summarized: 6, raw: 2), 'status': 'compressed', 'before': 6000, 'after': 900})),
        '已把 6 条较早消息压成摘要（约 6000 字 → 900 字）');
    expect(compactToast(before, CompactResult.fromJson({...state(), 'status': 'inflated'})), '摘要反而比原文长，保持原样');
    expect(compactToast(before, CompactResult.fromJson({...state(), 'status': 'noop'})), '已经很精简，没有可整理的');
  });

  testWidgets('整理上文：发请求、原地换新值、提示；展开摘要', (tester) async {
    final api = FakeApi()
      ..postResult = {...state(summarized: 6, raw: 2, chars: 800, compactable: 0, summary: '用户在做自建助手'), 'status': 'compressed', 'before': 6000, 'after': 816};
    await pump(tester, api);
    expect(find.text('对话记忆'), findsOneWidget);
    expect(find.text('25%'), findsOneWidget);
    expect(find.text('最近 8 条原文 · 约 6000 字，上限 2.4 万字'), findsOneWidget);
    expect(find.text('查看摘要'), findsNothing);

    await tester.tap(find.text('整理上文'));
    await tester.pumpAndSettle();
    expect(api.posts, 1);
    expect(find.text('已把 6 条较早消息压成摘要（约 6000 字 → 816 字）'), findsOneWidget);
    expect(find.text('最近 2 条原文 · 约 800 字，上限 2.4 万字'), findsOneWidget);
    expect(find.text('更早的 6 条已压成摘要'), findsOneWidget);
    expect(find.text('已经很精简'), findsOneWidget);
    final button = tester.widget<ButtonStyleButton>(find.ancestor(of: find.text('整理上文'), matching: find.bySubtype<ButtonStyleButton>()));
    expect(button.onPressed, isNull);

    await tester.tap(find.text('查看摘要'));
    await tester.pumpAndSettle();
    expect(find.text('用户在做自建助手'), findsOneWidget);
    await tester.tap(find.text('收起摘要'));
    await tester.pumpAndSettle();
    expect(find.text('用户在做自建助手'), findsNothing);
  });

  testWidgets('正在回复：转述 409 的原因，卡片不变', (tester) async {
    final api = FakeApi()..postResult = ApiError('正在回复，等这一轮结束再整理', 409);
    await pump(tester, api);
    await tester.tap(find.text('整理上文'));
    await tester.pumpAndSettle();
    expect(find.text('正在回复，等这一轮结束再整理'), findsOneWidget);
    expect(find.text('最近 8 条原文 · 约 6000 字，上限 2.4 万字'), findsOneWidget);
  });

  testWidgets('空对话不显示', (tester) async {
    final api = FakeApi()..body = state(raw: 0, chars: 0, compactable: 0);
    await pump(tester, api);
    expect(find.text('对话记忆'), findsNothing);
  });

  test('工作区规则：解析容错与措辞', () {
    final c = ConversationContext.fromJson({
      ...state(),
      'instructions': {
        'budget': 16384,
        'candidates': ['AGENTS.md', 'CLAUDE.md'],
        'files': [
          {'path': 'AGENTS.md', 'bytes': 2048, 'used': 2048, 'status': 'full'},
          {'path': 'AGENTS.local.md', 'bytes': 40000, 'used': 12000, 'status': 'truncated'},
          {'path': 'CLAUDE.md', 'bytes': 9, 'used': 0, 'status': 'omitted'},
          {'path': '', 'bytes': 1},
          'junk',
        ],
      },
    });
    expect(c.rules.enabled, isTrue);
    expect(c.rules.files.map((f) => f.path), ['AGENTS.md', 'AGENTS.local.md', 'CLAUDE.md']);
    expect(ruleStatus(c.rules.files[0]), '2 KB');
    expect(ruleStatus(c.rules.files[1]), '超出上限，只读了 12 KB / 39 KB');
    expect(ruleStatus(c.rules.files[2]), '超出上限，没有读');
    expect([for (final f in c.rules.files) f.cut], [false, true, true]);
    // 老后端没有这个字段 / 字段乱了 / 预算 0 = 关
    expect(ConversationContext.fromJson(state()).rules.enabled, isFalse);
    expect(ConversationContext.fromJson({...state(), 'instructions': 'x'}).rules.files, isEmpty);
    expect(ConversationContext.fromJson({...state(), 'instructions': {'budget': 0, 'files': []}}).rules.enabled, isFalse);
    expect(WorkspaceRule.fromJson({'path': 'a', 'status': '??'}).status, 'full');
  });

  testWidgets('工作区规则：有文件逐个列出', (tester) async {
    final api = FakeApi()
      ..body = {
        ...state(),
        'instructions': {
          'budget': 16384,
          'files': [
            {'path': 'AGENTS.md', 'bytes': 2048, 'used': 2048, 'status': 'full'},
            {'path': 'AGENTS.local.md', 'bytes': 40000, 'used': 12000, 'status': 'truncated'},
          ],
        },
      };
    await pump(tester, api);
    expect(find.text('工作区规则'), findsOneWidget);
    expect(find.text('AGENTS.md'), findsOneWidget);
    expect(find.text('超出上限，只读了 12 KB / 39 KB'), findsOneWidget);
    expect(find.bySemanticsLabel('规则文件 AGENTS.md，2 KB'), findsOneWidget);
    expect(find.text(rulesHint), findsNothing);
  });

  testWidgets('工作区规则：没有文件给引导', (tester) async {
    final empty = FakeApi()..body = {...state(), 'instructions': {'budget': 16384, 'files': []}};
    await pump(tester, empty);
    expect(find.text(rulesHint), findsOneWidget);
  });

  testWidgets('工作区规则：预算 0 不显示', (tester) async {
    final off = FakeApi()..body = {...state(), 'instructions': {'budget': 0, 'files': []}};
    await pump(tester, off);
    expect(find.text('工作区规则'), findsNothing);
  });

  testWidgets('工作区规则：窄屏长路径不溢出', (tester) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeApi()
      ..body = {
        ...state(),
        'instructions': {
          'budget': 16384,
          'files': [
            {'path': 'AGENTS.local.md', 'bytes': 400000, 'used': 12000, 'status': 'truncated'},
          ],
        },
      };
    await pump(tester, api);
    expect(tester.takeException(), isNull);
  });
}
