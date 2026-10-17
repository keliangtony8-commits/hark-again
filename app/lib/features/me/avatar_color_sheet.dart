// 头像颜色（设计 v2 P3）：“我的”页点大头像弹出。一排预设色（第一个 = 跟随强调色）+ 一个色相环。
// 色环只选色相，饱和度/明度固定在 AvatarColors.wheel*：随便点出来的颜色都好看、首字母都看得清。
// 选中立即生效（lookProvider 先改界面再落盘），不需要“确定”按钮；下拉/点外面关闭。
// 不做“选照片”：头像照片要上传存储和裁剪，等有了个人资料接口再一起做（不在本地塞大图）。
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/app_theme.dart';
import '../../theme/look.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

Future<void> showAvatarColorSheet(BuildContext context) => showAppSheet<void>(
      context,
      title: '头像颜色',
      builder: (_) => const AvatarColorPicker(),
    );

/// 色环上的颜色：给定色相，饱和度/明度用固定值。
Color wheelColor(double hue) => HSVColor.fromAHSV(1, hue % 360, AvatarColors.wheelSaturation, AvatarColors.wheelValue).toColor();

class AvatarColorPicker extends ConsumerWidget {
  const AvatarColorPicker({super.key, this.initial = '我'});
  final String initial;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = ref.watch(lookProvider.select((l) => l.value?.avatar));
    void pick(Color? c) => ref.read(lookProvider.notifier).setAvatar(c);
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(Layout.gutter, 0, Layout.gutter, Sp.x5),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Avatar(initial: initial, onTap: null, size: Layout.avatarLarge, color: current, tooltip: '预览'),
        const SizedBox(height: Sp.x5),
        Wrap(alignment: WrapAlignment.center, spacing: Sp.x3, runSpacing: Sp.x3, children: [
          _Swatch(color: p.avatar, label: '默认（中性）', selected: current == null, onTap: () => pick(null)),
          for (final c in AvatarColors.presets)
            _Swatch(color: c, label: '预设颜色', selected: current?.toARGB32() == c.toARGB32(), onTap: () => pick(c)),
        ]),
        const SizedBox(height: Sp.x5),
        HueWheel(color: current, onChanged: pick),
      ]),
    );
  }
}

class _Swatch extends StatelessWidget {
  const _Swatch({required this.color, required this.label, required this.selected, required this.onTap});
  final Color color;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      excludeSemantics: true,
      child: Pressable(
        onTap: onTap,
        scale: 0.9,
        child: SizedBox.square(
          dimension: A11y.minTap,
          // 选中：外圈一道 text 色细环，色块往里缩一点（渐变过去）
          child: AnimatedContainer(
            duration: context.motion(Motion.fast),
            curve: Motion.ease,
            padding: EdgeInsets.all(selected ? Sp.x1 : Sp.x1 / 2),
            decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: selected ? p.text : Colors.transparent, width: 2)),
            child: DecoratedBox(decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          ),
        ),
      ),
    );
  }
}

/// 色相环：点或拖动环上任意位置 → 那个色相的颜色。当前颜色若在环上（色相匹配）就在环上画一个指示点。
class HueWheel extends StatelessWidget {
  const HueWheel({super.key, required this.color, required this.onChanged});
  final Color? color;
  final ValueChanged<Color> onChanged;

  static const ring = Sp.x6; // 环的粗细

  void _at(Offset local) {
    const c = Offset(Layout.wheel / 2, Layout.wheel / 2);
    final d = local - c;
    if (d.distance < Layout.wheel / 2 - ring - Sp.x3) return; // 点在环中间的空洞里：不算
    final hue = (math.atan2(d.dy, d.dx) * 180 / math.pi + 360 + 90) % 360; // 0° 在正上方
    onChanged(wheelColor(hue));
  }

  @override
  Widget build(BuildContext context) {
    final hsv = color == null ? null : HSVColor.fromColor(color!);
    final onRing = hsv != null && (hsv.saturation - AvatarColors.wheelSaturation).abs() < 0.02 && (hsv.value - AvatarColors.wheelValue).abs() < 0.02;
    return Semantics(
      label: '色相环，点选任意颜色',
      child: GestureDetector(
        onTapDown: (d) => _at(d.localPosition),
        onPanUpdate: (d) => _at(d.localPosition),
        child: CustomPaint(
          size: const Size.square(Layout.wheel),
          painter: _WheelPainter(marker: onRing ? hsv.hue : null, markerBorder: context.palette.surface),
        ),
      ),
    );
  }
}

class _WheelPainter extends CustomPainter {
  _WheelPainter({required this.marker, required this.markerBorder});
  final double? marker;
  final Color markerBorder;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.width / 2 - HueWheel.ring / 2;
    final colors = [for (var h = 0; h <= 360; h += 30) wheelColor(h.toDouble())];
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = HueWheel.ring
      ..shader = SweepGradient(colors: colors, transform: const GradientRotation(-math.pi / 2)).createShader(Rect.fromCircle(center: c, radius: r));
    canvas.drawCircle(c, r, paint);
    if (marker != null) {
      final a = marker! * math.pi / 180 - math.pi / 2;
      final at = c + Offset(math.cos(a), math.sin(a)) * r;
      canvas.drawCircle(at, HueWheel.ring / 2 - 2, Paint()..color = wheelColor(marker!));
      canvas.drawCircle(at, HueWheel.ring / 2 - 2, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..color = markerBorder);
    }
  }

  @override
  bool shouldRepaint(_WheelPainter old) => old.marker != marker || old.markerBorder != markerBorder;
}
