// 建议卡配图 + 原页（v0.91）：只认 http(s)；域名去掉 www.；有图 → 卡顶一张宽图（OfferImage），
// 有原页 → 正文下“来源 · 域名”（OfferSource）；都没有 → 卡和以前一样。
import 'package:assistant/features/home/action_card.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'budget_card_test.dart' show pump;
import 'home_offer_test.dart' show offerJson;

void main() {
  test('parse image / link, host without www, non-http ignored', () {
    final c = HomeCard.fromJson({
      ...offerJson(),
      'image_url': 'https://img.example.com/a.jpg',
      'link_url': 'https://www.shop.example.com/item/42',
    });
    expect(c.imageUrl, 'https://img.example.com/a.jpg');
    expect(c.linkHost, 'shop.example.com');
    final bad = HomeCard.fromJson({...offerJson(), 'image_url': 'javascript:x', 'link_url': 'ftp://a/b'});
    expect(bad.imageUrl, isNull);
    expect(bad.linkUrl, isNull);
    expect(bad.linkHost, isNull);
    expect(HomeCard.fromJson(offerJson()).linkHost, isNull);
  });

  testWidgets('card with picture and source', (tester) async {
    await pump(tester, {
      ...offerJson(),
      'image_url': 'https://img.example.com/a.jpg',
      'link_url': 'https://www.shop.example.com/item/42',
    });
    expect(find.byType(OfferImage), findsOneWidget);
    final ratio = tester.widget<AspectRatio>(find.descendant(of: find.byType(OfferImage), matching: find.byType(AspectRatio)));
    expect(ratio.aspectRatio, Layout.offerImageRatio);
    expect(find.text('来源 · shop.example.com'), findsOneWidget);
    expect(tester.getSize(find.byType(OfferSource)).height, greaterThanOrEqualTo(A11y.minTap));
    // 图在标题上方
    expect(tester.getTopLeft(find.byType(OfferImage)).dy, lessThan(tester.getTopLeft(find.text('续费校园网')).dy));
  });

  testWidgets('plain offer card has neither', (tester) async {
    await pump(tester, offerJson());
    expect(find.byType(OfferImage), findsNothing);
    expect(find.byType(OfferSource), findsNothing);
  });
}
