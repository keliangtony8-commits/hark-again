// 报告卡的“一眼”（v1.07）：服务端给 headline（摘要卡标题）+ gist（一句话），收件箱行副标题和横幅第二行都是
// `headline · gist`；老服务器 / 老卡没有这两个字段 → 收件箱行退回正文纯文本，横幅只显示标题。
import 'package:assistant/features/home/inbox.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> reportJson([Map<String, dynamic> extra = const {}]) => {
      'id': 'r1',
      'kind': 'report',
      'title': '早间简报',
      'blocks': [
        {'type': 'text', 'text': '## 今天\n**三件事**，先背单词'},
      ],
      'dismissed': false,
      ...extra,
    };

void main() {
  test('glance = headline · gist; either alone; blank ignored', () {
    expect(HomeCard.fromJson(reportJson({'headline': '今天 · 10月12日 周一', 'gist': '今天先背单词。'})).glance,
        '今天 · 10月12日 周一 · 今天先背单词。');
    expect(HomeCard.fromJson(reportJson({'gist': '  今天先背单词。 '})).glance, '今天先背单词。');
    expect(HomeCard.fromJson(reportJson({'headline': '本周 3 篇', 'gist': '   '})).glance, '本周 3 篇');
  });

  test('old server: falls back to stripped plain text, then placeholder', () {
    expect(HomeCard.fromJson(reportJson()).glance, '今天 三件事，先背单词');
    expect(HomeCard.fromJson(reportJson({'blocks': <dynamic>[]})).glance, '点开查看结果');
    final long = HomeCard.fromJson(reportJson({
      'blocks': [
        {'type': 'text', 'text': '字' * 100},
      ],
    }));
    expect(long.glance.length, 81);
    expect(long.glance.endsWith('…'), isTrue);
  });

  test('inbox item glance', () {
    final item = InboxItem.fromJson({'id': 'x', 'kind': 'report', 'title': '论文追踪', 'headline': '本周 3 篇新论文', 'gist': '第二篇最相关。'});
    expect(item.glance, '本周 3 篇新论文 · 第二篇最相关。');
    expect(InboxItem.fromJson({'id': 'x', 'kind': 'report', 'title': 't'}).glance, isNull);
  });

  Future<void> banner(WidgetTester t, InboxItem item) => t.pumpWidget(MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: InboxBanner(item: item, onOpen: () {}, onDismiss: () {})),
      ));

  testWidgets('banner second line shows the glance, and reads it out', (t) async {
    final handle = t.ensureSemantics();
    await banner(t, const InboxItem(id: 'x', kind: 'report', title: '论文追踪', headline: '本周 3 篇新论文', gist: '第二篇最相关。'));
    expect(find.text('论文追踪'), findsOneWidget);
    expect(find.text('本周 3 篇新论文 · 第二篇最相关。'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('新报告，论文追踪，本周 3 篇新论文')), findsOneWidget);
    handle.dispose();
  });

  testWidgets('banner without glance = title only (old server)', (t) async {
    await banner(t, const InboxItem(id: 'x', kind: 'report', title: '每日新闻'));
    expect(find.text('每日新闻'), findsOneWidget);
    expect(find.byType(Text), findsNWidgets(2)); // 新报告 + 标题
  });
}
