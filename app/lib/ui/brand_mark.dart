// 品牌图标（用户 2026-10-14 指定）：App 内唯一入口。图源 assets/brand/mark.png 由 brand/make_icons.py 生成，
// 和桌面图标、网页 favicon 同一张图；要换图标只换 brand/source.png 再跑脚本。
import 'package:flutter/material.dart';
import '../brand.dart';

class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 44});
  final double size;

  @override
  Widget build(BuildContext context) => Image.asset(
        'assets/brand/mark.png',
        width: size,
        height: size,
        filterQuality: FilterQuality.medium,
        semanticLabel: appName,
      );
}
