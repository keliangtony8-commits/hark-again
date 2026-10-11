// 内容成品类的块：草稿（用户拿去发的字）、摘要（用户自己读的长文）、图片（想看样子）。
// 三张卡的分工和后端 agent/builtin/display.py 的 show_draft / show_summary / show_images 一一对应。
//   草稿：再深一层的小块（和代码块同一材质），原样文字，右上 复制 / 分享。
//   摘要：一张卡 = 一份文档：小字来源 + 标题 + Markdown 正文；很长时折起，“展开全文”交叉淡化成整篇。
//   图片：单张 4:3 铺满；多张横排滑动；下好了淡入，坏图留占位；点开看大图（可捏合缩放）。
import 'package:flutter/material.dart';

import '../core/links.dart';
import '../core/share.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/markdown.dart';
import '../ui/motion.dart';
import '../ui/sheets.dart';

Rect? _originOf(BuildContext context) {
  final box = context.findRenderObject() as RenderBox?;
  return box == null || !box.hasSize ? null : box.localToGlobal(Offset.zero) & box.size;
}

class DraftBlockView extends StatelessWidget {
  const DraftBlockView(this.block, {super.key});
  final DraftBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      container: true,
      label: '草稿：${block.title}',
      child: Container(
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.md)),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x1, Sp.x1, 0),
              child: Row(
                children: [
                  Icon(Icons.edit_note_rounded, size: QuietAction.iconSize, color: p.text3),
                  const SizedBox(width: Sp.x2),
                  Expanded(
                    child: Text('草稿 · ${block.title}', style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  CopyAction(text: block.body, tooltip: '复制草稿'),
                  Builder(
                    builder: (b) => QuietAction(
                      tooltip: '分享草稿',
                      icon: const Icon(Icons.ios_share_rounded),
                      onPressed: () => shareText(block.body, subject: block.title, origin: _originOf(b)),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x4),
              child: SelectableText(block.body, style: context.text.bodyMedium),
            ),
          ],
        ),
      ),
    );
  }
}

class SummaryBlockView extends StatefulWidget {
  const SummaryBlockView(this.block, {super.key});
  final SummaryBlock block;

  /// 估计“很长”：超过这么多字或行才折起，短文档直接整篇显示。
  static const foldChars = 600, foldLines = 14;
  static bool foldable(String md) => md.length > foldChars || '\n'.allMatches(md).length > foldLines;

  @override
  State<SummaryBlockView> createState() => _SummaryBlockViewState();
}

class _SummaryBlockViewState extends State<SummaryBlockView> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final b = widget.block;
    final p = context.palette;
    final fold = SummaryBlockView.foldable(b.markdown);
    final body = AppMarkdown(b.markdown);
    return AppCard(
      padding: const EdgeInsets.fromLTRB(Layout.cardPad, Sp.x4, Sp.x2, Sp.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: Sp.x1),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (b.subtitle != null && b.subtitle!.isNotEmpty) Text(b.subtitle!, style: context.text.labelSmall),
                      Text(b.title, style: context.text.titleLarge),
                    ],
                  ),
                ),
              ),
              CopyAction(text: copyText([b]), tooltip: '复制全文'),
            ],
          ),
          const SizedBox(height: Sp.x2),
          Padding(
            padding: const EdgeInsets.only(right: Sp.x3),
            child: !fold
                ? body
                : FadeSwitcher(
                    child: KeyedSubtree(
                      key: ValueKey(_open),
                      child: _open ? body : FoldedBox(maxHeight: Layout.summaryFold, child: body),
                    ),
                  ),
          ),
          if (fold)
            Pressable(
              onTap: () => setState(() => _open = !_open),
              semanticLabel: _open ? '收起' : '展开全文',
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: A11y.minTap),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SwapSwitcher(child: Text(_open ? '收起' : '展开全文', key: ValueKey(_open), style: context.text.labelLarge?.copyWith(color: p.text2))),
                    const SizedBox(width: Sp.x1),
                    TurnIcon(open: _open, turns: 0.5, child: Icon(Icons.expand_more_rounded, size: QuietAction.iconSize, color: p.text2)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class ImagesBlockView extends StatelessWidget {
  const ImagesBlockView(this.block, {super.key});
  final ImagesBlock block;

  @override
  Widget build(BuildContext context) {
    final items = block.items;
    if (items.isEmpty) return const SizedBox.shrink();
    if (items.length == 1) {
      return _Figure(item: items.first, child: AspectRatio(aspectRatio: 4 / 3, child: NetImage(items.first.url)));
    }
    return SizedBox(
      height: Layout.imageStrip + Sp.x6,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: items.length,
        separatorBuilder: (_, _) => const SizedBox(width: Sp.x2),
        itemBuilder: (_, i) => FadeSlideIn(
          delay: Motion.stagger(i),
          child: SizedBox(
            width: Layout.imageTileWidth,
            child: _Figure(item: items[i], child: SizedBox(height: Layout.imageStrip, child: NetImage(items[i].url))),
          ),
        ),
      ),
    );
  }
}

/// 一张图 + 一行说明；点了看大图。
class _Figure extends StatelessWidget {
  const _Figure({required this.item, required this.child});
  final ImageItem item;
  final Widget child;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Pressable(
        onTap: () => showImageViewer(context, item),
        semanticLabel: '图片${item.caption == null ? '' : '：${item.caption}'}，查看大图',
        child: ClipRRect(borderRadius: BorderRadius.circular(Radii.md), child: child),
      ),
      if (item.caption != null && item.caption!.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: Sp.x1),
          child: Text(item.caption!, style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
    ],
  );
}

/// 网络图：底下先铺一层占位底色，下好了淡入；打不开显示一个安静的坏图标。图片卡、商品宫格、订单卡共用。
class NetImage extends StatelessWidget {
  const NetImage(this.url, {super.key, this.fit = BoxFit.cover});
  final String url;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: context.tileFill,
    child: Image.network(
      url,
      fit: fit,
      width: double.infinity,
      height: double.infinity,
      frameBuilder: (c, child, frame, sync) => fadeInFrame(c, child, frame, sync),
      errorBuilder: (c, _, _) => Center(child: Icon(Icons.broken_image_outlined, color: c.palette.text3)),
    ),
  );
}

/// 大图：玻璃对话框里一张可捏合缩放的图 + 说明 + 打开原图。
Future<void> showImageViewer(BuildContext context, ImageItem item) => showAppDialog<void>(
  context,
  builder: (ctx) => GlassDialog(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(Radii.md),
          child: AspectRatio(
            aspectRatio: 1,
            child: InteractiveViewer(maxScale: 4, child: NetImage(item.url, fit: BoxFit.contain)),
          ),
        ),
        if (item.caption != null && item.caption!.isNotEmpty)
          Padding(padding: const EdgeInsets.only(top: Sp.x3), child: Text(item.caption!, style: ctx.text.bodyMedium)),
        const SizedBox(height: Sp.x4),
        Row(
          children: [
            Expanded(child: PillButton(label: '关闭', onTap: () => Navigator.of(ctx).pop())),
            const SizedBox(width: Sp.x2),
            Expanded(child: PillButton(label: '打开原图', icon: Icons.north_east_rounded, primary: true, onTap: () => openUrl(item.url))),
          ],
        ),
      ],
    ),
  ),
);
