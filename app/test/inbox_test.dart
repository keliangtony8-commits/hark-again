// 收件箱轮询：首次只当基线、来了新的才弹横幅、读掉/忽略不弹、摘要变了 Home 卡片跟着重拉、横幅点开去对话。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/home/inbox.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> summary(int n, [String? id]) =>
    {'unread': n, 'latest': id == null ? null : {'id': id, 'kind': 'report', 'title': '报告$id', 'conversation_id': 'c$id'}};

class FakeApi implements Api {
  Map<String, dynamic> inbox = summary(0);
  int cardLoads = 0;
  Object? lastReadBody;

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return inbox;
    if (path == '/api/cards') {
      cardLoads++;
      return <dynamic>[];
    }
    return null;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    lastReadBody = body;
    inbox = summary(0);
    return inbox;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('hasNewSince only fires when a new item arrives', () {
    final a = InboxSummary.fromJson(summary(1, 'a'));
    expect(InboxSummary.fromJson(summary(2, 'b')).hasNewSince(a), true);
    expect(InboxSummary.fromJson(summary(0)).hasNewSince(a), false); // 读掉
    expect(InboxSummary.fromJson(summary(1, 'b')).hasNewSince(InboxSummary.fromJson(summary(2, 'a'))), false); // 忽略一条后最新换了
    expect(a.sameAs(InboxSummary.fromJson(summary(1, 'a'))), true);
  });

  test('notifier: baseline, new item, mark read', () async {
    final api = FakeApi()..inbox = summary(1, 'a');
    final c = ProviderContainer(overrides: [apiProvider.overrideWithValue(api)]);
    addTearDown(c.dispose);
    final n = c.read(inboxProvider.notifier);

    expect(await n.refresh(), isNull, reason: '首次加载只是基线');
    expect(c.read(inboxProvider).unread, 1);
    expect(api.cardLoads, 0);

    expect(await n.refresh(), isNull, reason: '没变化');
    api.inbox = summary(2, 'b');
    expect((await n.refresh())?.id, 'b');
    await Future<void>.delayed(Duration.zero);
    expect(api.cardLoads, greaterThan(0), reason: '摘要变了要重拉卡片');

    await n.markRead();
    expect(api.lastReadBody, <String, dynamic>{});
    expect(c.read(inboxProvider).unread, 0);
  });

  testWidgets('banner shows title and opens on tap', (t) async {
    var opened = 0;
    await t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: InboxBanner(
          item: const InboxItem(id: 'x', kind: 'report', title: '每日新闻'),
          onOpen: () => opened++,
          onDismiss: () {},
        ),
      ),
    ));
    expect(find.text('新报告'), findsOneWidget);
    expect(find.text('每日新闻'), findsOneWidget);
    await t.tap(find.text('每日新闻'));
    await t.pumpAndSettle();
    expect(opened, 1);
  });
}
