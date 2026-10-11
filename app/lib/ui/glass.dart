// 设计 v2 的材质层：柔和渐变“壁纸” + 半透明玻璃。页面只用这里的零件，不自己写 BackdropFilter。
//   GlassMode     减少透明度开关（app.dart 注入；开了以后下面所有零件变实色、不模糊）
//   Backdrop      整个 App 的底（一级页面和“我的”透明，透出它）
//   GlassSurface  玻璃面：着色 + 发丝边 + 可选真模糊（只给浮层：顶栏、输入胶囊、弹层；列表卡片 blur: false）
//   GlassCard     列表里的大卡片（假玻璃、Radii.card、统一内边距）：主页的建议卡/面板、项目卡、“我的”用量卡
//   GlassGroup    分组列表卡：一张玻璃卡里多行，行间内缩的发丝分隔线（“我的”、主页收件箱）
//   ValueTile     卡片里再嵌一层的 标签 + 大数字 小块（面板的关键数字）
//   PillButton    卡片里的胶囊按钮：主按钮实心强调色，次按钮是一层 tile 色——等高、并排时等宽
//   WidePill      整行宽的玻璃胶囊入口（“＋ 创建一个新面板”）
//   GlassIconButton 圆形玻璃按钮（顶栏左侧的上下文按钮等）
//   Avatar        圆形头像（首字母 + 自选底色），点开“我的”
//   GlassChip     玻璃小胶囊（建议问题等，可点）
//   GlassSheet    底部弹层的玻璃框（更实的 glassSheet 着色 + 真模糊 + 顶部圆角 + 把手）：只由 ui/sheets.dart 用
//   GlassDialog   居中对话框的玻璃框（同 glassSheet 着色 + 真模糊 + 四角 Radii.card）：只由 ui/sheets.dart 用
//   GlassMode / GlassFills 在 glass_mode.dart（最底层，motion.dart 也用；本文件 re-export）
//   FrostScrim    整页的“磨砂遮罩”：输入胶囊聚焦时盖住页面，模糊和颜色一起渐入，点一下收起
// 颜色只来自 Palette，模糊强度来自 tokens 的 Glass，投影来自 Elevation。
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass_mode.dart';
import 'motion.dart';

export 'glass_mode.dart';

/// 玻璃顶边的 1px 内高光（v2.1：卡片不要外投影，像光从上面打下来）：沿圆角描边，从顶部的 glassHighlight
/// 渐隐到圆角下沿为止。画在内容之上、不挡点击；减少透明度时不画。GlassSurface 和 AppCard 都套它。
class GlassHighlight extends StatelessWidget {
  const GlassHighlight({super.key, required this.radius, required this.child});
  final double radius;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (GlassMode.solidOf(context)) return child;
    return CustomPaint(foregroundPainter: _HighlightPainter(radius, context.palette.glassHighlight), child: child);
  }
}

class _HighlightPainter extends CustomPainter {
  _HighlightPainter(this.radius, this.color);
  final double radius;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final r = radius.clamp(0, size.shortestSide / 2).toDouble();
    final fade = (r < Sp.x4 ? Sp.x4 : r) / size.height;
    final rect = Offset.zero & size;
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [color, color.withValues(alpha: 0)],
        stops: [0, fade.clamp(0, 1).toDouble()],
      ).createShader(rect);
    canvas.drawRRect(RRect.fromRectAndRadius(rect.deflate(1.5), Radius.circular(r - 1.5 < 0 ? 0 : r - 1.5)), paint);
  }

  @override
  bool shouldRepaint(_HighlightPainter old) => old.radius != radius || old.color != color;
}

/// 浮层的那圈很淡的投影（顶栏、输入胶囊、头像共用）。
List<BoxShadow> floatShadow(Palette p) =>
    [BoxShadow(color: p.shadow.withValues(alpha: p.shadow.a * Elevation.floatAlpha), blurRadius: Elevation.floatBlur, offset: const Offset(0, Elevation.floatY))];

class Backdrop extends StatelessWidget {
  const Backdrop({super.key, this.child});
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final body = child ?? const SizedBox.expand();
    if (GlassMode.solidOf(context)) return ColoredBox(color: p.bg, child: body);
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: p.backdrop),
      ),
      // 右下一团极淡的强调色光晕：给壁纸一点我们自己的温度，又不抢内容
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: RadialGradient(
            center: const Alignment(0.9, 0.85),
            radius: 0.9,
            colors: [p.accent.withValues(alpha: 0.05), p.accent.withValues(alpha: 0)],
          ),
        ),
        child: body,
      ),
    );
  }
}

class GlassSurface extends StatelessWidget {
  const GlassSurface({super.key, required this.child, this.radius = Radii.card, this.blur = false, this.padding = EdgeInsets.zero, this.shadow = true, this.borderColor});
  final Widget child;
  final double radius;
  final bool blur;
  final EdgeInsetsGeometry padding;
  final bool shadow;

  /// 换掉发丝边的颜色（录音中的输入胶囊描红边），变化时渐变过去。
  final Color? borderColor;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final solid = GlassMode.solidOf(context);
    final shape = BorderRadius.circular(radius);
    Widget body = AnimatedContainer(
      duration: context.motion(Motion.base),
      curve: Motion.ease,
      decoration: BoxDecoration(
        color: solid ? p.surface : p.glass,
        borderRadius: shape,
        border: Border.all(color: borderColor ?? (solid ? p.border : p.glassBorder), width: 1),
      ),
      padding: padding,
      child: child,
    );
    body = GlassHighlight(radius: radius, child: body);
    if (blur && !solid) {
      body = ClipRRect(
        borderRadius: shape,
        child: BackdropFilter(filter: ImageFilter.blur(sigmaX: Glass.blur, sigmaY: Glass.blur), child: body),
      );
    }
    if (!shadow) return body;
    return DecoratedBox(decoration: BoxDecoration(borderRadius: shape, boxShadow: floatShadow(p)), child: body);
  }
}

/// 列表里的大玻璃卡片（不模糊、不投影：靠发丝边和壁纸分层）。onTap 不为空时带按压回弹。
class GlassCard extends StatelessWidget {
  const GlassCard({super.key, required this.child, this.onTap, this.onLongPress, this.semanticLabel, this.padding = const EdgeInsets.all(Layout.cardPad)});
  final Widget child;
  final VoidCallback? onTap, onLongPress;
  final String? semanticLabel;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final card = GlassSurface(shadow: false, padding: padding, child: child);
    return onTap == null && onLongPress == null
        ? card
        : Pressable(onTap: onTap, onLongPress: onLongPress, semanticLabel: semanticLabel, child: card);
  }
}

/// 分组列表卡：行之间是从图标右侧开始的发丝线（和行首图标对齐），整卡一个大圆角。
class GlassGroup extends StatelessWidget {
  const GlassGroup({super.key, required this.children});
  final List<Widget> children;

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
              if (i > 0) Divider(indent: Sp.x4 + Layout.rowIcon + Sp.x4, endIndent: 0, color: line),
              children[i],
            ],
          ]),
        ),
      ),
    );
  }
}

/// 标签 + 大数字（+ 一句变化）的小块，嵌在玻璃卡片里。
class ValueTile extends StatelessWidget {
  const ValueTile({super.key, required this.label, required this.value, this.note});
  final String label, value;
  final String? note;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: '$label，$value${note == null ? '' : '，$note'}',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: Sp.x1),
          CountUp(value, style: context.text.displaySmall),
          if (note != null && note!.isNotEmpty) Text(note!, style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
    );
  }
}

/// 卡片里的胶囊按钮。primary = 实心墨色（v2.1：不再用强调色）；danger = 实心危险色（删除确认）；否则是一层 tile 色。高度 = A11y.minTap。
class PillButton extends StatelessWidget {
  const PillButton({super.key, required this.label, required this.onTap, this.icon, this.primary = false, this.danger = false, this.dense = false});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final bool primary, danger;

  /// 列表行尾的小号（“连接”）：看起来 Sp.x6 高、字小一档，可点区域仍是 A11y.minTap。
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
        final fg = danger ? p.onAccent : (primary ? p.onInk : p.text);
    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: Pressable(
        onTap: onTap,
        scale: 0.96,
        child: SizedBox(
          height: A11y.minTap,
          child: Center(
            widthFactor: 1,
            child: Container(
              height: dense ? Sp.x6 : A11y.minTap,
              padding: EdgeInsets.symmetric(horizontal: dense ? Sp.x3 : Sp.x4),
              alignment: Alignment.center,
              decoration: BoxDecoration(color: danger ? p.danger : (primary ? p.ink : context.tileFill), borderRadius: BorderRadius.circular(Radii.full)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                if (icon != null) ...[Icon(icon, size: dense ? Fs.md : Fs.lg - 2, color: fg), SizedBox(width: dense ? Sp.x1 : Sp.x2)],
                Flexible(
                    child: Text(label,
                        maxLines: 1, overflow: TextOverflow.ellipsis, style: (dense ? context.text.labelMedium : context.text.labelLarge)?.copyWith(color: fg))),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// 整行宽的玻璃胶囊入口：“＋ 创建一个新面板”。
class WidePill extends StatelessWidget {
  const WidePill({super.key, required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: label,
        excludeSemantics: true,
        child: Pressable(
          onTap: onTap,
          child: GlassSurface(
            radius: Radii.full,
            shadow: false,
            child: SizedBox(
              height: A11y.minTap + Sp.x3,
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Icon(icon, color: context.palette.text),
                const SizedBox(width: Sp.x2),
                Text(label, style: context.text.titleMedium),
              ]),
            ),
          ),
        ),
      );
}

/// 圆形玻璃图标按钮，尺寸 = 顶栏高度（≥ A11y.minTap）。tooltip 同时是读屏名字。
class GlassIconButton extends StatelessWidget {
  const GlassIconButton({super.key, required this.icon, required this.tooltip, required this.onTap, this.size = Layout.topBar});
  final IconData icon;
  final String tooltip;
  final VoidCallback? onTap;
  final double size;

  @override
  Widget build(BuildContext context) => Tooltip(
        message: tooltip,
        excludeFromSemantics: true,
        child: Pressable(
          onTap: onTap,
          semanticLabel: tooltip,
          scale: 0.92,
          child: SizedBox.square(
            dimension: size,
            child: GlassSurface(blur: true, radius: Radii.full, child: Center(child: Icon(icon, color: context.palette.text))),
          ),
        ),
      );
}

/// 圆形头像：底色（null = 中性 Palette.avatar，“我的”里可改）+ 衬线首字，字色按底色亮度自动深/浅。
/// 只有一圈发丝边和很淡的投影：它是顶栏的一员，不该像贴纸一样浮起来。
class Avatar extends StatelessWidget {
  const Avatar({super.key, required this.initial, required this.onTap, this.size = Layout.topBar, this.color, this.tooltip = '我的'});
  final String initial;
  final VoidCallback? onTap;
  final double size;
  final Color? color;
  final String tooltip;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final bg = color ?? p.avatar;
    final ink = color == null ? p.text : AvatarColors.inkOn(bg);
    return Tooltip(
      message: tooltip,
      excludeFromSemantics: true,
      child: Pressable(
        onTap: onTap,
        semanticLabel: tooltip,
        scale: 0.92,
        child: AnimatedContainer(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          width: size,
          height: size,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: bg, shape: BoxShape.circle, border: Border.all(color: p.glassBorder)),
          child: ExcludeSemantics(
            child: AnimatedDefaultTextStyle(
              duration: context.motion(Motion.base),
              style: context.text.displaySmall!.copyWith(color: ink, fontSize: size * 0.42, height: 1, letterSpacing: 0),
              child: Text(initial),
            ),
          ),
        ),
      ),
    );
  }
}

/// 玻璃小胶囊：建议问题、快捷入口。列表里用，所以是假玻璃（不模糊）。
class GlassChip extends StatelessWidget {
  const GlassChip({super.key, required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: A11y.minTap),
          child: GlassSurface(
            radius: Radii.full,
            shadow: false,
            padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
            child: Text(label, style: context.text.bodyMedium?.copyWith(color: context.palette.text)),
          ),
        ),
      );
}

/// 磨砂遮罩：visible 时整片模糊 + 着色渐入，挡住下面的点击；点它 = onTap（收起输入框）。
/// 不可见时不画 BackdropFilter（零开销），也不挡点击、不进读屏。减少透明度时只用不透明的底色盖住。
class FrostScrim extends StatelessWidget {
  const FrostScrim({super.key, required this.visible, this.onTap});
  final bool visible;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final solid = GlassMode.solidOf(context);
    return IgnorePointer(
      ignoring: !visible,
      child: TweenAnimationBuilder<double>(
        tween: Tween(end: visible ? 1 : 0),
        duration: context.motion(Motion.base),
        curve: Motion.ease,
        builder: (context, t, _) {
          if (t == 0) return const SizedBox.expand();
          final tint = solid ? p.bg.withValues(alpha: Op.dimmed * t) : p.scrim.withValues(alpha: p.scrim.a * t);
          final cover = ColoredBox(color: tint, child: const SizedBox.expand());
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: onTap,
            child: solid
                ? cover
                : ClipRect(
                    child: BackdropFilter(filter: ImageFilter.blur(sigmaX: Glass.scrimBlur * t, sigmaY: Glass.scrimBlur * t), child: cover),
                  ),
          );
        },
      ),
    );
  }
}

/// 底部弹层的玻璃框：上圆角 Radii.card、真模糊、glassSheet 着色、顶部发丝边、居中把手，底部让出手势条。
/// 页面不直接用它——走 ui/sheets.dart 的 showAppSheet / showAppScrollSheet。
class GlassSheet extends StatelessWidget {
  const GlassSheet({super.key, required this.child, this.fill = false});
  final Widget child;

  /// true = 撑满父级给的高度（可拖动弹层）；false = 随内容高度。
  final bool fill;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final solid = GlassMode.solidOf(context);
    const shape = BorderRadius.vertical(top: Radius.circular(Radii.card));
    final body = DecoratedBox(
      decoration: BoxDecoration(
        color: solid ? p.surface : p.glassSheet,
        borderRadius: shape,
        border: Border(top: BorderSide(color: solid ? p.border : p.glassBorder)),
      ),
      // 透明 Material：里面 ListTile 的水波纹画在玻璃之上，而不是被着色盖住
      child: Material(
        type: MaterialType.transparency,
        child: Column(mainAxisSize: fill ? MainAxisSize.max : MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: Sp.x3),
          child: Center(
            child: Container(
              key: const ValueKey('sheet-grabber'),
              width: Glass.grabber.width,
              height: Glass.grabber.height,
              decoration: BoxDecoration(color: p.text3.withValues(alpha: Op.dimmed), borderRadius: BorderRadius.circular(Radii.full)),
            ),
          ),
        ),
        // 底部安全区由这里统一让出（键盘弹起时 paddingOf 自动归零），内容里的 SafeArea 不再重复加
        if (fill) Expanded(child: _noBottom(context, child)) else Flexible(child: _noBottom(context, child)),
        SizedBox(height: MediaQuery.paddingOf(context).bottom),
        ]),
      ),
    );
    return ClipRRect(
      borderRadius: shape,
      child: solid ? body : BackdropFilter(filter: ImageFilter.blur(sigmaX: Glass.blur, sigmaY: Glass.blur), child: body),
    );
  }

  static Widget _noBottom(BuildContext context, Widget child) => MediaQuery.removePadding(context: context, removeBottom: true, child: child);
}

/// 居中对话框的玻璃框：四角 Radii.card、真模糊、glassSheet 着色、发丝边、贴身的淡投影；最宽 Layout.dialogMax。
/// 页面不直接用它——走 ui/sheets.dart 的 showAppDialog / confirmDanger。
class GlassDialog extends StatelessWidget {
  const GlassDialog({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final solid = GlassMode.solidOf(context);
    final shape = BorderRadius.circular(Radii.card);
    final body = DecoratedBox(
      decoration: BoxDecoration(color: solid ? p.surface : p.glassSheet, borderRadius: shape, border: Border.all(color: context.hairline)),
      child: Material(
        type: MaterialType.transparency,
        child: Padding(padding: const EdgeInsets.all(Sp.x5), child: child),
      ),
    );
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: Layout.dialogMax),
      child: DecoratedBox(
        decoration: BoxDecoration(borderRadius: shape, boxShadow: floatShadow(p)),
        child: ClipRRect(
          borderRadius: shape,
          child: solid ? body : BackdropFilter(filter: ImageFilter.blur(sigmaX: Glass.blur, sigmaY: Glass.blur), child: body),
        ),
      ),
    );
  }
}
