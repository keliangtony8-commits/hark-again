// Pages 页：老服务器没有 published = 已发布；已发布的菜单有打开/分享/复制/重命名/下线，下线要确认后 PATCH，
// 行变“已下线”且菜单只剩重新发布/重命名；重新发布恢复；重命名 PATCH 标题；失败提示服务器的话、列表不变。
import 'package:assistant/ui/glass.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/pages_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeApi implements Api {
  FakeApi(this.pages);
  List<Map<String, dynamic>> pages;
  final calls = <String>[];
  String? fail;

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return pages;
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path $body');
    if (fail != null) throw ApiError(fail!, 422);
    final id = path.split('/').last;
    final i = pages.indexWhere((p) => p['id'] == id);
    pages[i] = {...pages[i], ...(body as Map).cast<String, dynamic>()};
    return pages[i];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> page(String id, String title, {bool? published}) => {
      'id': id, 'slug': id, 'title': title, 'url': 'https://me.example/p/$id/', 'updated': 1760000000,
      'published': ?published,
    };

Future<void> pump(WidgetTester tester, FakeApi api) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const PagesScreen()),
  ));
  await tester.pumpAndSettle();
}

Future<void> menu(WidgetTester tester, String title) async {
  await tester.tap(find.text(title).first);
  await tester.pumpAndSettle();
}

void main() {
  test('published defaults to true for old servers', () {
    expect(PageItem.fromJson(page('a', 'x')).published, true);
    expect(PageItem.fromJson(page('a', 'x', published: false)).published, false);
  });

  testWidgets('unpublish (confirmed) then republish', (tester) async {
    final api = FakeApi([page('trip-1', '东京五日'), page('menu-2', '菜单', published: true)]);
    await pump(tester, api);
    expect(find.text('已下线'), findsNothing);

    await menu(tester, '东京五日');
    for (final a in ['在浏览器打开', '分享链接', '复制链接', '重命名', '下线']) {
      expect(find.text(a), findsOneWidget, reason: a);
    }
    expect(find.text('重新发布'), findsNothing);

    // 取消确认 → 不发请求
    await tester.tap(find.text('下线'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty);

    await menu(tester, '东京五日');
    await tester.tap(find.text('下线'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(PillButton, '下线'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'PATCH /api/pages/trip-1 {published: false}');
    expect(find.text('已下线'), findsWidgets); // 行标签 + 提示
    expect(find.byType(SnackBar), findsOneWidget);

    await menu(tester, '东京五日');
    expect(find.text('在浏览器打开'), findsNothing);
    expect(find.text('复制链接'), findsNothing);
    expect(find.text('重命名'), findsOneWidget);
    await tester.tap(find.text('重新发布'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'PATCH /api/pages/trip-1 {published: true}');
    expect(find.text('已重新发布，原链接恢复'), findsOneWidget);
    expect(find.descendant(of: find.byType(PageRow), matching: find.text('已下线')), findsNothing);
  });

  testWidgets('rename patches title; server error shown, list unchanged', (tester) async {
    final api = FakeApi([page('trip-1', '东京五日')]);
    await pump(tester, api);
    await menu(tester, '东京五日');
    await tester.tap(find.text('重命名'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '东京五日游');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'PATCH /api/pages/trip-1 {title: 东京五日游}');
    expect(find.text('东京五日游'), findsOneWidget);

    api.fail = '标题不能为空';
    await menu(tester, '东京五日游');
    await tester.tap(find.text('下线'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(PillButton, '下线'));
    await tester.pumpAndSettle();
    expect(find.text('标题不能为空'), findsOneWidget);
    expect(find.descendant(of: find.byType(PageRow), matching: find.text('已下线')), findsNothing);
  });
}
