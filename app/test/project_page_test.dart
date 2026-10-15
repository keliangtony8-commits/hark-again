// 项目页：≡↔+ 图标（只动 transform、减少动态直接到位）、项目名药丸的进场 DropIn（v2.95；v2.91 滚动显隐的标题药丸已删）、
// 状态胶囊（解析 + 三种样子）。
import 'package:assistant/features/chat/status_capsule.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _wrap(Widget child, {bool reduce = false}) => MaterialApp(
      theme: buildTheme(Brightness.light),
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: reduce, size: const Size(400, 800)),
        child: Scaffold(body: child),
      ),
    );

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

  group('DropIn（项目名药丸进场）', () {
    testWidgets('一挂上就从上方 8px 落下 + 淡入，只动 transform/opacity，回弹 ≤4%；常驻、可点', (tester) async {
      await tester.pumpWidget(_wrap(const Center(child: DropIn(shown: true, child: Text('📚 考研')))));
      final drop = find.descendant(of: find.byType(DropIn), matching: find.byType(Transform)).first;
      expect(tester.widget<Transform>(drop).transform.getTranslation().y, closeTo(-Motion.pillDrop, 0.01));
      await tester.pump(Motion.slow ~/ 3);
      final mid = tester.widget<Transform>(drop).transform.getTranslation().y;
      expect(mid, inExclusiveRange(-Motion.pillDrop, Motion.pillDrop * 0.04 + 0.01));
      await tester.pump(Motion.slow);
      expect(tester.widget<Transform>(drop).transform.getTranslation().y, closeTo(0, 0.01));
      expect(tester.widget<IgnorePointer>(find.descendant(of: find.byType(DropIn), matching: find.byType(IgnorePointer)).first).ignoring, isFalse);
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
