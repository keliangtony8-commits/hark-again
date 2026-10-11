// 输入框外形：圆角填充块 + 聚焦时一圈细线。
//
// 为什么不用 OutlineInputBorder：它是“描边式”，浮起的标签会骑在边线上——边线透明时
// 标签就半截掉到填充块外面（v0.90 截图里“收件人”）。这里 isOutline = false，Material 按
// “填充式”排版：标签浮在填充块里面、内容下移让位。
import 'package:flutter/material.dart';

class FieldBorder extends InputBorder {
  const FieldBorder({required this.radius, super.borderSide = BorderSide.none});

  final double radius;

  @override
  bool get isOutline => false;

  @override
  EdgeInsetsGeometry get dimensions => EdgeInsets.all(borderSide.width);

  @override
  FieldBorder copyWith({BorderSide? borderSide}) => FieldBorder(radius: radius, borderSide: borderSide ?? this.borderSide);

  @override
  ShapeBorder scale(double t) => FieldBorder(radius: radius * t, borderSide: borderSide.scale(t));

  RRect _rrect(Rect rect) => RRect.fromRectAndRadius(rect, Radius.circular(radius));

  @override
  Path getInnerPath(Rect rect, {TextDirection? textDirection}) => Path()..addRRect(_rrect(rect).deflate(borderSide.width));

  @override
  Path getOuterPath(Rect rect, {TextDirection? textDirection}) => Path()..addRRect(_rrect(rect));

  @override
  void paintInterior(Canvas canvas, Rect rect, Paint paint, {TextDirection? textDirection}) => canvas.drawRRect(_rrect(rect), paint);

  @override
  bool get preferPaintInterior => true;

  @override
  void paint(Canvas canvas, Rect rect, {double? gapStart, double gapExtent = 0, double gapPercentage = 0, TextDirection? textDirection}) {
    if (borderSide.style == BorderStyle.none || borderSide.width == 0) return;
    canvas.drawRRect(_rrect(rect).deflate(borderSide.width / 2), borderSide.toPaint());
  }

  @override
  bool operator ==(Object other) => other is FieldBorder && other.radius == radius && other.borderSide == borderSide;

  @override
  int get hashCode => Object.hash(radius, borderSide);
}
