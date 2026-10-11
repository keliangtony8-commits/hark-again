// 商品宫格 + 订单卡（v0.81）：解析（非 http 图/链接当没有）、复制规则（宫格进剪贴板，订单卡是过程卡不复制）、
// 宫格列数随宽度、推荐行；订单卡等确认时两颗胶囊回调审批（id 对、批准/拒绝），没有回调时不显示按钮，
// 状态变化后按钮收起；回执显示订单号。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/commerce_blocks.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> pump(WidgetTester tester, Block b, {void Function(String, bool)? onApproval}) async {
  tester.view.physicalSize = const Size(800, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(
      body: BlockActions(onApproval: onApproval, child: SingleChildScrollView(child: BlockView(b))),
    ),
  ));
  await tester.pumpAndSettle();
}

Map<String, dynamic> order(String state) => {
      'type': 'order',
      'id': 'a1',
      'merchant': '瑞幸咖啡 · 五道口店',
      'items': [
        {'name': '生椰拿铁', 'price': '¥29.00', 'qty': 2, 'note': '少冰', 'image': 'ftp://x'},
        {'name': '可颂', 'price': '¥9.00'},
      ],
      'breakdown': [
        {'label': '优惠', 'amount': '-¥10.00'}
      ],
      'total': '¥57.00',
      'payment': '招行信用卡 9258',
      'destination': '6 号楼门口',
      'order_number': state == 'placed' ? 'LK2026' : null,
      'action': '确认并付款',
      'state': state,
    };

void main() {
  test('解析 + 复制 + 列数', () {
    final blocks = blocksFrom([
      {
        'type': 'products',
        'title': '三款耳机',
        'pick': '选 A：降噪最好',
        'items': [
          {'name': 'A 耳机', 'price': '¥899', 'image': 'https://img.example/a.jpg', 'url': 'https://shop.example/a', 'meta': '4.8 分'},
          {'name': 'B 耳机', 'image': 'javascript:x', 'url': 'javascript:y'},
        ]
      },
      order('pending'),
    ]);
    final p = blocks[0] as ProductsBlock;
    expect(p.items[0].image, 'https://img.example/a.jpg');
    expect(p.items[1].image, isNull);
    expect(p.items[1].url, isNull);
    final o = blocks[1] as OrderBlock;
    expect(o.items.first.qty, 2);
    expect(o.items.first.image, isNull);
    expect(o.pending, isTrue);
    expect(copyText(blocks), '**三款耳机**\n- A 耳机 ¥899 4.8 分 https://shop.example/a\n- B 耳机\n选 A：降噪最好');
    expect(ProductsBlockView.columns(360, 1), 1);
    expect(ProductsBlockView.columns(300, 6), 2);
    expect(ProductsBlockView.columns(500, 6), 3);
    expect(ProductsBlockView.columns(2000, 6), 4);
    expect(ProductsBlockView.columns(2000, 3), 3);
  });

  test('字标 + 是否排宫格', () {
    expect(monogramOf('QCY HT08'), 'Q');
    expect(monogramOf('  「漫步者」Lolli'), '漫');
    expect(monogramOf('iPhone'), 'I');
    expect(monogramOf('…'), '·');
    final grid = blocksFrom([
      {'type': 'products', 'items': [{'name': 'A', 'image': 'https://img.example/a.jpg'}, {'name': 'B'}]}
    ]).first as ProductsBlock;
    expect(grid.hasPictures, isTrue);
    final list = blocksFrom([
      {'type': 'products', 'items': [{'name': 'A', 'image': 'ftp://x'}]}
    ]).first as ProductsBlock;
    expect(list.hasPictures, isFalse);
  });

  testWidgets('宫格：缺图的格子用字标占位', (tester) async {
    await pump(
        tester,
        blocksFrom([
          {
            'type': 'products',
            'items': [
              {'name': 'A 耳机', 'image': 'https://img.example/a.jpg'},
              {'name': 'B 耳机'},
            ]
          }
        ]).first);
    expect(find.byType(AspectRatio), findsNWidgets(2));
    expect(find.text('B'), findsOneWidget);
    expect(find.byIcon(Icons.north_east_rounded), findsNothing);
  });

  testWidgets('清单（一张图都没有）：名字、价格、补充、推荐', (tester) async {
    await pump(
        tester,
        blocksFrom([
          {
            'type': 'products',
            'title': '三款耳机',
            'pick': '选 A：降噪最好',
            'items': [
              {'name': 'A 耳机', 'price': '¥899', 'meta': '4.8 分', 'url': 'https://shop.example/a'},
              {'name': 'B 耳机', 'price': '¥499'},
            ]
          }
        ]).first);
    expect(find.text('三款耳机'), findsOneWidget);
    expect(find.text('¥899'), findsOneWidget);
    expect(find.text('4.8 分'), findsOneWidget);
    expect(find.text('选 A：降噪最好'), findsOneWidget);
    expect(find.byType(AspectRatio), findsNothing); // 没图 → 不排空白方块
    expect(find.text('A'), findsOneWidget); // 字标
    expect(find.byIcon(Icons.north_east_rounded), findsOneWidget); // 只有 A 有商品页
    expect(find.bySemanticsLabel(RegExp('A 耳机，¥899，4.8 分，打开商品页')), findsOneWidget);
  });

  testWidgets('订单：确认 / 不买了 回调审批 id', (tester) async {
    final replies = <(String, bool)>[];
    await pump(tester, Block.fromJson(order('pending')), onApproval: (id, ok) => replies.add((id, ok)));
    expect(find.text('等你确认'), findsOneWidget);
    expect(find.text('¥57.00'), findsOneWidget);
    expect(find.text('×2'), findsOneWidget);
    expect(find.text('-¥10.00'), findsOneWidget);
    expect(find.text('6 号楼门口'), findsOneWidget);
    await tester.tap(find.text('确认并付款'));
    await tester.tap(find.text('不买了'));
    expect(replies, [('a1', true), ('a1', false)]);

    // 服务器推来 approved：按钮收起
    await pump(tester, Block.fromJson(order('approved')), onApproval: (id, ok) {});
    expect(find.text('已确认'), findsOneWidget);
    expect(find.text('确认并付款'), findsNothing);
  });

  testWidgets('订单：没有回调不显示按钮；回执显示订单号', (tester) async {
    await pump(tester, Block.fromJson(order('pending')));
    expect(find.text('确认并付款'), findsNothing);
    await pump(tester, Block.fromJson(order('placed')));
    expect(find.text('已下单'), findsOneWidget);
    expect(find.text('订单号 LK2026'), findsOneWidget);
    expect(find.byTooltip('复制订单号'), findsOneWidget);
  });
}
