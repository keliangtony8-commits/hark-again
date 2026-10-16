// 设计 v2 的材质层：柔和渐变“壁纸” + 半透明玻璃。页面只用这里的零件，不自己写 BackdropFilter。
//   GlassMode     减少透明度开关（app.dart 注入；开了以后下面所有零件变实色、不模糊）
//   Backdrop      整个 App 的底（一级页面和“我的”透明，透出它）
//   GlassSurface  玻璃面：着色 + 发丝边 + 可选真模糊（只给浮层：顶栏、输入胶囊、弹层；列表卡片 blur: false）
//   GlassCard     列表里的大卡片（假玻璃、Radii.card、统一内边距）：主页的建议卡/面板、项目卡、“我的”用量卡
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
//   BackdropFade  壁纸的上沿渐隐条（ShellPage 顶部：盖在内容上，代替整页 ShaderMask 离屏层）
//
// 毛玻璃分组（v3.3 卡顿根因，Flutter BackdropGroup / BackdropFilter.grouped）：GlassSurface(blur) 和子页标题栏用 grouped，
//   找最近的 BackdropGroup 共享一次“取背景 + 模糊”。组只开在三处：AppShell（顶栏 + 一级页面左侧按钮 / header）、
//   ShellPage 内容（输入胶囊等）、SubPage。引擎语义：组里第一个画到的滤镜取背景，后面的成员只从那张结果里取自己那块——
//   所以成员不能重叠、第一个成员之后不能再在其他成员底下画东西、第一个成员不能在淡入淡出里（绘制顺序见 shell_page.dart / composer.dart）。
//   没有组的地方 grouped = 普通 BackdropFilter。弹层 / 对话框 / 磨砂遮罩永远独立（它们要模糊的正是组里的成员）。
// 颜色只来自 Palette，模糊强度来自 tokens 的 Glass，投影来自 Elevation。
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass_mode.dart';
import 'sky.dart';
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
    // v3.3 流光壁纸（ui/sky.dart）：自身是重绘边界，只有这一层随 SkyClock 重画
    return Stack(fit: StackFit.passthrough, children: [const Positioned.fill(child: SkyLayer()), body]);
  }
}

/// 一个毛玻璃组（规则见文件头）：BackdropGroup + 自己持有的 BackdropKey。
/// 不直接写 BackdropGroup(child: …)：它不给 key 时每次 build 都新建一个，组里所有滤镜跟着重建。
class BlurGroup extends StatefulWidget {
  const BlurGroup({super.key, required this.child});
  final Widget child;

  @override
  State<BlurGroup> createState() => _BlurGroupState();
}

class _BlurGroupState extends State<BlurGroup> {
  final _key = BackdropKey();

  @override
  Widget build(BuildContext context) => BackdropGroup(backdropKey: _key, child: widget.child);
}

/// 壁纸的上沿渐隐条：[clear]（屏幕坐标）以上是不透明的壁纸，到 [solid] 渐成透明（Sky.fadeAlpha 缓入缓出）。
/// 盖在内容上 = 内容在这一截以 1−α 透出壁纸，和原来整页 ShaderMask(dstIn) 看起来一样，但只画这一条、没有离屏层。
/// 和 Backdrop 同一处判断：玻璃模式 = 同一张流光壁纸（SkyLayer 按屏幕坐标逐像素对齐、共用 SkyClock）；减少透明度 = 实色 bg。
/// 不挡点击、不进读屏（和原来被遮罩的内容一样仍可点）。
class BackdropFade extends StatelessWidget {
  const BackdropFade({super.key, required this.clear, required this.solid});
  final double clear, solid;

  @override
  Widget build(BuildContext context) {
    final Widget strip = GlassMode.solidOf(context)
        ? RepaintBoundary(child: CustomPaint(painter: _SolidFadePainter(context.palette.bg, clear, solid), child: const SizedBox.expand()))
        : SkyLayer(fade: (clear, solid));
    return IgnorePointer(child: ExcludeSemantics(child: strip));
  }
}

class _SolidFadePainter extends CustomPainter {
  _SolidFadePainter(this.color, this.clear, this.solid);
  final Color color;
  final double clear, solid;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    // 条从屏幕顶开始（ShellPage 把它放在 top: 0），所以本地 y = 屏幕 y；色标按 Sky.fadeAlpha 取，和着色器同一条曲线
    const n = 6;
    final stops = <double>[], colors = <Color>[];
    for (var k = 0; k <= n; k++) {
      final y = clear + (solid - clear) * k / n;
      stops.add((y / size.height).clamp(0.0, 1.0));
      colors.add(color.withValues(alpha: Sky.fadeAlpha(y, clear, solid)));
    }
    final rect = Offset.zero & size;
    canvas.drawRect(rect, Paint()..shader = LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [color, ...colors], stops: [0, ...stops]).createShader(rect));
  }

  @override
  bool shouldRepaint(_SolidFadePainter old) => old.color != color || old.clear != clear || old.solid != solid;
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
    // v2.80 F.2：不模糊的面 = 列表卡片，一律实色 surface、无描边无高光；只有浮层（blur）是玻璃 + 发丝边。
    final card = !blur;
    Widget body = AnimatedContainer(
      duration: context.motion(Motion.base),
      curve: Motion.ease,
      decoration: BoxDecoration(
        color: solid || card ? p.surface : p.glass,
        borderRadius: shape,
        border: Border.all(color: borderColor ?? (card ? p.surface.withValues(alpha: 0) : (solid ? p.border : p.chromeEdge)), width: 1),
      ),
      padding: padding,
      child: child,
    );
    if (!card) body = GlassHighlight(radius: radius, child: body);
    if (blur && !solid) {
      body = ClipRRect(
        borderRadius: shape,
        child: BackdropFilter.grouped(filter: ImageFilter.blur(sigmaX: Glass.blur, sigmaY: Glass.blur), child: body),
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
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
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
  const GlassIconButton({super.key, required IconData this.icon, required this.tooltip, required this.onTap, this.size = Layout.topBar}) : glyph = null;

  /// 图标不是字体图标时（v2.93 项目左上的 ≡/+ MenuPlusIcon）。
  const GlassIconButton.glyph({super.key, required Widget this.glyph, required this.tooltip, required this.onTap, this.size = Layout.topBar}) : icon = null;
  final IconData? icon;
  final Widget? glyph;
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
            child: GlassSurface(blur: true, radius: Radii.full, child: Center(child: glyph ?? Icon(icon, color: context.palette.text))),
          ),
        ),
      );
}

/// 圆形头像：底色（null = 中性 Palette.avatar，“我的”里可改）+ 无衬线首字（600），字色按底色亮度自动深/浅。
/// 只有一圈发丝边和很淡的投影：它是顶栏的一员，不该像贴纸一样浮起来。
/// v2.92 §P：[image] = 用户上传的头像（完整地址，带 ?token=）；有图盖在圆里，加载失败退回首字母。
class Avatar extends StatelessWidget {
  const Avatar({super.key, required this.initial, required this.onTap, this.size = Layout.topBar, this.color, this.image, this.tooltip = '我的'});
  final String initial;
  final VoidCallback? onTap;
  final double size;
  final Color? color;
  final String? image;
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
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(color: bg, shape: BoxShape.circle, border: Border.all(color: p.chromeEdge)),
          child: ExcludeSemantics(
            child: Stack(fit: StackFit.expand, children: [
              Center(
                child: AnimatedDefaultTextStyle(
                  duration: context.motion(Motion.base),
                  style: context.text.displaySmall!.copyWith(color: ink, fontSize: size * 0.4, fontWeight: Weights.title, height: 1, letterSpacing: 0),
                  child: Text(initial),
                ),
              ),
              if (image != null)
                Image.network(
                  image!,
                  key: ValueKey(image),
                  fit: BoxFit.cover,
                  // 淡入：图到了才盖住首字母（只动 opacity）；失败就留着首字母
                  frameBuilder: (_, child, frame, sync) => AnimatedOpacity(
                    opacity: sync || frame != null ? 1 : 0,
                    duration: context.motion(Motion.base),
                    curve: Motion.ease,
                    child: child,
                  ),
                  errorBuilder: (_, _, _) => const SizedBox.shrink(),
                ),
            ]),
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
  Widget build(BuildContext context) => IgnorePointer(
        ignoring: !visible,
        child: TweenAnimationBuilder<double>(
          tween: Tween(end: visible ? 1 : 0),
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          builder: (context, t, _) => FrostLayer(t: t, onTap: onTap, blur: Glass.scrimBlur),
        ),
      );
}

/// 磨砂层本身（t = 0…1 的进度，外面给动画）：模糊 + 着色按 t 渐入；t = 0 什么都不画。
/// FrostScrim（输入框聚焦）和长按聚焦菜单（ui/focus_menu.dart，模糊更重）共用这一份。
class FrostLayer extends StatelessWidget {
  const FrostLayer({super.key, required this.t, this.onTap, this.blur = Glass.scrimBlur, this.semanticLabel});
  final double t;
  final VoidCallback? onTap;
  final double blur;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    if (t == 0) return const SizedBox.expand();
    final p = context.palette;
    final solid = GlassMode.solidOf(context);
    // v2.88 动效性能（hark-elegant-ui 7a）：模糊半径固定，整层只淡入（Opacity 合成层），不再每帧重算 sigma。
    final cover = ColoredBox(color: solid ? p.bg.withValues(alpha: Op.dimmed) : p.scrim, child: const SizedBox.expand());
    final layer = solid ? cover : ClipRect(child: BackdropFilter(filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur), child: cover));
    return Semantics(
      label: semanticLabel,
      button: semanticLabel != null,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: RepaintBoundary(child: t >= 1 ? layer : Opacity(opacity: t, child: layer)),
      ),
    );
  }
}

/// 底部弹层的玻璃框：上圆角 Radii.card、真模糊、glassSheet 着色、顶部发丝边、居中把手，底部让出手势条。
/// 页面不直接用它——走 ui/sheets.dart 的 showAppSheet / showAppScrollSheet。
class GlassSheet extends StatelessWidget {
  const GlassSheet({super.key, required this.child});
  final Widget child; // 随内容高度；放不下时由内容自己滚（showAppScrollSheet + SheetList）

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
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
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
        Flexible(child: _noBottom(context, child)),
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
