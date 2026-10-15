// v2.97 E1：列表行 / 分组 / 子页说明各只有一个组件（ui/kit.dart 的 ListRow / ListGroup / PageIntro），= 网页 ui/kit.tsx 同名组件。
// 旧名 RowTile / GlassGroup / SubPageLine 已删除；页面不再自己拼 InkWell + Padding + Row 的行。
import 'dart:io';

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _wrap(Widget child) => MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: ListView(children: [child])));

/// 仍自己画行的文件（都不是设置式列表行）：抽屉里的对话 / 项目行、电脑页带进度条的状态行、运行记录（多行错误说明）、用量分享行。
/// 只许减少；新页面一律用 ListRow。
const _rawRowFiles = {
  'lib/features/chat/history_panel.dart',
  'lib/features/computer/computer_details.dart',
  'lib/features/computer/computer_section.dart',
  'lib/features/me/task_detail.dart',
  'lib/features/me/usage_screen.dart',
  'lib/features/projects/project_switcher.dart',
};

void main() {
  test('架构守卫：旧名不回来；手写 InkWell 行只在登记的文件里', () {
    final files = Directory('lib').listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'));
    for (final f in files) {
      final path = f.path.replaceAll('\\', '/');
      final src = f.readAsStringSync();
      for (final old in ['RowTile', 'GlassGroup', 'SubPageLine']) {
        expect(RegExp('\\b$old\\b').hasMatch(src), isFalse, reason: '$path 还在用 $old → 用 ListRow / ListGroup / PageIntro');
      }
      if (path.startsWith('lib/features/') && src.contains('InkWell(')) {
        expect(_rawRowFiles, contains(path), reason: '$path 手写了 InkWell 行 → 用 ui/kit.dart 的 ListRow');
      }
    }
  });

  testWidgets('ListRow：titleWidget 代替标题文字、titleMaxLines 放开行数、semanticLabel 合成一个按钮节点', (tester) async {
    var taps = 0;
    await tester.pumpWidget(_wrap(ListGroup(children: [
      ListRow(
        title: '我对花生过敏',
        titleWidget: const HighlightText('我对花生过敏', query: '花生'),
        subtitle: '昨天',
        semanticLabel: '记忆：我对花生过敏',
        onTap: () => taps++,
      ),
      const ListRow(title: '很长的一段记忆正文', titleMaxLines: 3),
    ])));
    expect(find.byType(HighlightText), findsOneWidget);
    expect(find.text('我对花生过敏'), findsOneWidget); // 只有 titleWidget 那一份（标题文字被替掉，不画两遍）
    expect(find.bySemanticsLabel('记忆：我对花生过敏'), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsOneWidget); // 可点的行带箭头，静态行不带
    await tester.tap(find.byType(HighlightText));
    expect(taps, 1);
    final body = tester.widget<Text>(find.text('很长的一段记忆正文'));
    expect(body.maxLines, 3);
  });

  testWidgets('PageIntro：有摘要 = 小字 + 说明；没摘要 = 只有说明，下面留区块间距（原 SubPageLine）', (tester) async {
    await tester.pumpWidget(_wrap(const Column(children: [PageIntro(summary: '3 条', line: '说明一'), PageIntro(line: '说明二')])));
    await tester.pumpAndSettle();
    expect(find.text('3 条'), findsOneWidget);
    expect(find.text('说明一'), findsOneWidget);
    expect(find.text('说明二'), findsOneWidget);
    final gapBelow = tester.getBottomLeft(find.byType(PageIntro).last).dy - tester.getBottomLeft(find.text('说明二')).dy;
    expect(gapBelow, greaterThan(16));
  });
}
