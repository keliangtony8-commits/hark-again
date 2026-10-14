// 反馈（v2.64）：纯规则（解析、副标题、提示、入口副标题）+ 回复下的 👍 / 👎（点 👍 记 good、再点取消；
// 👎 弹原因单，没选原因不能提交，选了带补充提交；已经 👎 再点 = 取消；失败提示）+ 反馈页（分组、计数、报告问题、详情复制/标已解决）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/reply_rating.dart';
import 'package:assistant/ui/sheets.dart';
import 'package:assistant/features/me/feedback_screen.dart';
import 'package:assistant/models/feedback.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://me.example', token: 't');
}

final _now = DateTime.now().toUtc();
Map<String, dynamic> _f(String id, String kind, String label, {String status = 'open', String excerpt = '', String? mid}) => {
      'id': id, 'kind': kind, 'kind_label': label, 'excerpt': excerpt, 'status': status, 'message_id': mid,
      'conversation_id': mid == null ? null : 'c1', 'created_at': _now.subtract(const Duration(hours: 3)).toIso8601String(),
    };

class FakeApi implements Api {
  FakeApi(this.items);
  List<Map<String, dynamic>> items;
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/feedback') {
      return {'items': items, 'open': items.where((x) => x['status'] == 'open' && x['kind'] != 'good').length};
    }
    final id = path.split('/').last;
    final x = items.firstWhere((x) => x['id'] == id);
    return {...x, 'note': '', 'markdown': '# 反馈：${x['kind_label']}\n\n## 提问\n\n${x['excerpt']}\n', 'snapshot': {}};
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    bodies.add(body);
    items = [_f('n${items.length}', 'problem', '问题报告', excerpt: '${(body as Map)['note']}'), ...items];
    return items.first;
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    calls.add('PATCH $path');
    final id = path.split('/').last;
    items = [for (final x in items) x['id'] == id ? {...x, 'status': (body as Map)['status']} : x];
    return items.firstWhere((x) => x['id'] == id);
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    items = [for (final x in items) if ('/api/feedback/${x['id']}' != path) x];
    return {'ok': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pumpScreen(WidgetTester tester, FakeApi api, Widget home) async {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: home),
  ));
  await tester.pumpAndSettle();
}

class _Rated extends StatefulWidget {
  const _Rated({required this.log, this.fail = false});
  final List<(String?, String?)> log;
  final bool fail;
  @override
  State<_Rated> createState() => _RatedState();
}

class _RatedState extends State<_Rated> {
  String? current;
  @override
  Widget build(BuildContext context) => Scaffold(
        // §I：评价在长按回复的动作菜单里；这里用一颗按钮打开同一份菜单
        body: Center(
          child: Builder(
            builder: (context) => TextButton(
              onPressed: () => showActionSheet<void>(context,
                  actions: ratingActions(context, (k, {note}) async {
                    widget.log.add((k, note));
                    if (widget.fail) throw ApiError('服务器出错了', 500);
                    setState(() => current = k);
                  }, current)),
              child: const Text('菜单'),
            ),
          ),
        ),
      );
}

void main() {
  test('rules', () {
    final now = DateTime(2026, 10, 14, 12);
    final l = FeedbackList.fromJson({
      'items': [
        {'id': 'a', 'kind': 'wrong', 'kind_label': '答错了', 'excerpt': '查快递', 'status': 'open', 'message_id': 'm1', 'conversation_id': 'c1', 'project_id': 'p1',
          'created_at': DateTime(2026, 10, 14, 9).toUtc().toIso8601String()},
        {'id': 'b', 'kind': 'good', 'kind_label': '有用', 'excerpt': '', 'status': 'resolved'},
      ],
      'open': 1,
    });
    expect(l.open, 1);
    expect(l.items.first.projectId, 'p1');
    expect(feedbackLine(l.items.first, now: now), startsWith('答错了 · '));
    expect(feedbackLine(l.items.last, now: now), '有用 · 已解决');
    expect(l.items.last.good, isTrue);
    expect(isBadFeedback('stuck'), isTrue);
    expect(isBadFeedback('good'), isFalse);
    expect(isBadFeedback(null), isFalse);
    expect(feedbackToast(null), '已取消评价');
    expect(feedbackToast('good'), '谢谢，记下了');
    expect(feedbackToast('wrong'), contains('我的 → 反馈'));
    expect(feedbackRowSubtitle(null), '报告问题，回看评价过的回复');
    expect(feedbackRowSubtitle(l), '1 条没解决');
    expect(FeedbackList.fromJson(null).items, isEmpty);
    // 消息带评价，copyWith 能设能清
    final m = Message.fromJson({'id': 'm', 'role': 'assistant', 'blocks': [], 'feedback': 'wrong'});
    expect(m.feedback, 'wrong');
    expect(m.copyWith(feedback: () => null).feedback, isNull);
    expect(m.copyWith().feedback, 'wrong');
    expect([for (final (k, _) in feedbackReasons) k], ['wrong', 'incomplete', 'stuck', 'other']);
  });

  testWidgets('有用可取消，不好要原因（长按菜单里的两项）', (tester) async {
    final log = <(String?, String?)>[];
    await tester.pumpWidget(MaterialApp(theme: buildTheme(Brightness.light), home: _Rated(log: log)));
    Future<void> pick(String label) async {
      await tester.tap(find.text('菜单'));
      await tester.pumpAndSettle();
      await tester.tap(find.text(label));
      await tester.pumpAndSettle();
    }

    await pick('有用');
    expect(log.last, ('good', null));
    expect(find.text('谢谢，记下了'), findsOneWidget);
    await tester.tap(find.text('菜单'));
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.thumb_up_alt_rounded), findsOneWidget); // 已评过：实心 + “取消”
    await tester.tap(find.text('取消“有用”'));
    await tester.pumpAndSettle();
    expect(log.last, (null, null));

    await pick('不好');
    expect(find.text('哪里不好？'), findsOneWidget);
    final submit = find.widgetWithText(FilledButton, '提交');
    expect(tester.widget<FilledButton>(submit).onPressed, isNull); // 没选原因
    await tester.tap(find.byKey(const ValueKey('reason-incomplete')));
    await tester.pump();
    await tester.enterText(find.byType(TextField), '  只做了一半  ');
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(log.last, ('incomplete', '只做了一半'));

    await pick('取消评价'); // 已经不好：再点 = 取消，不弹原因单
    expect(log.last, (null, null));
    expect(find.text('哪里不好？'), findsNothing);
  });

  testWidgets('failure shows a toast', (tester) async {
    final log = <(String?, String?)>[];
    await tester.pumpWidget(MaterialApp(theme: buildTheme(Brightness.light), home: _Rated(log: log, fail: true)));
    await tester.tap(find.text('菜单'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('有用'));
    await tester.pumpAndSettle();
    expect(find.text('服务器出错了'), findsOneWidget);
  });

  testWidgets('feedback screen groups, reports, details', (tester) async {
    final api = FakeApi([
      _f('a', 'wrong', '答错了', excerpt: '帮我查顺丰', mid: 'm1'),
      _f('b', 'good', '有用', excerpt: '订了明早的车', mid: 'm2'),
      _f('c', 'problem', '问题报告', excerpt: '语音没反应', status: 'resolved'),
    ]);
    await pumpScreen(tester, api, const FeedbackScreen());
    expect(find.text('1 条待处理'), findsOneWidget);
    for (final t in ['待处理', '有用的回复', '已解决', '帮我查顺丰', '订了明早的车', '语音没反应']) {
      expect(find.text(t), findsOneWidget, reason: t);
    }

    await tester.tap(find.byTooltip('报告问题'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '首页卡片不刷新');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, '提交'));
    await tester.pumpAndSettle();
    expect(api.bodies.last, {'note': '首页卡片不刷新'});
    expect(find.text('首页卡片不刷新'), findsOneWidget);
    expect(find.text('2 条待处理'), findsOneWidget);
  });

  testWidgets('detail copies the report and resolves', (tester) async {
    final api = FakeApi([_f('a', 'wrong', '答错了', excerpt: '帮我查顺丰', mid: 'm1')]);
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String?;
      return null;
    });
    await pumpScreen(tester, api, const FeedbackDetailScreen(id: 'a'));
    expect(find.text('还没解决'), findsOneWidget);
    await tester.tap(find.text('复制报告'));
    await tester.pumpAndSettle();
    expect(copied, contains('# 反馈：答错了'));
    await tester.tap(find.text('标为已解决'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('PATCH /api/feedback/a'));
    expect(find.text('已解决'), findsOneWidget);
    expect(find.text('重新打开'), findsOneWidget);
  });
}
