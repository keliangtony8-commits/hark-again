// 待发送附件托盘（v1.14 排版）：图片 = 方缩略图；其他文件 = 名片（类型角标 + 名字 + 一行来源/大小），一眼分得清两个 PDF。
// 两种来源：本机文件（先上传，local 有值，上传中角标里转圈）；项目文件引用（Attachment.ref，现成的 FileBlock，角标带文件夹记号）。
// 两种样子同高 Layout.attachThumb，右上角小叉可点区 A11y.minTap；新增/移除带尺寸动画。网页 Composer .attach 同规则（lib/files attachSub）。
import 'dart:io';

import 'package:flutter/material.dart';

import '../../models/block.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
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

  /// 本机图片画缩略图；项目里的图片没有本地文件，按名片画。
  bool get asThumb => isImage && local != null;

  /// 类型角标：扩展名大写，最多 4 个字。
  String get ext {
    final e = name.contains('.') ? name.split('.').last.toUpperCase() : 'FILE';
    return e.length > 4 ? e.substring(0, 4) : e;
  }

  /// 名片第二行——唯一规则（网页 attachSub 同义）。
  String get sub => uploading ? '上传中…' : [if (fromProject) '项目文件', formatSize(file!.size)].join(' · ');
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
                height: _Removable.extent,
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x3),
                  itemCount: items.length,
                  // 叉号留的边就是间距
                  itemBuilder: (_, i) => FadeSlideIn(
                    key: ObjectKey(items[i]),
                    child: _Removable(
                      a: items[i],
                      onRemove: () => onRemove(items[i]),
                      child: items[i].asThumb ? _Thumb(items[i]) : _Chip(items[i]),
                    ),
                  ),
                ),
              ),
      );
}

/// 外框：内容贴左下，右上角留半个按钮的边（_bleed），小叉以内容右上角为圆心、完全落在自身范围内——溢出 Stack 的部分点不到。
class _Removable extends StatelessWidget {
  const _Removable({required this.a, required this.onRemove, required this.child});
  final Attachment a;
  final VoidCallback onRemove;
  final Widget child;

  static const _bleed = A11y.minTap / 2;
  static const extent = Layout.attachThumb + _bleed;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final width = (a.asThumb ? Layout.attachThumb : Layout.attachChip) + _bleed;
    return SizedBox(
      width: width,
      height: extent,
      child: Stack(children: [
        Positioned(left: 0, bottom: 0, right: _bleed, top: _bleed, child: child),
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

/// 本机图片：方缩略图，上传中盖一层半透明 + 转圈。
class _Thumb extends StatelessWidget {
  const _Thumb(this.a);
  final Attachment a;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ClipRRect(
      borderRadius: BorderRadius.circular(Radii.sm),
      child: Stack(fit: StackFit.expand, children: [
        Image.file(a.local!, fit: BoxFit.cover, semanticLabel: a.name),
        if (a.uploading)
          ColoredBox(color: p.bg.withValues(alpha: 0.6), child: const Center(child: _Spinner())),
      ]),
    );
  }
}

/// 文件名片：角标（扩展名 / 上传中转圈 / 项目文件记号）+ 名字 + 来源·大小。
class _Chip extends StatelessWidget {
  const _Chip(this.a);
  final Attachment a;

  static const _badge = 36.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      label: '${a.name}，${a.sub}',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x3),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
        child: Row(children: [
          SizedBox.square(
            dimension: _badge,
            child: Stack(clipBehavior: Clip.none, children: [
              Container(
                decoration: BoxDecoration(
                  border: Border.all(color: context.hairline),
                  borderRadius: BorderRadius.circular(Radii.sm),
                ),
                alignment: Alignment.center,
                child: SwapSwitcher(
                  child: a.uploading
                      ? const _Spinner(key: ValueKey('up'))
                      : Text(a.ext,
                          key: const ValueKey('ext'),
                          style: context.text.labelSmall?.copyWith(color: p.text2, fontSize: Fs.xs - 2, fontWeight: Weights.strong)),
                ),
              ),
              if (a.fromProject)
                Positioned(
                  right: -Sp.x1,
                  bottom: -Sp.x1,
                  child: Container(
                    padding: const EdgeInsets.all(2),
                    decoration: BoxDecoration(color: p.surface, shape: BoxShape.circle),
                    child: Icon(Icons.folder_rounded, size: 11, color: p.text2),
                  ),
                ),
            ]),
          ),
          const SizedBox(width: Sp.x2),
          Expanded(
            child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(a.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodySmall?.copyWith(color: p.text)),
              SwapSwitcher(
                child: Text(a.sub,
                    key: ValueKey(a.sub), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.labelSmall),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _Spinner extends StatelessWidget {
  const _Spinner({super.key});

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: 18,
        child: CircularProgressIndicator(strokeWidth: 2, color: context.palette.accent, semanticsLabel: '正在上传'),
      );
}
