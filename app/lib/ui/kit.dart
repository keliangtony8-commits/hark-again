// 基础界面零件：分组列表、行、卡片、空状态、分区标题。
// 各页面只拼这些，间距/圆角/颜色全部来自令牌，保证整个 App 版式统一。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass.dart';
import 'motion.dart';

/// 页面骨架：统一的左右留白 + 平板上限制最大宽度。
class PageBody extends StatelessWidget {
  const PageBody({super.key, required this.children, this.padding = const EdgeInsets.fromLTRB(Layout.gutter, Sp.x2, Layout.gutter, Sp.x7)});
  final List<Widget> children;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    // 安全区（含一级页面的浮动顶栏，见 shell/shell_page.dart）叠加在自己的留白上：内容能滚到顶栏下面
    final safe = MediaQuery.paddingOf(context);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Layout.contentMax),
        child: ListView(padding: padding + EdgeInsets.only(top: safe.top, bottom: safe.bottom), children: children),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.title, {super.key, this.trailing, this.count});
  final String title;
  final Widget? trailing;

  /// 区块里有几项：和标题同一小字层级放在行尾（有 trailing 时以 trailing 为准）。
  final int? count;

  @override
  Widget build(BuildContext context) => Padding(
        // 区块之间留 32（v2.1 节奏）；标签本身不加粗：小字 + 字距 + text3
        padding: const EdgeInsets.fromLTRB(Sp.x1, Layout.sectionGap - Sp.x3, Sp.x1, Sp.x3),
        child: Row(children: [
          Expanded(child: Text(title, style: context.text.labelSmall)),
          trailing ?? (count == null ? null : Text('$count', style: context.text.labelSmall)),
        ].nonNulls.toList()),
      );
}

/// 子页面页头（v0.75 起各“我的”子页共用）：一行小标签摘要（变化时换一下）+ 一句说明（也可变化）。
/// 子页面不再放大标题；层级 = 摘要小字 → 说明正文 text2 → 下面的分区。
class PageIntro extends StatelessWidget {
  const PageIntro({super.key, required this.summary, required this.line});
  final String summary, line;

  @override
  Widget build(BuildContext context) => FadeSlideIn(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x2, Sp.x1, 0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SwapSwitcher(child: Text(summary, key: ValueKey(summary), style: context.text.labelSmall)),
            const SizedBox(height: Sp.x2),
            SwapSwitcher(child: Text(line, key: ValueKey(line), style: context.text.bodyMedium?.copyWith(color: context.palette.text2))),
          ]),
        ),
      );
}

/// 起步卡：列表为空时代替“空空如也”——标题 + 一句引导 + 一排起步按钮（PillButton）。
/// 点按钮只是带内容打开新建表单，用户没确认前什么都不会存。
class StarterCard extends StatelessWidget {
  const StarterCard({super.key, required this.title, required this.text, required this.starters});
  final String title, text;
  final List<Widget> starters;

  @override
  Widget build(BuildContext context) => FadeSlideIn(
        child: AppCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: context.text.titleSmall),
            const SizedBox(height: Sp.x1),
            Text(text, style: context.text.bodySmall?.copyWith(color: context.palette.text2)),
            const SizedBox(height: Sp.x3),
            Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: starters),
          ]),
        ),
      );
}

/// 内容卡片（设计 v2）：默认是“假玻璃”——玻璃着色 + 1px 发丝边、不模糊不投影，和 GlassCard 同一材质，
/// 只是圆角小一号（Radii.lg）、内边距紧一些：子页面、聊天里的块、弹层里都用它。给了 [color] 就是一张实色卡（强调/警示）。
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.onTap, this.padding = const EdgeInsets.all(Sp.x4), this.color});
  final Widget child;
  final VoidCallback? onTap;
  final EdgeInsets padding;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final card = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color ?? context.cardFill,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: context.hairline),
      ),
      child: child,
    );
    final lit = color == null ? GlassHighlight(radius: Radii.lg, child: card) : card;
    return onTap == null ? lit : Pressable(onTap: onTap, child: lit);
  }
}

/// iOS 设置风格的分组列表 = GlassGroup（一张玻璃卡里多行，行间发丝线和行首图标对齐）。
/// 保留这个名字是为了子页面读起来顺；实现只有一份，在 ui/glass.dart。
class ListGroup extends StatelessWidget {
  const ListGroup({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => GlassGroup(children: children);
}

/// 下拉刷新：转圈从让位线（浮动顶栏 / 玻璃标题栏下面）出来，而不是被它挡住。所有列表页用它，不直接用 RefreshIndicator。
class PullRefresh extends StatelessWidget {
  const PullRefresh({super.key, required this.onRefresh, required this.child});
  final RefreshCallback onRefresh;
  final Widget child;

  @override
  Widget build(BuildContext context) =>
      RefreshIndicator(onRefresh: onRefresh, edgeOffset: MediaQuery.paddingOf(context).top, child: child);
}

class RowTile extends StatelessWidget {
  const RowTile({super.key, this.icon, required this.title, this.subtitle, this.problem, this.trailing, this.onTap, this.leading});
  final IconData? icon;
  final Widget? leading;
  final String title;
  final String? subtitle;

  /// 这一行的问题（“连不上”）：只把这两三个字放在副标题最前面、用警示色，后面的说明保持原色——
  /// 一眼看到问题，又不让整行变成一片黄。
  final String? problem;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = ConstrainedBox(
      constraints: BoxConstraints(minHeight: subtitle == null ? Layout.rowMin : Layout.rowMinTwoLine),
      child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2),
      child: Row(children: [
        if (leading != null || icon != null) ...[
          leading ?? IconBadge(icon!),
          const SizedBox(width: Sp.x4),
        ],
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
            if (problem != null)
              Text.rich(
                TextSpan(children: [
                  TextSpan(text: problem, style: TextStyle(color: p.warning, fontWeight: Weights.title)),
                  if (subtitle != null) TextSpan(text: ' · $subtitle'),
                ]),
                style: context.text.bodySmall,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              )
            else if (subtitle != null)
              Text(subtitle!, style: context.text.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
          ]),
        ),
        if (trailing != null) trailing! else if (onTap != null) Icon(Icons.chevron_right_rounded, color: p.text3, size: Layout.rowIcon),
      ]),
      ),
    );
    return onTap == null ? row : InkWell(onTap: onTap, borderRadius: BorderRadius.circular(Radii.md), child: row);
  }
}

/// 行首图标（v2.1）：细线图标、正文二级色、不加色块底——列表靠排版分层，不靠一排彩色方块。
/// [size] 是占位宽度（行首对齐线），图标本身 = Layout.rowIcon；空状态这类大图标给大 size 时按比例放大。
class IconBadge extends StatelessWidget {
  const IconBadge(this.icon, {super.key, this.size = Layout.rowIcon});
  final IconData icon;
  final double size;

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: size,
        child: Icon(icon, size: size, color: context.palette.text2, weight: 300),
      );
}

/// 空状态：图标 + 标题 + 一句说明 + 可选按钮。
class EmptyHint extends StatelessWidget {
  const EmptyHint({super.key, required this.icon, required this.title, required this.text, this.action});
  final IconData icon;
  final String title;
  final String text;
  final Widget? action;

  @override
  Widget build(BuildContext context) => FadeSlideIn(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: Sp.x7, horizontal: Sp.x5),
          child: Column(children: [
            Icon(icon, size: Sp.x7 - Sp.x2, color: context.palette.text3, weight: 300),
            const SizedBox(height: Sp.x4),
            Text(title, style: context.text.titleMedium, textAlign: TextAlign.center),
            const SizedBox(height: Sp.x1),
            Text(text, style: context.text.bodyMedium?.copyWith(color: context.palette.text2), textAlign: TextAlign.center),
            if (action != null) ...[const SizedBox(height: Sp.x4), action!],
          ]),
        ),
      );
}

/// 加载占位：几行骨架。
class SkeletonList extends StatelessWidget {
  const SkeletonList({super.key, this.rows = 3});
  final int rows;

  @override
  Widget build(BuildContext context) => Column(
        children: [for (var i = 0; i < rows; i++) const Padding(padding: EdgeInsets.only(bottom: Sp.x2), child: Shimmer())],
      );
}

/// 列表页的统一三态（交叉淡化切换）：加载 = 骨架，失败 = 提示 + 重试，空 = [empty]，有数据 = [builder]。
class AsyncBody<T> extends StatelessWidget {
  const AsyncBody({super.key, required this.value, required this.builder, this.empty, this.onRetry});
  final AsyncValue<List<T>> value;
  final Widget Function(List<T>) builder;
  final Widget? empty;
  final VoidCallback? onRetry;

  /// 四态各有自己的 key：骨架 → 内容（或空 / 出错）交叉淡化；同一态内的数据更新不触发过渡。
  @override
  Widget build(BuildContext context) => FadeSwitcher(
        child: value.when(
          skipLoadingOnReload: true,
          loading: () => const PageBody(key: ValueKey('loading'), children: [SkeletonList(rows: 4)]),
          error: (e, _) => PageBody(key: const ValueKey('error'), children: [
            EmptyHint(
              icon: Icons.cloud_off_rounded,
              title: '加载失败',
              text: '$e',
              action: onRetry == null ? null : OutlinedButton(onPressed: onRetry, child: const Text('重试')),
            ),
          ]),
          data: (list) => list.isEmpty && empty != null
              ? PageBody(key: const ValueKey('empty'), children: [empty!])
              : KeyedSubtree(key: const ValueKey('data'), child: builder(list)),
        ),
      );
}

/// 左滑删除（列表行通用）。[confirm] 不为空时先确认，返回 false 则回弹。
class SwipeToDelete extends StatelessWidget {
  const SwipeToDelete({super.key, required this.id, required this.onDelete, required this.child, this.confirm});
  final String id;
  final VoidCallback onDelete;
  final Future<bool> Function()? confirm;
  final Widget child;

  @override
  Widget build(BuildContext context) => Dismissible(
        key: ValueKey(id),
        direction: DismissDirection.endToStart,
        confirmDismiss: confirm == null ? null : (_) => confirm!(),
        background: Container(
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: Sp.x5),
          child: Icon(Icons.delete_outline_rounded, color: context.palette.danger),
        ),
        onDismissed: (_) => onDelete(),
        child: child,
      );
}

/// 小状态标签：已连接 / 内置 / 登录……[strong] 用强调色。
/// 行尾的状态小字（“已连接”“带令牌”）：状态只是说明，不做成按钮的样子——能点的动作才用 PillButton(dense)。
class RowHint extends StatelessWidget {
  const RowHint(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Text(text, style: context.text.labelSmall);
}

class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.strong = false});
  final String text;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return AnimatedContainer(
      duration: Motion.base,
      curve: Motion.ease,
      padding: const EdgeInsets.symmetric(horizontal: Sp.x2, vertical: 2),
      // strong 不再是橙色：墨色细边 + 正文色字，安静但看得出“这个是开着的”
      decoration: BoxDecoration(
        color: strong ? null : context.tileFill,
        border: Border.all(color: strong ? p.text3 : Colors.transparent),
        borderRadius: BorderRadius.circular(Radii.full),
      ),
      child: Text(text, style: context.text.labelMedium?.copyWith(color: strong ? p.text : p.text2)),
    );
  }
}

/// 把文字里命中 [query] 的部分（不分大小写）用强调色标出来：搜索结果用。
class HighlightText extends StatelessWidget {
  const HighlightText(this.text, {super.key, required this.query, this.style, this.maxLines = 1});
  final String text, query;
  final TextStyle? style;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    final base = style ?? DefaultTextStyle.of(context).style;
    final hit = base.copyWith(color: context.palette.accent, fontWeight: Weights.strong);
    return Text.rich(TextSpan(style: base, children: highlightSpans(text, query, hit)), maxLines: maxLines, overflow: TextOverflow.ellipsis);
  }
}

List<TextSpan> highlightSpans(String text, String query, TextStyle hit) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return [TextSpan(text: text)];
  final lower = text.toLowerCase();
  final out = <TextSpan>[];
  var from = 0;
  for (var i = lower.indexOf(q); i >= 0; i = lower.indexOf(q, from)) {
    if (i > from) out.add(TextSpan(text: text.substring(from, i)));
    out.add(TextSpan(text: text.substring(i, i + q.length), style: hit));
    from = i + q.length;
  }
  if (from < text.length) out.add(TextSpan(text: text.substring(from)));
  return out;
}

/// 圆角搜索框：右侧在加载时转圈、有字时给清除键。历史和记忆页共用。
class SearchField extends StatelessWidget {
  const SearchField({super.key, required this.controller, required this.hint, required this.onChanged, required this.onClear, this.loading = false});
  final TextEditingController controller;
  final String hint;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return TextField(
      controller: controller,
      onChanged: onChanged,
      textInputAction: TextInputAction.search,
      decoration: InputDecoration(
        hintText: hint,
        isDense: true,
        filled: true,
        fillColor: context.tileFill,
        prefixIcon: Icon(Icons.search_rounded, color: p.text3),
        suffixIcon: AnimatedSwitcher(
          duration: Motion.fast,
          child: loading
              ? Padding(
                  key: const ValueKey('loading'),
                  padding: const EdgeInsets.all(Sp.x3),
                  child: SizedBox.square(dimension: Sp.x4, child: CircularProgressIndicator(strokeWidth: 2, color: p.text3)),
                )
              : controller.text.isEmpty
                  ? const SizedBox.shrink(key: ValueKey('none'))
                  : IconButton(key: const ValueKey('clear'), icon: const Icon(Icons.close_rounded), tooltip: '清除', onPressed: onClear),
        ),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.full), borderSide: BorderSide.none),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.full), borderSide: BorderSide.none),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.full), borderSide: BorderSide(color: p.text3)),
      ),
    );
  }
}

void showToast(BuildContext context, String text) =>
    ScaffoldMessenger.of(context)..hideCurrentSnackBar()..showSnackBar(SnackBar(content: Text(text)));

/// 浮在内容底部的一条（输入胶囊）：内容铺满到底、从它下面滚过去。
/// 它量出底条的实际高度（多行、附件托盘、编辑条都会变高）加进 MediaQuery.padding.bottom，
/// 所以里面的列表 / PageBody 照常读安全区就会让位——和 ShellPage 让出顶栏是同一个做法。
/// behind：画在内容和底条之间的一层（输入框聚焦时的 FrostScrim）。
class FloatingFooter extends StatefulWidget {
  const FloatingFooter({super.key, required this.footer, required this.child, this.behind});
  final Widget footer;
  final Widget child;
  final Widget? behind;

  @override
  State<FloatingFooter> createState() => _FloatingFooterState();
}

class _FloatingFooterState extends State<FloatingFooter> {
  double _height = 0;

  void _onSize(Size s) {
    if (mounted && s.height != _height) setState(() => _height = s.height);
  }

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    return Stack(children: [
      MediaQuery(
        data: mq.copyWith(padding: mq.padding.copyWith(bottom: _height > mq.padding.bottom ? _height : mq.padding.bottom)),
        child: widget.child,
      ),
      if (widget.behind != null) Positioned.fill(child: widget.behind!),
      Positioned(left: 0, right: 0, bottom: 0, child: _SizeReporter(onSize: _onSize, child: widget.footer)),
    ]);
  }
}

class _SizeReporter extends SingleChildRenderObjectWidget {
  const _SizeReporter({required this.onSize, super.child});
  final ValueChanged<Size> onSize;

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderSizeReporter(onSize);

  @override
  void updateRenderObject(BuildContext context, _RenderSizeReporter renderObject) => renderObject.onSize = onSize;
}

class _RenderSizeReporter extends RenderProxyBox {
  _RenderSizeReporter(this.onSize);
  ValueChanged<Size> onSize;
  Size? _last;

  @override
  void performLayout() {
    super.performLayout();
    if (size == _last) return;
    _last = size;
    final s = size;
    WidgetsBinding.instance.addPostFrameCallback((_) => onSize(s)); // 布局中不能 setState：下一帧再报
  }
}

/// 长内容折起：最多露出 [maxHeight] 高，底边渐隐提示“还有”（摘要卡展开前）。只在确实很长时用。
class FoldedBox extends StatelessWidget {
  const FoldedBox({super.key, required this.maxHeight, required this.child});
  final double maxHeight;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final ink = context.palette.text;
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: ShaderMask(
        // 遮罩只看透明度：上面 70% 全显，往下渐隐到 0
        shaderCallback: (r) => LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [ink, ink.withValues(alpha: 0)],
          stops: const [0.7, 1],
        ).createShader(r),
        blendMode: BlendMode.dstIn,
        child: SingleChildScrollView(physics: const NeverScrollableScrollPhysics(), child: child),
      ),
    );
  }
}

/// 内容从浮动顶栏下面滚过时的上沿渐隐：[clear] 以上完全透明（露出壁纸，不和顶栏/标题叠字），
/// 到 [solid] 按缓入曲线渐变成全显（线性渐变在深色墨气泡上会显出一道硬边，v0.92 修）。
/// 只改透明度、不画颜色，所以和任何壁纸/深浅色都对得上。一级页面外框（ShellPage）用它。
class TopFade extends StatelessWidget {
  const TopFade({super.key, required this.clear, required this.solid, required this.child});
  final double clear;
  final double solid;
  final Widget child;

  /// 渐变的采样点（0..1 在 clear→solid 之间）和对应透明度：easeInOut 采样，头尾都柔。
  static const ramp = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0];
  static double alphaAt(double x) => Curves.easeInOut.transform(x.clamp(0.0, 1.0));

  @override
  Widget build(BuildContext context) {
    final ink = context.palette.text;
    return ShaderMask(
      blendMode: BlendMode.dstIn,
      shaderCallback: (r) {
        final h = r.height <= 0 ? 1.0 : r.height;
        final a = (clear / h).clamp(0.0, 1.0);
        final b = (solid / h).clamp(a, 1.0);
        return LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [ink.withValues(alpha: 0), for (final x in ramp) ink.withValues(alpha: alphaAt(x)), ink],
          stops: [0, for (final x in ramp) a + (b - a) * x, 1],
        ).createShader(r);
      },
      child: child,
    );
  }
}

/// 一段还在变长的文字只露出“最后几行”：固定高度、底对齐，顶上一截渐隐（像滚动的字幕）。
/// 用于思考过程这类只关心最新进展的流式文字；lines 决定露几行，按 style 的字号和行高算高度。
class TailText extends StatelessWidget {
  const TailText(this.text, {super.key, required this.style, this.lines = 2});
  final String text;
  final TextStyle style;
  final int lines;

  @override
  Widget build(BuildContext context) {
    final scale = MediaQuery.textScalerOf(context);
    final lineH = scale.scale(style.fontSize ?? Fs.sm) * (style.height ?? Fs.lineHeight);
    return SizedBox(
      height: lineH * lines,
      child: ShaderMask(
        // 遮罩只看透明度：上面 0 → 第一行中间 1，颜色本身不画出来
        shaderCallback: (r) => LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [style.color!.withValues(alpha: 0), style.color!],
          stops: [0, 0.5 / lines],
        ).createShader(r),
        blendMode: BlendMode.dstIn,
        child: ClipRect(
          child: OverflowBox(
            alignment: Alignment.bottomLeft,
            minHeight: 0,
            maxHeight: double.infinity,
            child: Text(text, style: style),
          ),
        ),
      ),
    );
  }
}

/// 内容下方那排“安静的”小图标键（回复的复制 / 朗读 / 重新生成）：18px、text3，点按区仍是紧凑 IconButton。
/// icon 换状态时用 PopSwitcher（给 icon 一个随状态变化的 key）。整排图标长相只在这里定。
class QuietAction extends StatelessWidget {
  const QuietAction({super.key, required this.icon, required this.tooltip, required this.onPressed});
  final Widget icon;
  final String tooltip;
  final VoidCallback? onPressed;
  static const iconSize = 18.0;

  @override
  Widget build(BuildContext context) => IconButton(
        onPressed: onPressed,
        tooltip: tooltip,
        iconSize: iconSize,
        color: context.palette.text3,
        visualDensity: VisualDensity.compact,
        icon: PopSwitcher(child: icon),
      );
}

/// 复制键：点了把 [text] 放进剪贴板，图标变对勾停 Timing.copiedHold 再变回去（对勾本身就是确认，不再弹提示条）；
/// 读屏会念“已复制”。
class CopyAction extends StatefulWidget {
  const CopyAction({super.key, required this.text, this.tooltip = '复制'});
  final String text;
  final String tooltip;

  @override
  State<CopyAction> createState() => _CopyActionState();
}

class _CopyActionState extends State<CopyAction> {
  Timer? _reset;
  bool get _done => _reset?.isActive ?? false;

  void _copy() {
    Clipboard.setData(ClipboardData(text: widget.text));
    HapticFeedback.selectionClick();
    SemanticsService.sendAnnouncement(View.of(context), '已复制', Directionality.of(context));
    _reset?.cancel();
    setState(() => _reset = Timer(Timing.copiedHold, () {
          if (mounted) setState(() {});
        }));
  }

  @override
  void dispose() {
    _reset?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => QuietAction(
        tooltip: _done ? '已复制' : widget.tooltip,
        onPressed: _copy,
        icon: _done
            ? Icon(Icons.check_rounded, key: const ValueKey('copied'), color: context.palette.text2)
            : const Icon(Icons.content_copy_rounded, key: ValueKey('copy')),
      );
}
