// 分享对话（features/chat/conversation_share.dart）：没分享 → 生成链接；分享中显示链接 + 复制/分享；
// 对话有新内容（stale）才出现“更新快照”；停止分享要确认，之后按钮变“恢复分享”（同一链接）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/chat/conversation_share.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';

const _url = 'https://me.example/p/trip-abc123/';

class _Api implements Api {
  Map<String, dynamic> state = {'shared': false};
  final calls = <String>[];
  bool staleAfterShare = false;

  Map<String, dynamic> _page(bool shared, bool stale) =>
      {'slug': 'trip-abc123', 'id': 'trip-abc123', 'title': '杭州', 'url': _url, 'updated': 1791700000, 'published': shared,
       'shared': shared, 'stale': stale};

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return state;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    return state = _page(true, staleAfterShare);
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    return state = _page(false, false);
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _open(WidgetTester tester, _Api api) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 900);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Builder(builder: (context) => Scaffold(
            body: Center(child: TextButton(onPressed: () => showConversationShare(context, 'c1'), child: const Text('open'))),
          )),
    ),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
}

void main() {
  test('parsing', () {
    expect(ConversationShare.fromJson({'shared': false}).page, isNull);
    final s = ConversationShare.fromJson({'slug': 'a', 'id': 'a', 'title': 't', 'url': _url, 'published': false, 'shared': false, 'stale': true});
    expect([s.page?.url, s.shared, s.stale, s.page?.published], [_url, false, true, false]);
  });

  testWidgets('生成 → 链接 → 停止 → 恢复', (tester) async {
    final api = _Api();
    await _open(tester, api);
    expect(find.text('分享对话'), findsOneWidget);
    await tester.tap(find.text('生成分享链接'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/conversations/c1/share'));
    expect(find.text(_url), findsOneWidget);
    expect(find.text('复制链接'), findsWidgets);
    expect(find.text('对话有新内容 · 更新快照'), findsNothing);

    await tester.tap(find.text('停止分享'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('停止分享').last); // 确认框里的按钮
    await tester.pumpAndSettle();
    expect(api.calls, contains('DELETE /api/conversations/c1/share'));
    expect(find.text('恢复分享'), findsOneWidget);
    expect(find.text(_url), findsNothing);
  });

  testWidgets('有新内容才出现更新快照', (tester) async {
    final api = _Api()..state = {'slug': 'trip-abc123', 'id': 'trip-abc123', 'title': '杭州', 'url': _url, 'updated': 1791700000,
      'published': true, 'shared': true, 'stale': true};
    await _open(tester, api);
    expect(find.text('对话有新内容 · 更新快照'), findsOneWidget);
    await tester.tap(find.text('对话有新内容 · 更新快照'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.startsWith('POST')).length, 1);
    expect(find.text('对话有新内容 · 更新快照'), findsNothing);
  });
}
