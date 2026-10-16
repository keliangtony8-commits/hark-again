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
import 'haptics.dart';
import '../core/swr.dart';

/// 页面骨架：统一的左右留白 + 平板上限制最大宽度。
class PageBody extends StatelessWidget {
  const PageBody({super.key, required this.children, this.padding = const EdgeInsets.fromLTRB(Layout.gutter, Sp.x2, Layout.gutter, Sp.x7)});
  final List<Widget> children;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    // 安全区（含一级页面的浮动顶栏，见 shell/shell_page.dart）叠加在自己的留白上：内容能滚到顶栏下面
    final safe = MediaQuery.paddingOf(context);
    // 有待定位的设置项（v3.0 设置搜索直达）时多建一些屏外内容：长页（我的电脑）底部的区块才会被建出来、才找得到它
    final spot = SpotlightScope.maybeOf(context)?.pending ?? false;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Layout.contentMax),
        child: ListView(
            scrollCacheExtent: spot ? const ScrollCacheExtent.pixels(Layout.spotlightReach) : null,
            padding: padding + EdgeInsets.only(top: safe.top, bottom: safe.bottom),
            children: children),
      ),
    );
  }
}

/// 设置搜索直达（v3.0，“我的”页底部搜索，见 features/me/me_index.dart）：路由带 `?focus=<id>` 时，app.dart 在这页外面套一层，
/// 页里对应的 [Spotlight] 出现时滚到它并闪一下。同一次进页只亮一次（数据刷新、换态重建都不再亮）。
class SpotlightScope extends StatefulWidget {
  const SpotlightScope({super.key, required this.focus, required this.child});
  final String? focus;
  final Widget child;

  static SpotlightData? maybeOf(BuildContext context) => context.getInheritedWidgetOfExactType<SpotlightData>();

  @override
  State<SpotlightScope> createState() => _SpotlightScopeState();
}

class _SpotlightScopeState extends State<SpotlightScope> {
  final _done = <String>{};

  @override
  Widget build(BuildContext context) => SpotlightData._(widget.focus, _done, child: widget.child);
}

class SpotlightData extends InheritedWidget {
  const SpotlightData._(this.focus, this._done, {required super.child});
  final String? focus;
  final Set<String> _done;

  /// 还有一项等着被亮。
  bool get pending => focus != null && !_done.contains(focus);

  /// 是这一项、且还没亮过 → 记下并返回 true。
  bool claim(String id) => id == focus && _done.add(id);

  @override
  bool updateShouldNotify(SpotlightData old) => old.focus != focus;
}

/// 可被设置搜索定位的一项：[id] 与索引里的定位 id 相同。出现时（数据异步加载完才出现也行）滚到视口约 1/3 处，
/// 再用 [FlashHighlight] 闪一下（与搜索命中消息同一个高亮；减少动态时不滚动动画、底色直接出现到点消失）。
/// [row] = 分组里的一行：高亮铺满这一行（不外扩、不压分隔线）；否则是一整块（卡片 / 分区），底色是卡片外一圈等宽的光环。
class Spotlight extends StatefulWidget {
  const Spotlight({super.key, required this.id, required this.child, this.row = false});
  final String id;
  final Widget child;
  final bool row;

  @override
  State<Spotlight> createState() => _SpotlightState();
}

class _SpotlightState extends State<Spotlight> {
  int _play = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal());
  }

  Future<void> _reveal() async {
    final scope = SpotlightScope.maybeOf(context);
    if (scope == null || scope.focus != widget.id) return;
    // 区块的数据是异步取的（登录设备、电脑页各节）：内容出来之前高度为 0，滚过去只会闪一条空边。等到有内容再定位，超时就不闪。
    final deadline = DateTime.now().add(Timing.spotlightWait);
    while (mounted && (context.size?.height ?? 0) < 1) {
      if (DateTime.now().isAfter(deadline)) return;
      await Future<void>.delayed(Timing.spotlightPoll);
    }
    if (!mounted || !scope.claim(widget.id)) return;
    await Scrollable.ensureVisible(context, alignment: Layout.spotlightAt, duration: context.motion(Motion.slow), curve: Motion.ease);
    if (mounted) setState(() => _play++);
  }

  @override
  Widget build(BuildContext context) =>
      FlashHighlight(play: _play, outset: widget.row ? 0 : Sp.x2, radius: widget.row ? 0 : Radii.card + Sp.x2, child: widget.child);
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.title, {super.key, this.trailing, this.count});
  final String title;
  final Widget? trailing;

  /// 区块里有几项：和标题同一小字层级放在行尾（有 trailing 时以 trailing 为准）。
  final int? count;

  @override
  Widget build(BuildContext context) => Padding(
        // 区块之间留 32（v2.1 节奏）；标签本身不加粗：小字 + 字距 + text3。
        // v1.12：标题行固定一个触控高（A11y.minTap），有没有行尾按钮（全部已读 / 全部 N 个）节奏都一样——
        // 以前按钮把行撑高 ~28，带按钮的区块标题离下面的卡明显更远。上距 = 区块间距 − 行内留白。
        padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x5, Sp.x1, 0),
        child: SizedBox(
          height: A11y.minTap,
          child: Row(children: [
            Expanded(child: Text(title, style: context.text.labelSmall)),
            trailing ?? (count == null ? null : Text('$count', style: context.text.labelSmall)),
          ].nonNulls.toList()),
        ),
      );
}

/// 子页面页头（全 App 唯一，v2.97 E1 并入原“子页一句说明”组件）：一行小标签摘要（变化时换一下）+ 一句说明（也可变化）。
/// 子页面不再放大标题；层级 = 摘要小字 → 说明正文 text2 → 下面的分区。
/// 没有摘要（静态页：关于、偏好、“我的”分组页）时只有那句说明，下面留一个区块间距（列表行不带副标题，这一页是干什么的只在这里说一次）。
class PageIntro extends StatelessWidget {
  const PageIntro({super.key, this.summary, required this.line});
  final String? summary;
  final String line;

  @override
  Widget build(BuildContext context) {
    final text = Text(line, key: ValueKey(line), style: context.text.bodyMedium?.copyWith(color: context.palette.text2));
    final s = summary;
    if (s == null) {
      return FadeSlideIn(child: Padding(padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x2, Sp.x1, Sp.x5), child: text));
    }
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x2, Sp.x1, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SwapSwitcher(child: Text(s, key: ValueKey(s), style: context.text.labelSmall)),
          const SizedBox(height: Sp.x2),
          SwapSwitcher(child: text),
        ]),
      ),
    );
  }
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

/// 内容卡片：实色 surface、无描边（v2.80 F.2），和 GlassCard 同一材质，
/// 只是内边距紧一些：子页面、聊天里的块、弹层里都用它。给了 [color] 就是一张实色卡（强调/警示）。
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
        borderRadius: BorderRadius.circular(Radii.card),
      ),
      child: child,
    );
    return onTap == null ? card : Pressable(onTap: onTap, child: card);
  }
}

/// 分组列表（全 App 唯一，v2.97 E1）：一张玻璃卡里多行（行用 [ListRow]），行之间是从图标右侧开始的发丝线（和行首图标对齐），整卡一个大圆角。
class ListGroup extends StatelessWidget {
  const ListGroup({super.key, required this.children, this.separator});
  final List<Widget> children;

  /// 第 i 行（i ≥ 1）上方的分隔；返回 null 用默认细线（缩进到行首图标之后）。
  /// 用途：行首不是图标的列表把细线对齐到自己的标题边，或在两行之间放一条标记（主页“今天”的“现在”）。
  final Widget? Function(int i)? separator;

  @override
  Widget build(BuildContext context) {
    final line = context.hairline;
    return GlassSurface(
      shadow: false,
      padding: const EdgeInsets.symmetric(vertical: Sp.x1),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(Radii.card),
        child: Material(
          type: MaterialType.transparency, // 行里的 InkWell 水波纹画在玻璃上
          child: Column(children: [
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0) separator?.call(i) ?? Divider(indent: Sp.x4 + Layout.rowIcon + Sp.x4, endIndent: 0, color: line),
              children[i],
            ],
          ]),
        ),
      ),
    );
  }
}

/// 下拉刷新：转圈从让位线（浮动顶栏 / 玻璃标题栏下面）出来，而不是被它挡住。所有列表页用它，不直接用 RefreshIndicator。
class PullRefresh extends StatelessWidget {
  const PullRefresh({super.key, required this.onRefresh, required this.child});
  final RefreshCallback onRefresh;
  final Widget child;

  @override
  Widget build(BuildContext context) =>
      RefreshIndicator(
        onRefresh: () {
          Haptics.tap(); // v2.99：拉过阈值、开始刷新那一下轻触（松手才触发，拉着不放不会连震）
          return onRefresh();
        },
        edgeOffset: MediaQuery.paddingOf(context).top,
        child: child,
      );
}

/// 开关（全 App 唯一，v2.99）：系统 Switch + 切换时轻触一下（ui/haptics.dart）。页面不直接用 Switch（test/haptics_test.dart 守卫）。
class AppSwitch extends StatelessWidget {
  const AppSwitch({super.key, required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) => Switch(
        value: value,
        onChanged: onChanged == null
            ? null
            : (v) {
                Haptics.tap();
                onChanged!(v);
              },
      );
}

/// 列表行（全 App 唯一，v2.97 E1）：行首图标 + 标题（+ 副标题 / 问题）+ 行尾值 / 控件 / 箭头。放在 [ListGroup] 里。
/// 各页不再自己拼 InkWell + Padding + Row 的行；需要高亮搜索词或多行正文时用 [titleWidget] / [titleMaxLines]。
class ListRow extends StatelessWidget {
  const ListRow(
      {super.key, this.icon, required this.title, this.titleWidget, this.titleMaxLines = 1, this.subtitle, this.value, this.problem, this.trailing, this.onTap, this.onLongPress, this.leading, this.dimmed = false, this.semanticLabel});
  final IconData? icon;

  /// 代替标题文字的部件（记忆 / 笔记搜索时的 HighlightText）；[title] 仍要给，读屏和测试按它找。
  final Widget? titleWidget;

  /// 标题最多几行：设置类 1 行；记忆这类正文行给 3。
  final int titleMaxLines;

  /// 整行读屏念的一句（给了就合并成一个按钮节点，不逐个念子元素）。
  final String? semanticLabel;

  /// 行尾的当前值（“跟随系统”“中文”“toyuis.com”）：一行、次要色、放不下就省略，后面照常跟箭头——
  /// 设置类列表用它代替副标题，行高保持单行（v2.81 “我的”页减法）。
  final String? value;
  final Widget? leading;
  final String title;
  final String? subtitle;

  /// 这一行的问题（“连不上”）：只把这两三个字放在副标题最前面、用警示色，后面的说明保持原色——
  /// 一眼看到问题，又不让整行变成一片黄。
  final String? problem;
  final Widget? trailing;
  final VoidCallback? onTap;

  /// 长按：这一行的更多操作（收件箱行的“稍后再看/已读/收起”）。行尾最好同时给一颗可见的“更多”钮，长按只是捷径。
  final VoidCallback? onLongPress;

  /// 这一项是关着的（停用的技能、暂停的任务）：图标和文字变淡，行尾的开关/按钮保持原样——
  /// 控件一起淡掉看着像“点不了”（v1.08）。整行都不能用时才在外面包 Dimmed。
  final bool dimmed;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = ConstrainedBox(
      constraints: BoxConstraints(minHeight: subtitle == null ? Layout.rowMin : Layout.rowMinTwoLine),
      child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2),
      child: Row(children: [
        Expanded(
          child: Dimmed(
            dimmed: dimmed,
            child: Row(children: [
        if (leading != null || icon != null) ...[
          leading ?? IconBadge(icon!),
          const SizedBox(width: Sp.x4),
        ],
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            titleWidget ?? Text(title, style: context.text.titleMedium, maxLines: titleMaxLines, overflow: TextOverflow.ellipsis),
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
            ]),
          ),
        ),
        if (value != null) ...[
          const SizedBox(width: Sp.x3),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: Layout.rowValueMax),
            child: Text(value!, style: context.text.bodyMedium?.copyWith(color: p.text3), maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.end),
          ),
          const SizedBox(width: Sp.x1),
        ],
        if (trailing != null) trailing! else if (onTap != null) Icon(Icons.chevron_right_rounded, color: p.text3, size: Layout.rowIcon),
      ]),
      ),
    );
    final tile = onTap == null && onLongPress == null
        ? row
        : InkWell(onTap: onTap, onLongPress: onLongPress, borderRadius: BorderRadius.circular(Radii.inner), child: row);
    return semanticLabel == null ? tile : Semantics(container: true, button: onTap != null, label: semanticLabel, excludeSemantics: true, child: tile);
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
        child: value.swr( // 有数据就显示数据（core/swr.dart）：后台刷新、刷新失败都不换成骨架 / 错误
          loading: () => const PageBody(key: ValueKey('loading'), children: [SkeletonList(rows: 4)]),
          error: (e) => PageBody(key: const ValueKey('error'), children: [
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
  const RowHint(this.text, {super.key, this.warn = false});
  final String text;

  /// 需要用户注意（磁盘已满之类）：警示色。
  final bool warn;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: warn ? context.text.labelSmall?.copyWith(color: context.palette.warning) : context.text.labelSmall);
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

/// 搜索词：与后端 chat_search.terms 同规则——空格分开、引号（"…" “…” 「…」）里当一个词、不分大小写去重、最多 6 个。
List<String> searchTerms(String query) {
  final q = query.trim();
  final quote = RegExp(r'"([^"]+)"|“([^”]+)”|「([^」]+)」');
  final out = <String>[
    for (final m in quote.allMatches(q)) (m.group(1) ?? m.group(2) ?? m.group(3)!).trim(),
    ...q.replaceAll(quote, ' ').split(RegExp(r'\s+')),
  ];
  final seen = <String>{};
  return [for (final t in out) if (t.isNotEmpty && seen.add(t.toLowerCase())) t].take(6).toList();
}

/// 把每个搜索词在 text 里的所有出现（不分大小写）标亮；同一位置多个词都能匹配时取最长的。
List<TextSpan> highlightSpans(String text, String query, TextStyle hit) {
  final words = [for (final t in searchTerms(query)) t.toLowerCase()]..sort((a, b) => b.length - a.length);
  if (words.isEmpty) return [TextSpan(text: text)];
  final lower = text.toLowerCase();
  final out = <TextSpan>[];
  var from = 0, i = 0;
  while (i < lower.length) {
    final w = words.where((w) => lower.startsWith(w, i)).firstOrNull;
    if (w == null) {
      i++;
      continue;
    }
    if (i > from) out.add(TextSpan(text: text.substring(from, i)));
    out.add(TextSpan(text: text.substring(i, i + w.length), style: hit));
    i = from = i + w.length;
  }
  if (from < text.length) out.add(TextSpan(text: text.substring(from)));
  return out;
}

/// 圆角搜索框：右侧在加载时转圈、有字时给清除键。历史、记忆页和“我的”页底部设置搜索共用。
/// [floating]：放在玻璃胶囊里（“我的”页底部，v3.0）——不再叠一层 tile 底和聚焦描边，材质交给外面的玻璃。
class SearchField extends StatelessWidget {
  const SearchField(
      {super.key, required this.controller, required this.hint, required this.onChanged, required this.onClear, this.loading = false, this.floating = false, this.focusNode, this.onSubmitted});
  final TextEditingController controller;
  final String hint;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;
  final bool loading;
  final bool floating;
  final FocusNode? focusNode;
  final ValueChanged<String>? onSubmitted;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return TextField(
      controller: controller,
      focusNode: focusNode,
      onChanged: onChanged,
      onSubmitted: onSubmitted,
      textInputAction: TextInputAction.search,
      decoration: InputDecoration(
        hintText: hint,
        isDense: !floating,
        filled: !floating,
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
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.full), borderSide: floating ? BorderSide.none : BorderSide(color: p.text3)),
      ),
    );
  }
}

/// 底部一条提示；给了 [action] 就带一个按钮（“撤销”之类，点了调 [onAction]）。
void showToast(BuildContext context, String text, {String? action, VoidCallback? onAction}) =>
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(text),
        action: action == null ? null : SnackBarAction(label: action, textColor: context.palette.onInk, onPressed: onAction ?? () {}),
      ));

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

/// 横向滚动条的右缘渐隐（v1.16）：最后 [width] 宽从全显淡到透明，提示“右边还有”，不再被容器边硬切。
/// [width] 取滚动列表的右内边距，没溢出时内容到不了这一截，看不出任何变化。只改透明度，深浅色通用。
class EdgeFadeEnd extends StatelessWidget {
  const EdgeFadeEnd({super.key, required this.child, this.width = Sp.x3});
  final Widget child;
  final double width;

  @override
  Widget build(BuildContext context) {
    final ink = context.palette.text;
    return ShaderMask(
      shaderCallback: (r) => LinearGradient(
        colors: [ink, ink.withValues(alpha: 0)],
        stops: [r.width <= width ? 0 : 1 - width / r.width, 1],
      ).createShader(r),
      blendMode: BlendMode.dstIn,
      child: child,
    );
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
    Haptics.tap();
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
