// 图片一摞（v2.99 E4 ImageStack，= 网页 blocks/ImageStack.tsx）：一个图片块（后端 show_images 一次的结果）= 一摞。
// 单张：4:3 铺满；多张：最上面一张 4:3，后面最多露 Layout.stackLayers 层（向右下错开 + 交替轻转约 2° + 逐层盖一层底色薄纱），右下角“N 张”。
// 第一次出现时后面几张从正下方扇开到位（只动 transform / opacity；减少动态时直接到位）。
// 点开 = 全屏查看器（ui/sheets.dart showAppViewer）：左右滑翻页、每页可捏合缩放，顶部页码，底部说明 + 打开原图。
// 替换了 v2.98 之前的“多张横排小图条 + 单张玻璃对话框大图”（见 docs/devlog.md v2.99）。
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/links.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import '../ui/sheets.dart';
import 'content_blocks.dart' show NetImage;

class ImageStack extends StatelessWidget {
  const ImageStack(this.block, {super.key});
  final ImagesBlock block;

  @override
  Widget build(BuildContext context) {
    final items = [for (final i in block.items) if (i.safe) i];
    if (items.isEmpty) return const SizedBox.shrink();
    final n = items.length;
    final layers = math.min(n - 1, Layout.stackLayers);
    final top = items.first;
    final cap = top.caption?.trim() ?? '';
    final label = n == 1
        ? '图片${cap.isEmpty ? '' : '：$cap'}，查看大图'
        : '$n 张图片${cap.isEmpty ? '' : '，第一张：$cap'}，点开左右翻看';
    // 最上面一张：同一条 1px 发丝边（浅色图贴在浅底上也有边界，= 网页 .image-stack-card 的 border）
    final front = DecoratedBox(
      position: DecorationPosition.foreground,
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(Radii.inner), border: Border.all(color: context.palette.border)),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(Radii.inner),
        // 实底垫在图下：坏图 / 加载中时后面那层不会从半透明占位里透出来
        child: ColoredBox(color: context.palette.surface, child: AspectRatio(aspectRatio: 4 / 3, child: NetImage(top.url))),
      ),
    );
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: Layout.imageStackMax),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Pressable(
            key: const Key('image-stack'),
            onTap: () => showImageGallery(context, items),
            semanticLabel: label,
            scale: 0.98,
            child: Padding(
              // 给后面错开的几层留出位置，整摞仍在自己的盒子里（不压到下一块）
              padding: EdgeInsets.only(right: layers * Layout.stackPeek, bottom: layers * Layout.stackPeek),
              child: layers == 0
                  ? front
                  : _Fan(builder: (t) => Stack(clipBehavior: Clip.none, children: [
                        for (var i = layers; i >= 1; i--)
                          Positioned.fill(
                            child: Transform.translate(
                              offset: Offset(i * Layout.stackPeek * t, i * Layout.stackPeek * t),
                              child: Transform.rotate(
                                angle: (i.isOdd ? 1 : -1) * Motion.stackTurn * t,
                                child: _Layer(url: items[i].url, depth: i),
                              ),
                            ),
                          ),
                        front,
                        Positioned(right: Sp.x2, bottom: Sp.x2, child: _Count(n)),
                      ])),
            ),
          ),
          if (cap.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: Sp.x1),
              child: Text(cap, style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
        ],
      ),
    );
  }
}

/// 后面的一层：实图 + 一层页面底色的薄纱（越靠后越淡）+ 发丝边框，层与层分得清；
/// 不用 Opacity——半透明的层会互相透出来，糊成一片。
class _Layer extends StatelessWidget {
  const _Layer({required this.url, required this.depth});
  final String url;
  final int depth;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = BorderRadius.circular(Radii.inner);
    return ExcludeSemantics(
      child: DecoratedBox(
        position: DecorationPosition.foreground,
        decoration: BoxDecoration(borderRadius: r, border: Border.all(color: p.border)),
        child: ClipRRect(
          borderRadius: r,
          child: Stack(fit: StackFit.expand, children: [
            ColoredBox(color: p.surface),
            NetImage(url),
            ColoredBox(color: p.bg.withValues(alpha: depth * Op.stackLayer)),
          ]),
        ),
      ),
    );
  }
}

/// 扇开进度：首次挂载 t 从 0 走到 1（Motion.spring，轻微过冲）；减少动态时 t 直接是 1。
class _Fan extends StatelessWidget {
  const _Fan({required this.builder});
  final Widget Function(double t) builder;

  @override
  Widget build(BuildContext context) {
    if (context.reduceMotion) return builder(1);
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Motion.stackFan,
      curve: Motion.spring,
      builder: (_, t, _) => RepaintBoundary(child: builder(t)),
    );
  }
}

/// 右下角“N 张”小胶囊。
class _Count extends StatelessWidget {
  const _Count(this.n);
  final int n;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ExcludeSemantics(
      child: DecoratedBox(
        decoration: BoxDecoration(color: p.ink, borderRadius: BorderRadius.circular(Radii.full)),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x2, vertical: Sp.x1 / 2),
          child: Text('$n 张', style: context.text.labelSmall?.copyWith(color: p.onInk)),
        ),
      ),
    );
  }
}

/// 打开全屏查看器，从第 [start] 张开始。
Future<void> showImageGallery(BuildContext context, List<ImageItem> items, {int start = 0}) =>
    showAppViewer<void>(context, builder: (_) => ImageGallery(items: items, start: start));

/// 全屏查看器内容：顶部页码 + 关闭，中间左右滑翻页（每页可捏合缩放），底部说明 + 打开原图。
/// 当前页用 ValueNotifier，翻页只重画页码和说明，不重建整页。
class ImageGallery extends StatefulWidget {
  const ImageGallery({super.key, required this.items, this.start = 0});
  final List<ImageItem> items;
  final int start;

  @override
  State<ImageGallery> createState() => _ImageGalleryState();
}

class _ImageGalleryState extends State<ImageGallery> {
  late final PageController _pages = PageController(initialPage: widget.start);
  late final ValueNotifier<int> _at = ValueNotifier(widget.start);
  final _zoomed = ValueNotifier(false);

  @override
  void dispose() {
    _pages.dispose();
    _at.dispose();
    _zoomed.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.items;
    final n = items.length;
    final p = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, Sp.x2, Layout.gutter, Sp.x2),
          child: Row(children: [
            Expanded(
              child: n == 1
                  ? const SizedBox.shrink()
                  : ValueListenableBuilder<int>(
                      valueListenable: _at,
                      builder: (_, i, _) => Text('${i + 1} / $n', key: const Key('gallery-page'), style: context.text.titleSmall?.copyWith(color: p.text2)),
                    ),
            ),
            GlassIconButton(icon: Icons.close_rounded, tooltip: '关闭', onTap: () => Navigator.of(context).pop()),
          ]),
        ),
        Expanded(
          // 放大时锁住翻页（拖动交给图片平移），缩回原大再放开——photo_view 画廊的做法（scale state 非 initial 时锁 PageView）
          child: ValueListenableBuilder<bool>(
            valueListenable: _zoomed,
            builder: (_, zoomed, _) => PageView.builder(
              controller: _pages,
              itemCount: n,
              physics: zoomed ? const NeverScrollableScrollPhysics() : const PageScrollPhysics(),
              onPageChanged: (i) {
                _at.value = i;
                _zoomed.value = false; // 新的一页总是原大（旧页离屏即销毁，缩放随之复位）
              },
              itemBuilder: (_, i) => Semantics(
                label: '第 ${i + 1} 张，共 $n 张${(items[i].caption ?? '').isEmpty ? '' : '：${items[i].caption}'}',
                image: true,
                child: _ZoomPage(url: items[i].url, onZoom: (z) => _zoomed.value = z),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, Sp.x3, Layout.gutter, Sp.x4),
          child: ValueListenableBuilder<int>(
            valueListenable: _at,
            builder: (_, i, _) {
              final cap = items[i].caption?.trim() ?? '';
              return Row(children: [
                Expanded(child: Text(cap, style: context.text.bodyMedium, maxLines: 2, overflow: TextOverflow.ellipsis)),
                const SizedBox(width: Sp.x3),
                PillButton(label: '打开原图', icon: Icons.north_east_rounded, onTap: () => openUrl(items[i].url)),
              ]);
            },
          ),
        ),
      ],
    );
  }
}

/// 查看器的一页：捏合缩放（1–4 倍）+ 双击在原大与放大之间切换（以点按处为中心，Motion.base 过渡；减少动态直接到位）。
/// 缩放状态只在这一页里（TransformationController），是否放大通过 [onZoom] 告诉画廊去锁 / 放开翻页。
class _ZoomPage extends StatefulWidget {
  const _ZoomPage({required this.url, required this.onZoom});
  final String url;
  final ValueChanged<bool> onZoom;

  @override
  State<_ZoomPage> createState() => _ZoomPageState();
}

class _ZoomPageState extends State<_ZoomPage> with SingleTickerProviderStateMixin {
  static const _double = 2.5; // 双击放大到几倍
  final _t = TransformationController();
  late final AnimationController _anim = AnimationController(vsync: this, duration: Motion.base)..addListener(_step);
  Matrix4Tween? _tween;
  Offset _tap = Offset.zero;
  bool _zoomed = false;

  void _step() => _t.value = _tween!.evaluate(CurvedAnimation(parent: _anim, curve: Motion.ease));

  void _report() {
    final z = _t.value.getMaxScaleOnAxis() > 1.01;
    if (z != _zoomed) widget.onZoom(_zoomed = z);
  }

  void _toggle() {
    final target = _zoomed
        ? Matrix4.identity()
        : (Matrix4.identity()
          ..translateByDouble(-_tap.dx * (_double - 1), -_tap.dy * (_double - 1), 0, 1)
          ..scaleByDouble(_double, _double, 1, 1));
    if (context.reduceMotion) {
      _t.value = target;
    } else {
      _tween = Matrix4Tween(begin: _t.value, end: target);
      _anim.forward(from: 0);
    }
    widget.onZoom(_zoomed = !_zoomed);
  }

  @override
  void dispose() {
    _anim.dispose();
    _t.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => GestureDetector(
        onDoubleTapDown: (d) => _tap = d.localPosition,
        onDoubleTap: _toggle,
        child: InteractiveViewer(
          transformationController: _t,
          maxScale: 4,
          onInteractionStart: (_) => _anim.stop(),
          onInteractionEnd: (_) => _report(),
          child: _ViewerImage(widget.url),
        ),
      );
}

/// 查看器里的一张：整图按原比例放进页面（竖图、横图都不裁），底下不铺色块；下好了淡入；
/// 打不开时居中一个安静的坏图标 + 一行字，而不是满屏一块灰。
class _ViewerImage extends StatelessWidget {
  const _ViewerImage(this.url);
  final String url;

  @override
  Widget build(BuildContext context) => Image.network(
        url,
        fit: BoxFit.contain,
        width: double.infinity,
        height: double.infinity,
        frameBuilder: (c, child, frame, sync) => fadeInFrame(c, child, frame, sync),
        errorBuilder: (c, _, _) {
          final p = c.palette;
          return Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.broken_image_outlined, color: p.text3),
              const SizedBox(height: Sp.x2),
              Text('这张图片打不开', style: c.text.bodyMedium?.copyWith(color: p.text3)),
            ]),
          );
        },
      );
}
