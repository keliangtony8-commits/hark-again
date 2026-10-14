// 长按 = 原地聚焦菜单（home-redesign §J，对标 Hark 截图 1000035388）。全 App 唯一的“长按菜单”，取代 v2.84 的底部动作 Sheet。
// 样子：整屏重度模糊变暗（FrostLayer, Glass.focusBlur）；被按的那条留在原位、保持清晰（它的快照放回原处，轻微放大 2% 再落回）；
// 紧贴它下方（放不下就上方，再放不下就贴屏幕底）、和它同侧对齐弹出一张菜单卡：一行 = 图标 + 一个词；点空白处 / 返回键收起。
// 菜单项沿用 ui/sheets.dart 的 SheetAction（同一份动作，不另造类型）；超过 Layout.focusMenuRows 行时前几行 + “更多”原地展开。
// 动效只用 motion.dart 的时长（减弱动效 = 直接出现）；打开时 mediumImpact 震一下。
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass.dart';
import 'motion.dart';
import 'sheets.dart';

/// 包住一条可长按的内容：长按 → 聚焦菜单。actions 在长按那一刻才取（状态最新）；返回空列表 = 不弹。
class FocusPressable extends StatefulWidget {
  const FocusPressable({super.key, required this.child, required this.actions, this.alignEnd = false, this.enabled = true});
  final Widget child;
  final List<SheetAction<void>> Function() actions;

  /// 菜单卡和内容右对齐（用户气泡在右侧）。
  final bool alignEnd;
  final bool enabled;

  @override
  State<FocusPressable> createState() => _FocusPressableState();
}

class _FocusPressableState extends State<FocusPressable> {
  final _boundary = GlobalKey();

  Future<void> _open() async {
    final actions = widget.actions();
    if (actions.isEmpty) return;
    final box = _boundary.currentContext?.findRenderObject();
    if (box is! RenderRepaintBoundary || !box.hasSize) return;
    final rect = box.localToGlobal(Offset.zero) & box.size;
    ui.Image? shot;
    try {
      shot = box.toImageSync(pixelRatio: MediaQuery.devicePixelRatioOf(context));
    } catch (_) {
      shot = null; // 拍不到快照（极少数平台）：照样弹菜单，只是被按的那条也在模糊层下面
    }
    HapticFeedback.mediumImpact();
    await showFocusMenu(context, rect: rect, shot: shot, actions: actions, alignEnd: widget.alignEnd);
    shot?.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final body = RepaintBoundary(key: _boundary, child: widget.child);
    if (!widget.enabled) return body;
    return Semantics(
      onLongPressHint: '更多操作',
      child: GestureDetector(onLongPress: _open, child: body),
    );
  }
}

/// 弹出聚焦菜单：rect = 被按内容在屏幕上的位置，shot = 它的快照（放回原位、不被模糊）。点了某项 = 先收起再执行它。
Future<void> showFocusMenu(BuildContext context,
    {required Rect rect, ui.Image? shot, required List<SheetAction<void>> actions, bool alignEnd = false}) async {
  final picked = await Navigator.of(context, rootNavigator: true).push<SheetAction<void>>(PageRouteBuilder(
    opaque: false,
    barrierDismissible: false, // 点空白由 FrostLayer 自己收（它要拦住点击并带读屏标签）
    transitionDuration: context.motion(Motion.base),
    reverseTransitionDuration: context.motion(Motion.fast),
    pageBuilder: (ctx, anim, _) => _FocusMenuPage(anim: anim, rect: rect, shot: shot, actions: actions, alignEnd: alignEnd),
  ));
  picked?.onTap?.call();
}

class _FocusMenuPage extends StatefulWidget {
  const _FocusMenuPage({required this.anim, required this.rect, required this.shot, required this.actions, required this.alignEnd});
  final Animation<double> anim;
  final Rect rect;
  final ui.Image? shot;
  final List<SheetAction<void>> actions;
  final bool alignEnd;

  @override
  State<_FocusMenuPage> createState() => _FocusMenuPageState();
}

class _FocusMenuPageState extends State<_FocusMenuPage> {
  bool _more = false;

  List<SheetAction<void>> get _shown {
    final all = widget.actions;
    if (_more || all.length <= Layout.focusMenuRows) return all;
    return all.take(Layout.focusMenuRows - 1).toList();
  }

  bool get _hasMore => !_more && widget.actions.length > Layout.focusMenuRows;

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final pad = MediaQuery.paddingOf(context);
    final r = widget.rect;
    final rows = _shown.length + (_hasMore ? 1 : 0);
    final menuH = rows * A11y.minTap + Sp.x2 * 2;
    final width = math.min(Layout.focusMenuWidth, size.width - Layout.gutter * 2);
    // 竖直：下方放得下 → 下方；否则上方；都不行 → 贴屏幕底（盖在长内容上）
    final low = size.height - pad.bottom - Sp.x4;
    final high = pad.top + Sp.x4;
    final below = r.bottom + Sp.x2 + menuH <= low;
    final above = !below && r.top - Sp.x2 - menuH >= high;
    final top = below ? r.bottom + Sp.x2 : (above ? r.top - Sp.x2 - menuH : low - menuH);
    // 横向：和内容同侧对齐，夹在左右留白之内
    final left = (widget.alignEnd ? r.right - width : r.left).clamp(Layout.gutter / 2, size.width - Layout.gutter / 2 - width).toDouble();
    final origin = Alignment(widget.alignEnd ? 1 : -1, below ? -1 : 1);
    final curved = CurvedAnimation(parent: widget.anim, curve: Motion.ease);

    final menu = GlassSurface(
      radius: Radii.card, // 实色卡面 + 浮层淡投影（glass.dart 唯一投影）
      child: Material(
        type: MaterialType.transparency,
        borderRadius: BorderRadius.circular(Radii.card),
        clipBehavior: Clip.antiAlias,
        child: AnimatedSize(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          alignment: below ? Alignment.topCenter : Alignment.bottomCenter,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: Sp.x2),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              for (final a in _shown) _MenuRow(icon: a.icon, label: a.label, danger: a.danger, onTap: () => Navigator.of(context).pop(a)),
              if (_hasMore)
                _MenuRow(
                  icon: Icons.more_horiz_rounded,
                  label: '更多',
                  onTap: () {
                    HapticFeedback.selectionClick();
                    setState(() => _more = true);
                  },
                ),
            ]),
          ),
        ),
      ),
    );

    return Stack(children: [
      Positioned.fill(
        child: AnimatedBuilder(
          animation: curved,
          builder: (context, _) => FrostLayer(t: curved.value, blur: Glass.focusBlur, semanticLabel: '关闭菜单', onTap: () => Navigator.of(context).pop()),
        ),
      ),
      if (widget.shot != null)
        Positioned.fromRect(
          rect: r,
          child: IgnorePointer(
            child: AnimatedBuilder(
              animation: widget.anim,
              // 先放大 2% 再落回（正弦一个来回）；收起时不再放大
              builder: (context, child) => Transform.scale(
                scale: 1 + Motion.focusLift * math.sin(math.pi * widget.anim.value) * (widget.anim.status == AnimationStatus.reverse ? 0 : 1),
                child: child,
              ),
              child: RawImage(image: widget.shot, width: r.width, height: r.height, fit: BoxFit.fill),
            ),
          ),
        ),
      Positioned(
        left: left,
        top: top,
        width: width,
        child: FadeTransition(
          opacity: curved,
          child: ScaleTransition(
            scale: Tween(begin: Motion.menuFrom, end: 1.0).animate(curved),
            alignment: origin,
            child: menu,
          ),
        ),
      ),
    ]);
  }
}

class _MenuRow extends StatelessWidget {
  const _MenuRow({required this.icon, required this.label, required this.onTap, this.danger = false});
  final IconData icon;
  final String label;
  final bool danger;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final color = danger ? p.danger : p.text;
    return InkWell(
      onTap: onTap,
      child: SizedBox(
        height: A11y.minTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x5),
          child: Row(children: [
            Icon(icon, size: Layout.rowIcon - 2, color: color),
            const SizedBox(width: Sp.x3),
            Expanded(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodyLarge?.copyWith(color: color))),
          ]),
        ),
      ),
    );
  }
}
