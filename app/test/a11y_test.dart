// 无障碍底线：大字号不溢出、可点区域 ≥ 48、每个可点的东西都有名字、系统关动画时不再动。
import 'dart:io';

import 'package:assistant/features/chat/attachment_tray.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// 小屏（360 宽）+ 1.3 倍字号 + 可选“移除动画”
Widget _frame(Widget child, {double scale = 1.3, bool reduce = false, Brightness b = Brightness.light}) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(b),
        home: Builder(
          builder: (ctx) => MediaQuery(
            data: MediaQuery.of(ctx).copyWith(textScaler: TextScaler.linear(scale), disableAnimations: reduce),
            child: Scaffold(body: child),
          ),
        ),
      ),
    );

void _smallScreen(WidgetTester tester) {
  tester.view.physicalSize = const Size(360, 720);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

void main() {
  testWidgets('输入框：1.3 倍字号不溢出，按钮够大且有名字', (tester) async {
    _smallScreen(tester);
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(_frame(Align(alignment: Alignment.bottomCenter, child: Composer(onSend: (_, _) {}, busy: false))));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.bySemanticsLabel('语音输入'), findsOneWidget);
    expect(find.byTooltip('添加附件'), findsOneWidget);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));

    await tester.enterText(find.byType(TextField), '你好');
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel('发送'), findsOneWidget);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    handle.dispose();
  });

  testWidgets('附件托盘：小叉的可点区域 48 且落在自身范围内', (tester) async {
    _smallScreen(tester);
    final handle = tester.ensureSemantics();
    var removed = 0;
    final a = Attachment(name: '课表.pdf', local: File('/tmp/x.pdf'));
    await tester.pumpWidget(_frame(AttachmentTray(items: [a], onRemove: (_) => removed++), reduce: true));
    await tester.pump();
    expect(tester.takeException(), isNull);
    final close = find.bySemanticsLabel('移除 课表.pdf');
    expect(close, findsOneWidget);
    expect(tester.getSize(close).shortestSide, greaterThanOrEqualTo(48));
    // 点按钮边缘（离小叉圆心 20）也要命中
    await tester.tapAt(tester.getCenter(close) + const Offset(-20, 20));
    expect(removed, 1);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    handle.dispose();
  });

  for (final b in Brightness.values) {
    testWidgets('通用零件：长文案 + 1.3 倍字号不溢出（${b.name}）', (tester) async {
      _smallScreen(tester);
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_frame(
        b: b,
        ListView(padding: const EdgeInsets.all(16), children: [
          ListGroup(children: [
            RowTile(icon: Icons.memory_rounded, title: '记忆' * 20, subtitle: '助手记住的关于你的事情' * 6, onTap: () {}),
            RowTile(icon: Icons.schedule_rounded, title: '定时任务', trailing: const Pill('每天 08:00'), onTap: () {}),
          ]),
          AppCard(onTap: () {}, child: const Text('一张可以点的卡片')),
          EmptyHint(icon: Icons.inbox_rounded, title: '还没有内容', text: '说明文字' * 15, action: FilledButton(onPressed: () {}, child: const Text('新建'))),
        ]),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.bySemanticsLabel(RegExp('一张可以点的卡片')), findsOneWidget); // Pressable 把文字并成按钮名
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  }

  testWidgets('系统关掉动画：进场直接到位，循环动画停住（pumpAndSettle 能结束）', (tester) async {
    await tester.pumpWidget(_frame(
      reduce: true,
      const Column(children: [
        FadeSlideIn(child: Text('出现')),
        TypingDots(),
        Shimmer(),
        PulseDot(color: Colors.red),
      ]),
    ));
    expect(find.byType(Opacity), findsNothing); // FadeSlideIn 没包动画层
    await tester.pumpAndSettle(); // 若还在循环，这里会超时
    expect(tester.hasRunningAnimations, isFalse);
  });

  testWidgets('Pressable：读屏里是按钮，禁用时标为不可用', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(_frame(const Column(children: [
      Pressable(semanticLabel: '关闭', child: SizedBox.square(dimension: 48)),
    ])));
    final node = tester.getSemantics(find.bySemanticsLabel('关闭'));
    expect(node.flagsCollection.isButton, isTrue);
    expect(node.flagsCollection.isEnabled, isNot(true));
    handle.dispose();
  });
}
