// v2.91 §N 项目页：≡↔+ 图标（只动 transform、减少动态直接到位）、标题药丸的显隐规则（进场浮出 / 上翻 >24 浮出 /
// 下滑、停 1.5 秒、回到底部收起；换对话那一跳不算回到底部；标题被重新总结时浮出、占位标题不弹）、状态胶囊（解析 + 三种样子）。
import 'package:assistant/features/chat/status_capsule.dart';
import 'package:assistant/features/chat/title_pill.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _wrap(Widget child, {bool reduce = false}) => MaterialApp(
      theme: buildTheme(Brightness.light),
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: reduce, size: const Size(400, 800)),
        child: Scaffold(body: child),
      ),
    );

/// 和聊天区一样的 reverse 列表 + 药丸。
class _Host extends StatefulWidget {
  const _Host({required this.id, required this.title, required this.scroll});
  final String? id;
  final String title;
  final ScrollController scroll;
  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> {
  @override
  Widget build(BuildContext context) => Stack(children: [
        ListView.builder(
          controller: widget.scroll,
          reverse: true,
          itemCount: 60,
          itemBuilder: (_, i) => SizedBox(height: 80, child: Text('消息 $i')),
        ),
        Positioned(top: 8, left: 0, right: 0, child: Center(child: TitlePill(scroll: widget.scroll, conversationId: widget.id, title: widget.title))),
      ]);
}

void main() {
  group('MenuPlusIcon', () {
    List<Matrix4> transforms(WidgetTester tester) => [
          for (final t in tester.widgetList<Transform>(find.descendant(of: find.byType(MenuPlusIcon), matching: find.byType(Transform))))
            t.transform
        ];

    testWidgets('≡：三条横线上中下排开；+：上下两条转到中线成竖线，280ms 走完', (tester) async {
      await tester.pumpWidget(_wrap(const Center(child: MenuPlusIcon(plus: false))));
      var m = transforms(tester);
      expect(m.length, 3);
      expect(m[0].getTranslation().y, -6);
      expect(m[1].getTranslation().y, 0);
      expect(m[2].getTranslation().y, 6);
      await tester.pumpWidget(_wrap(const Center(child: MenuPlusIcon(plus: true))));
      await tester.pump(Motion.morph ~/ 2);
      m = transforms(tester);
      expect(m[0].getTranslation().y, inExclusiveRange(-6, 0)); // 半路
      await tester.pump(Motion.morph ~/ 2 + const Duration(milliseconds: 1));
      m = transforms(tester);
      expect(m[0].getTranslation().y, closeTo(0, 1e-9));
      expect(m[2].getTranslation().y, closeTo(0, 1e-9));
      // 旋转 90°：矩阵的 x 轴转到了 y 方向
      expect(m[0].entry(1, 0).abs(), greaterThan(0.85));
      expect(m[1].entry(1, 0), closeTo(0, 1e-9)); // 中线不转
    });

    testWidgets('减少动态：直接到终态', (tester) async {
      await tester.pumpWidget(_wrap(const Center(child: MenuPlusIcon(plus: false)), reduce: true));
      await tester.pumpWidget(_wrap(const Center(child: MenuPlusIcon(plus: true)), reduce: true));
      await tester.pump();
      expect(transforms(tester)[0].getTranslation().y, closeTo(0, 1e-9));
    });
  });

  group('TitlePill', () {
    bool shown(WidgetTester tester) => tester.state<TitlePillState>(find.byType(TitlePill)).shown.value;

    testWidgets('进场浮出，停 1.5 秒收起；上翻 >24px 浮出，下滑收起；回到最新收起', (tester) async {
      final scroll = ScrollController();
      await tester.pumpWidget(_wrap(_Host(id: 'c1', title: '考研数学错题整理', scroll: scroll)));
      await tester.pump();
      expect(shown(tester), isTrue);
      expect(find.text('考研数学错题整理'), findsOneWidget);
      await tester.pump(Timing.pillHold + const Duration(milliseconds: 10));
      expect(shown(tester), isFalse);

      scroll.jumpTo(20); // 上翻 20：不到 24
      await tester.pump();
      expect(shown(tester), isFalse);
      scroll.jumpTo(30); // 累计 30 > 24
      await tester.pump();
      expect(shown(tester), isTrue);
      scroll.jumpTo(300); // 一直往上翻：保持，计时重来
      await tester.pump(const Duration(seconds: 1));
      scroll.jumpTo(320);
      await tester.pump(const Duration(seconds: 1));
      expect(shown(tester), isTrue);
      scroll.jumpTo(317); // 往下 3px：回弹抖动，不收
      await tester.pump();
      expect(shown(tester), isTrue);
      scroll.jumpTo(300); // 往下 >4px：收起
      await tester.pump();
      expect(shown(tester), isFalse);

      scroll.jumpTo(400);
      await tester.pump();
      expect(shown(tester), isTrue);
      scroll.jumpTo(0); // 回到最新
      await tester.pump();
      expect(shown(tester), isFalse);
      await tester.pump(Timing.pillHold);
    });

    testWidgets('换对话：浮出且那一跳回最新不算“回到底部”；新建对话（还没标题）不弹，占位标题不弹，重新总结后弹', (tester) async {
      final scroll = ScrollController();
      await tester.pumpWidget(_wrap(_Host(id: 'c1', title: '甲', scroll: scroll)));
      await tester.pump(Timing.pillHold + const Duration(milliseconds: 10));
      scroll.jumpTo(500);
      await tester.pump(Timing.pillHold + const Duration(milliseconds: 10));
      expect(shown(tester), isFalse);

      // 换到 c2：ChatView 在换对话时登记一个帧后回调把列表跳回 0（登记在重建之前）
      SchedulerBinding.instance.addPostFrameCallback((_) => scroll.jumpTo(0));
      await tester.pumpWidget(_wrap(_Host(id: 'c2', title: '乙', scroll: scroll)));
      expect(scroll.offset, 0);
      await tester.pump();
      expect(shown(tester), isTrue);
      await tester.pump(Timing.pillHold + const Duration(milliseconds: 10));
      expect(shown(tester), isFalse);

      // 新建：先没有 id，再有 id 但列表里还没有标题，再来占位标题 —— 都不弹
      await tester.pumpWidget(_wrap(_Host(id: null, title: '', scroll: scroll)));
      await tester.pump();
      await tester.pumpWidget(_wrap(_Host(id: 'c3', title: '', scroll: scroll)));
      await tester.pump();
      expect(shown(tester), isFalse);
      await tester.pumpWidget(_wrap(_Host(id: 'c3', title: '帮我把这一章的错题整理一下', scroll: scroll)));
      await tester.pump();
      expect(shown(tester), isFalse);
      // 模型起好总结标题：弹一下
      await tester.pumpWidget(_wrap(_Host(id: 'c3', title: '第三章错题整理', scroll: scroll)));
      await tester.pump();
      expect(shown(tester), isTrue);
      await tester.pump(Timing.pillHold + const Duration(milliseconds: 10));
      expect(shown(tester), isFalse);
    });

    testWidgets('浮出动效：从上方 8px 落下 + 淡入，只动 transform/opacity；收起后不挡点击', (tester) async {
      final scroll = ScrollController();
      await tester.pumpWidget(_wrap(_Host(id: 'c1', title: '甲', scroll: scroll)));
      await tester.pump();
      final drop = find.descendant(of: find.byType(DropIn), matching: find.byType(Transform)).first;
      expect(tester.widget<Transform>(drop).transform.getTranslation().y, closeTo(-Motion.pillDrop, 0.01));
      await tester.pump(Motion.slow ~/ 3);
      final mid = tester.widget<Transform>(drop).transform.getTranslation().y;
      expect(mid, inExclusiveRange(-Motion.pillDrop, Motion.pillDrop * 0.04 + 0.01)); // 回弹 ≤4%
      await tester.pump(Motion.slow);
      expect(tester.widget<Transform>(drop).transform.getTranslation().y, closeTo(0, 0.01));
      expect(tester.widget<IgnorePointer>(find.descendant(of: find.byType(DropIn), matching: find.byType(IgnorePointer)).first).ignoring, isFalse);
      await tester.pump(Timing.pillHold);
      await tester.pump(Motion.base);
      expect(tester.widget<IgnorePointer>(find.descendant(of: find.byType(DropIn), matching: find.byType(IgnorePointer)).first).ignoring, isTrue);
    });

    test('Motion.spring 的过冲 ≤ 4%', () {
      var peak = 0.0;
      for (var i = 0; i <= 1000; i++) {
        final v = Motion.spring.transform(i / 1000);
        if (v > peak) peak = v;
      }
      expect(peak, greaterThan(1.0));
      expect(peak, lessThanOrEqualTo(1.04));
    });
  });

  group('状态胶囊', () {
    test('解析：running / waiting / done；其余 → null', () {
      expect(ConversationSummary.fromJson({'id': 'a', 'status': 'running'}).status, ConversationStatus.running);
      expect(ConversationSummary.fromJson({'id': 'a', 'status': 'waiting'}).status, ConversationStatus.waiting);
      expect(ConversationSummary.fromJson({'id': 'a', 'status': 'done'}).status, ConversationStatus.done);
      expect(ConversationSummary.fromJson({'id': 'a', 'status': 'weird'}).status, isNull);
      expect(ConversationSummary.fromJson({'id': 'a'}).status, isNull);
      expect(ConversationSummary.fromJson({'id': 'a', 'status': 'done'}).withTitle('新').status, ConversationStatus.done); // 换标题不丢状态
    });

    testWidgets('三种文字；等你回复是墨色实心，进行中带呼吸点；读屏念“状态：…”', (tester) async {
      await tester.pumpWidget(_wrap(const Column(children: [
        StatusCapsule(ConversationStatus.running),
        StatusCapsule(ConversationStatus.waiting),
        StatusCapsule(ConversationStatus.done),
      ])));
      expect(find.text('进行中'), findsOneWidget);
      expect(find.text('等你回复'), findsOneWidget);
      expect(find.text('已完成'), findsOneWidget);
      expect(find.byType(PulseDot), findsOneWidget);
      final ctx = tester.element(find.text('等你回复'));
      final box = tester.widget<Container>(find.ancestor(of: find.text('等你回复'), matching: find.byType(Container)).first);
      expect((box.decoration! as BoxDecoration).color, ctx.palette.ink);
      expect(find.bySemanticsLabel('状态：等你回复'), findsOneWidget);
    });
  });
}
