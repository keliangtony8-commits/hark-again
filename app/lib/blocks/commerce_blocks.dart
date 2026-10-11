// 购物类的块：商品宫格（挑东西）、订单卡（付款前确认 / 下单后回执）。
// 和后端 agent/builtin/display.py 的 show_products、orders.py 的 confirm_order / show_receipt 一一对应。
//   宫格：一张卡里按宽度排 2–4 列，一格 = 方图 + 名字（两行）+ 价格 + 一行补充；点格子打开商品页；底部一句推荐。
//   订单：一张“小票”：商家 + 状态，每行商品（小图、规格、数量、价格），费用明细，合计用衬线大字；
//         等确认时边框换成提醒色、底部两颗胶囊“不买了 / 确认下单”（走审批 approval.reply）；回执显示订单号可复制。
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/links.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import 'block_actions.dart';
import 'content_blocks.dart';

class ProductsBlockView extends StatelessWidget {
  const ProductsBlockView(this.block, {super.key});
  final ProductsBlock block;

  /// 一行放几格：至少两列（单件时一列），每格不窄于 productTileMin，最多 4 列。
  static int columns(double width, int count) {
    if (count <= 1) return 1;
    final fit = ((width + Sp.x3) / (Layout.productTileMin + Sp.x3)).floor();
    return math.min(count, fit.clamp(2, 4));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = block;
    return AppCard(
      padding: const EdgeInsets.all(Sp.x4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (b.title != null && b.title!.isNotEmpty) ...[
            Text(b.title!, style: context.text.titleMedium),
            const SizedBox(height: Sp.x3),
          ],
          LayoutBuilder(builder: (context, c) {
            final cols = columns(c.maxWidth, b.items.length);
            final w = (c.maxWidth - Sp.x3 * (cols - 1)) / cols;
            return Wrap(
              spacing: Sp.x3,
              runSpacing: Sp.x4,
              children: [
                for (var i = 0; i < b.items.length; i++)
                  FadeSlideIn(
                    delay: Motion.stagger(i),
                    child: SizedBox(width: w, child: _ProductTile(b.items[i], wide: cols == 1)),
                  ),
              ],
            );
          }),
          if (b.pick != null && b.pick!.isNotEmpty) ...[
            const SizedBox(height: Sp.x4),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Icon(Icons.auto_awesome_outlined, size: QuietAction.iconSize, color: p.text2),
                ),
                const SizedBox(width: Sp.x2),
                Expanded(child: Text(b.pick!, style: context.text.bodyMedium?.copyWith(color: p.text2))),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _ProductTile extends StatelessWidget {
  const _ProductTile(this.item, {required this.wide});
  final ProductItem item;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final picture = ClipRRect(
      borderRadius: BorderRadius.circular(Radii.md),
      child: AspectRatio(
        aspectRatio: wide ? 4 / 3 : 1,
        child: item.image != null
            ? NetImage(item.image!)
            : ColoredBox(
                color: context.tileFill,
                child: Center(child: Icon(Icons.shopping_bag_outlined, color: p.text3, size: Layout.rowIcon)),
              ),
      ),
    );
    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        picture,
        const SizedBox(height: Sp.x2),
        Text(item.name, style: context.text.bodyMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
        if (item.price != null && item.price!.isNotEmpty)
          Text(item.price!, style: context.text.titleMedium?.copyWith(fontWeight: Weights.strong)),
        if (item.meta != null && item.meta!.isNotEmpty)
          Text(item.meta!, style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
      ],
    );
    final url = item.url;
    if (url == null) return Semantics(container: true, child: body);
    return Pressable(
      onTap: () => openUrl(url),
      semanticLabel: [item.name, item.price, item.meta, '打开商品页'].whereType<String>().where((s) => s.isNotEmpty).join('，'),
      child: body,
    );
  }
}

class OrderBlockView extends StatelessWidget {
  const OrderBlockView(this.block, {super.key});
  final OrderBlock block;

  /// 状态小字和颜色：等确认用提醒色（和审批卡一致），其余都退到 text2/text3。
  static (String, Color) stateLabel(OrderBlock b, Palette p) => switch (b.state) {
        'placed' => ('已下单', p.text2),
        'approved' => ('已确认', p.text2),
        'rejected' => ('没有下单', p.text3),
        'expired' => ('已过期', p.text3),
        _ => ('等你确认', p.warning),
      };

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = block;
    final onReply = BlockActions.of(context)?.onApproval;
    final (label, color) = stateLabel(b, p);
    final ended = b.state == 'rejected' || b.state == 'expired';
    final small = context.text.bodySmall;
    return AnimatedContainer(
      duration: context.motion(Motion.base),
      curve: Motion.ease,
      padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x4, Sp.x4, Sp.x4),
      decoration: BoxDecoration(
        color: context.cardFill,
        borderRadius: BorderRadius.circular(Radii.md),
        border: Border.all(color: b.pending ? p.warning.withValues(alpha: 0.5) : context.hairline, width: b.pending ? 1.5 : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.receipt_long_outlined, size: QuietAction.iconSize, color: p.text2),
            const SizedBox(width: Sp.x2),
            Expanded(child: Text(b.merchant, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
            SwapSwitcher(
              child: Text(label, key: ValueKey(b.state), style: context.text.labelSmall?.copyWith(color: color, fontWeight: Weights.title)),
            ),
          ]),
          Dimmed(
            dimmed: ended,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: Sp.x3),
                for (final line in b.items) _Line(line),
                if (b.breakdown.isNotEmpty || b.items.length > 1) Divider(height: Sp.x4, thickness: 1, color: context.hairline),
                for (final f in b.breakdown)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(children: [
                      Expanded(child: Text(f.label, style: small)),
                      Text(f.amount, style: small),
                    ]),
                  ),
                const SizedBox(height: Sp.x2),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Expanded(child: Text('合计', style: context.text.bodyMedium)),
                    Text(b.total, style: context.text.headlineMedium),
                  ],
                ),
                for (final (icon, text) in [
                  if (b.destination != null && b.destination!.isNotEmpty) (Icons.place_outlined, b.destination!),
                  if (b.payment != null && b.payment!.isNotEmpty) (Icons.credit_card_outlined, b.payment!),
                ])
                  Padding(
                    padding: const EdgeInsets.only(top: Sp.x2),
                    child: Row(children: [
                      Icon(icon, size: Fs.md, color: p.text3),
                      const SizedBox(width: Sp.x2),
                      Expanded(child: Text(text, style: small, maxLines: 2, overflow: TextOverflow.ellipsis)),
                    ]),
                  ),
                if (b.placed && b.orderNumber != null && b.orderNumber!.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: Sp.x2),
                    child: Row(children: [
                      Expanded(child: SelectableText('订单号 ${b.orderNumber}', style: small)),
                      CopyAction(text: b.orderNumber!, tooltip: '复制订单号'),
                    ]),
                  ),
              ],
            ),
          ),
          RiseSwitcher(
            child: b.pending && onReply != null
                ? Padding(
                    key: const ValueKey('ask'),
                    padding: const EdgeInsets.only(top: Sp.x4),
                    child: Row(children: [
                      Expanded(child: PillButton(label: '不买了', onTap: () => onReply(b.id, false))),
                      const SizedBox(width: Sp.x2),
                      Expanded(flex: 2, child: PillButton(label: b.action, primary: true, onTap: () => onReply(b.id, true))),
                    ]),
                  )
                : null,
          ),
        ],
      ),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line(this.line);
  final OrderLine line;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: Sp.x1),
      child: Row(children: [
        if (line.image != null) ...[
          ClipRRect(
            borderRadius: BorderRadius.circular(Radii.sm),
            child: SizedBox.square(dimension: Layout.orderThumb, child: NetImage(line.image!)),
          ),
          const SizedBox(width: Sp.x3),
        ],
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(line.name, style: context.text.bodyMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
            if (line.note != null && line.note!.isNotEmpty) Text(line.note!, style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
        if (line.qty > 1) ...[
          Text('×${line.qty}', style: context.text.bodySmall?.copyWith(color: p.text2)),
          const SizedBox(width: Sp.x3),
        ],
        Text(line.price, style: context.text.bodyMedium),
      ]),
    );
  }
}
