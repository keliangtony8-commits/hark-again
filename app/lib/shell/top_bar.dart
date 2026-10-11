// 浮动顶栏（设计 v2）：[左侧上下文按钮的位置] [居中分段导航：主页/聊天/项目] [头像 → 我的]。
// 它浮在一级页面上面，内容从下面滚过去被模糊。左侧按钮属于页面（每个 Tab 不同），由 ShellPage 画在同一位置，
// 这里只留出空位、不挡点击——这样“导航”归外壳、“这一页能做什么”归页面，边界清楚。
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';

typedef TopTab = ({String label, int badge});

class FloatingTopBar extends StatelessWidget {
  const FloatingTopBar({super.key, required this.tabs, required this.index, required this.onSelect, required this.onAvatar, this.initial = '我', this.avatarColor});
  final List<TopTab> tabs;
  final int index;
  final ValueChanged<int> onSelect;
  final VoidCallback onAvatar;
  final String initial;
  final Color? avatarColor;

  @override
  Widget build(BuildContext context) => SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, Layout.topBarTop, Layout.gutter, Sp.x2),
          child: SizedBox(
            height: Layout.topBar,
            child: Row(children: [
              const SizedBox(width: Layout.topBar), // 页面的上下文按钮画在这里（ShellPage）
              const SizedBox(width: Sp.x3),
              Expanded(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: Layout.segmentsMax),
                    child: SegmentedNav(tabs: tabs, index: index, onSelect: onSelect),
                  ),
                ),
              ),
              const SizedBox(width: Sp.x3),
              Avatar(initial: initial, onTap: onAvatar, color: avatarColor),
            ]),
          ),
        ),
      );
}

/// 玻璃胶囊里的等分 Tab：选中项是一颗实心胶囊，切换时滑过去（motion.dart SlidingThumb），字色同步渐变。
class SegmentedNav extends StatelessWidget {
  const SegmentedNav({super.key, required this.tabs, required this.index, required this.onSelect});
  final List<TopTab> tabs;
  final int index;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return GlassSurface(
      blur: true,
      radius: Radii.full,
      // 滑块四周内缩一圈；可点区域是整条栏高（≥ A11y.minTap），只在横向内缩，与滑块对齐
      child: Stack(children: [
        Positioned.fill(
          child: Padding(
            padding: const EdgeInsets.all(Sp.x1),
            child: SlidingThumb(
              index: index,
              count: tabs.length,
              thumb: DecoratedBox(decoration: BoxDecoration(color: p.pillOn, borderRadius: BorderRadius.circular(Radii.full))),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
          child: Row(children: [
            for (var i = 0; i < tabs.length; i++)
              Expanded(child: _Segment(tab: tabs[i], selected: i == index, onTap: () => onSelect(i))),
          ]),
        ),
      ]),
    );
  }
}

class _Segment extends StatelessWidget {
  const _Segment({required this.tab, required this.selected, required this.onTap});
  final TopTab tab;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final badge = tab.badge > 0 ? '，${tab.badge} 条未读' : '';
    return Semantics(
      selected: selected,
      label: '${tab.label}$badge',
      button: true,
      excludeSemantics: true,
      onTap: onTap,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        // 未读点在这一段的右上角（胶囊内侧），不压在字上；字始终居中
        child: DotBadge(
          visible: tab.badge > 0,
          color: p.accent,
          size: Sp.x2,
          right: Sp.x3,
          top: Sp.x3,
          child: Center(
            child: AnimatedDefaultTextStyle(
              duration: context.motion(Motion.slow),
              curve: Motion.ease,
              style: context.text.labelLarge!.copyWith(fontSize: Fs.md, height: 1.2, fontWeight: Weights.title, color: selected ? p.onPillOn : p.text2),
              child: Padding(padding: const EdgeInsets.symmetric(horizontal: Sp.x2), child: Text(tab.label, maxLines: 1)),
            ),
          ),
        ),
      ),
    );
  }
}
