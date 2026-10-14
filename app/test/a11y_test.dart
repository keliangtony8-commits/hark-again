// 无障碍底线：大字号不溢出、可点区域 ≥ 48、每个可点的东西都有名字、系统关动画时不再动、配色对比度够。
import 'dart:io';

import 'package:assistant/features/chat/attachment_tray.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
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

/// WCAG 相对亮度对比度（和网页 scripts/check-contrast.mjs 同一套算法、同一批配对）。
double _contrast(Color fg, Color bg) {
  final a = fg.computeLuminance(), b = bg.computeLuminance();
  return ((a > b ? a : b) + 0.05) / ((a > b ? b : a) + 0.05);
}

/// 必须 ≥ 4.5 的（正文/按钮字/气泡字/警示小字）：(叫什么, 前景, 背景)。
typedef _Pair = (String, Color Function(Palette), Color Function(Palette));

final List<_Pair> _aa45 = [
  ('气泡字', (Palette p) => p.onUserBubble, (Palette p) => p.userBubble), // §L v2.90.1 用户气泡改灰后最要紧的这一对
  ('正文/底', (Palette p) => p.text, (Palette p) => p.bg),
  ('正文/卡', (Palette p) => p.text, (Palette p) => p.surface),
  ('正文/卡2', (Palette p) => p.text, (Palette p) => p.surface2),
  ('次要字/底', (Palette p) => p.text2, (Palette p) => p.bg),
  ('次要字/卡', (Palette p) => p.text2, (Palette p) => p.surface),
  ('主按钮', (Palette p) => p.onInk, (Palette p) => p.ink),
  ('强调', (Palette p) => p.onAccent, (Palette p) => p.accent),
  ('出错字', (Palette p) => p.danger, (Palette p) => p.bg),
  ('警示字', (Palette p) => p.warning, (Palette p) => p.bg), // 到处当 bodySmall/labelSmall 用，所以按正文守（浅色因此压深过）
  ('成功字', (Palette p) => p.success, (Palette p) => p.bg),
];

/// 次要信息（时间戳、图标这类，token 里写明“对底色 ≥ 3:1”）按大字号/图形守 3.0。
final List<_Pair> _aa30 = [
  ('最次要字/底', (Palette p) => p.text3, (Palette p) => p.bg),
  ('最次要字/卡', (Palette p) => p.text3, (Palette p) => p.surface),
];

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

  const palettes = [('浅色', Palette.light), ('深色', Palette.dark)];
  for (final (name, p) in palettes) {
    testWidgets('配色对比度：正文/气泡 ≥4.5、次要信息 ≥3（$name）', (tester) async {
      final bad = <String>[];
      for (final (what, fg, bg) in _aa45) {
        final r = _contrast(fg(p), bg(p));
        if (r < 4.5) bad.add('$what ${r.toStringAsFixed(2)}:1（要 ≥4.5）');
      }
      for (final (what, fg, bg) in _aa30) {
        final r = _contrast(fg(p), bg(p));
        if (r < 3) bad.add('$what ${r.toStringAsFixed(2)}:1（要 ≥3）');
      }
      expect(bad, isEmpty, reason: '$name 配色没过 AA：${bad.join('；')}');
    });
  }

  // 气泡这条用户最在意（“不要白色，Hark 偏灰”）：颜色对不够，画出来还得对——万一气泡用了别的字色，上面那组算不出来。
  for (final b in Brightness.values) {
    testWidgets('用户气泡与回复卡：画出来字也压得住（${b.name}）', (tester) async {
      final handle = tester.ensureSemantics();
      const user = Message(id: 'u1', role: 'user', blocks: [TextBlock('明天几点出发？我八点前到南门等你')]);
      const reply = Message(id: 'a1', role: 'assistant', blocks: [TextBlock('好，我七点五十到南门，到了给你发消息。')]);
      await tester.pumpWidget(_frame(
        b: b,
        scale: 1,
        Column(children: [MessageView(user), MessageView(reply)]),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  }

  // §L：换了气泡色，编辑条 / 引用条 / 长按聚焦这三处也得跟着够亮。
  for (final b in Brightness.values) {
    testWidgets('编辑条、引用条、长按聚焦：跟气泡同一套色也够亮（${b.name}）', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_frame(
        b: b,
        scale: 1,
        Column(children: [
          Composer(onSend: (_, _) {}, busy: false, quoting: const MessageQuote(id: 'm1', role: 'user', text: '明天几点出发？')),
          Composer(onSend: (_, _) {}, busy: false, editing: const EditDraft('m1', '明天几点出发？')),
        ]),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await expectLater(tester, meetsGuideline(textContrastGuideline));

      // 长按用户消息 = 聚焦菜单（浮层压暗底下，气泡抬起来），这时也得够亮
      await tester.pumpWidget(_frame(
        b: b,
        scale: 1,
        const MessageView(Message(id: 'u1', role: 'user', blocks: [TextBlock('明天几点出发？')])),
      ));
      await tester.pumpAndSettle();
      await tester.longPress(find.text('明天几点出发？'));
      await tester.pumpAndSettle();
      expect(find.text('复制'), findsOneWidget); // 菜单真开了
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  }
}
