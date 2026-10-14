// v2.78 Home 重做的架构守卫：主页只排卡片栈——没有小节标题、问候、解释文字；每种卡在自己的文件里；
// 主页上的卡（今天 / 面板 / 收件箱 / 引导）都走 StackCard，节奏只在一处定。网页版同规则（HomeScreen.tsx）。
import 'dart:io';

import 'package:assistant/features/home/home_screen.dart';
import 'package:assistant/features/home/stack_card.dart';
import 'package:assistant/features/home/today_agenda.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('home_screen.dart 只排顺序：没有小节标题 / 问候 / 空状态说明', () {
    final src = File('lib/features/home/home_screen.dart').readAsStringSync();
    for (final banned in ['SectionTitle', '下午好', '早上好', '面板会按时', '今天没有排定', 'GlassCard(', 'RemovedPanels']) {
      expect(src.contains(banned), isFalse, reason: banned);
    }
  });

  test('今天 / 面板 / 收件箱 / 引导卡都用 StackCard', () {
    for (final f in ['today_card.dart', 'panel_card.dart', 'report_actions.dart']) {
      expect(File('lib/features/home/$f').readAsStringSync().contains('StackCard('), isTrue, reason: f);
    }
  });

  test('主页输入框第一个建议是“帮我准备今天”', () {
    expect(homePrompts.first, prepDayPrompt);
  });

  testWidgets('StackCard：标题在卡里、行贴卡边、卡下等距', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(
          body: Column(children: [
        StackCard(title: '收件箱', trailing: CardNote('2 条'), rows: [ListTile(title: Text('a')), ListTile(title: Text('b'))]),
        StackCard(child: Text('内容')),
      ])),
    ));
    await tester.pumpAndSettle();
    expect(find.text('收件箱'), findsOneWidget);
    expect(find.text('2 条'), findsOneWidget);
    expect(find.byType(Divider), findsOneWidget);
    expect(find.text('内容'), findsOneWidget);
  });
}
