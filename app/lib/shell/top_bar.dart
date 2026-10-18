// 浮动顶栏（设计 v2）：[左侧上下文按钮的位置] [居中分段导航：主页/聊天/项目] [头像 → 我的]。
// v3.5.1 照 Hark：“我的”是第四个分支，index 超出分段数（= 3）即“我的”是当前项——三个分段都不选中（滑块淡出、停在原位），头像外圈亮起。
// 它浮在一级页面上面，内容从下面滚过去被模糊。左侧按钮属于页面（每个 Tab 不同），由 ShellPage 画在同一位置，
// 这里只留出空位、不挡点击——这样“导航”归外壳、“这一页能做什么”归页面，边界清楚。
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';

typedef TopTab = ({String label, int badge});

class FloatingTopBar extends StatelessWidget {
  const FloatingTopBar({super.key, required this.tabs, required this.index, required this.onSelect, required this.onAvatar, this.initial = '我', this.avatarColor, this.image});
  final List<TopTab> tabs;
  final int index;
  final ValueChanged<int> onSelect;
  final VoidCallback onAvatar;
  final String initial;
  final Color? avatarColor;
  final String? image; // v2.92 §P 上传的头像（完整地址）

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
              _AvatarTab(selected: index >= tabs.length, child: Avatar(initial: initial, onTap: onAvatar, color: avatarColor, image: image)),
            ]),
          ),
        ),
      );
}

/// 玻璃胶囊里的等分 Tab：选中项是一颗实心胶囊，切换时滑过去（motion.dart SlidingThumb），字色同步渐变。
/// [index] 不在分段里（当前是“我的”）时滑块淡出、停在上一次的位置；回来时在原位淡入再滑到新位置——只动 opacity / transform。
class SegmentedNav extends StatefulWidget {
  const SegmentedNav({super.key, required this.tabs, required this.index, required this.onSelect});
  final List<TopTab> tabs;
  final int index;
  final ValueChanged<int> onSelect;

  @override
  State<SegmentedNav> createState() => _SegmentedNavState();
}

class _SegmentedNavState extends State<SegmentedNav> {
  late int _at = _inRange(widget.index) ? widget.index : 0; // 滑块所在的分段（当前项不在分段里时保持不动）

  bool _inRange(int i) => i >= 0 && i < widget.tabs.length;

  @override
  void didUpdateWidget(SegmentedNav old) {
    super.didUpdateWidget(old);
    if (_inRange(widget.index)) _at = widget.index;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final tabs = widget.tabs;
    final on = _inRange(widget.index);
    return GlassSurface(
      blur: true,
      probe: PerfBlur.topBar, // v3.5.3 性能自检“只关顶栏模糊”
      radius: Radii.full,
      // 滑块四周内缩一圈；可点区域是整条栏高（≥ A11y.minTap），只在横向内缩，与滑块对齐
      child: Stack(children: [
        Positioned.fill(
          child: Padding(
            padding: const EdgeInsets.all(Sp.x1),
            child: AnimatedOpacity(
              key: const Key('nav-thumb'),
              opacity: on ? 1 : 0,
              duration: context.motion(Motion.base),
              curve: Motion.ease,
              child: SlidingThumb(
                index: _at,
                count: tabs.length,
                thumb: DecoratedBox(decoration: BoxDecoration(color: p.pillOn, borderRadius: BorderRadius.circular(Radii.full))),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
          child: Row(children: [
            for (var i = 0; i < tabs.length; i++)
              Expanded(child: _Segment(tab: tabs[i], selected: i == widget.index, onTap: () => widget.onSelect(i))),
          ]),
        ),
      ]),
    );
  }
}

/// 头像作为“我的”这一项：当前项时外圈亮起一道 pillOn 色的环（= 选中分段滑块的颜色），淡入淡出；读屏报“已选中”。
/// 环画在头像外面（不改头像尺寸、不触发布局），只动 opacity。
class _AvatarTab extends StatelessWidget {
  const _AvatarTab({required this.selected, required this.child});
  final bool selected;
  final Widget child;

  static const _ring = 2.0; // 环宽

  @override
  Widget build(BuildContext context) => Semantics(
        selected: selected,
        child: Stack(clipBehavior: Clip.none, children: [
          child,
          Positioned(
            left: -_ring - 1,
            top: -_ring - 1,
            right: -_ring - 1,
            bottom: -_ring - 1,
            child: IgnorePointer(
              child: AnimatedOpacity(
                key: const Key('avatar-ring'),
                opacity: selected ? 1 : 0,
                duration: context.motion(Motion.base),
                curve: Motion.ease,
                child: DecoratedBox(decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: context.palette.pillOn, width: _ring))),
              ),
            ),
          ),
        ]),
      );
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
          color: selected ? p.onPillOn : p.accent, // v3.1 选中段是白胶囊：白点会只剩一圈描边，像“°”
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
