// 待发送附件：横向小卡片，上传中显示进度环，可单独移除。新增/移除带尺寸动画。
// 两种来源：本机文件（先上传，local 有值）；项目文件引用（Attachment.ref，现成的 FileBlock，角上一个文件夹记号）。
import 'dart:io';

import 'package:flutter/material.dart';

import '../../models/block.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import '../../ui/glass.dart';

class Attachment {
  Attachment({required this.name, required File this.local});
  Attachment.ref(FileBlock this.file) : name = file.name, local = null;
  final String name;
  final File? local;
  FileBlock? file; // 上传完成后才有；引用一开始就有
  bool get uploading => file == null;
  bool get fromProject => file?.source == 'project';
  bool get isImage => RegExp(r'\.(png|jpe?g|gif|webp|heic)$', caseSensitive: false).hasMatch(name);
}

class AttachmentTray extends StatelessWidget {
  const AttachmentTray({super.key, required this.items, required this.onRemove});
  final List<Attachment> items;
  final void Function(Attachment) onRemove;

  @override
  Widget build(BuildContext context) => AnimatedSize(
        duration: Motion.base,
        curve: Motion.ease,
        alignment: Alignment.topCenter,
        child: items.isEmpty
            ? const SizedBox(width: double.infinity)
            : SizedBox(
                height: _Thumb.extent,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x3),
                  itemCount: items.length,
                  separatorBuilder: (_, _) => const SizedBox.shrink(), // 叉号留的边就是间距
                  itemBuilder: (_, i) => FadeSlideIn(key: ObjectKey(items[i]), child: _Thumb(items[i], onRemove: () => onRemove(items[i]))),
                ),
              ),
      );
}

/// 缩略图 64，右上角小叉的可点区域是 A11y.minTap、以缩略图角为圆心。
/// 整块留出半个按钮的边（_bleed），按钮完全落在自身范围内——溢出 Stack 的部分点不到。
class _Thumb extends StatelessWidget {
  const _Thumb(this.a, {required this.onRemove});
  final Attachment a;
  final VoidCallback onRemove;

  static const _size = 64.0;
  static const _bleed = A11y.minTap / 2;
  static const extent = _size + _bleed;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ext = a.name.contains('.') ? a.name.split('.').last.toUpperCase() : 'FILE';
    return SizedBox.square(
      dimension: extent,
      child: Stack(children: [
        Positioned(
          left: 0,
          bottom: 0,
          width: _size,
          height: _size,
          child: Stack(children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(Radii.sm),
              child: Container(
                width: _size,
                height: _size,
                color: context.tileFill,
                alignment: Alignment.center,
                child: a.isImage && a.local != null
                    ? Image.file(a.local!, width: _size, height: _size, fit: BoxFit.cover, semanticLabel: a.name)
                    : Text(ext.length > 4 ? ext.substring(0, 4) : ext,
                        semanticsLabel: a.name, style: TextStyle(color: p.text2, fontSize: 11, fontWeight: Weights.strong)),
              ),
            ),
            if (a.fromProject)
              Positioned(
                left: Sp.x1,
                bottom: Sp.x1,
                child: Icon(Icons.folder_rounded, size: 12, color: p.text3, semanticLabel: '项目文件'),
              ),
            if (a.uploading)
              Positioned.fill(
                child: Container(
                  decoration: BoxDecoration(color: p.bg.withValues(alpha: 0.6), borderRadius: BorderRadius.circular(Radii.sm)),
                  alignment: Alignment.center,
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: p.accent, semanticsLabel: '正在上传'),
                  ),
                ),
              ),
          ]),
        ),
        Positioned(
          top: 0,
          right: 0,
          child: Pressable(
            onTap: onRemove,
            semanticLabel: '移除 ${a.name}',
            child: SizedBox.square(
              dimension: A11y.minTap,
              child: Center(
                child: Container(
                  width: 20,
                  height: 20,
                  decoration: BoxDecoration(color: p.text, shape: BoxShape.circle, border: Border.all(color: p.surface, width: 1.5)),
                  child: Icon(Icons.close_rounded, size: 12, color: p.bg),
                ),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}
