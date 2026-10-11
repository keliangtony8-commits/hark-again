// 可交互的块：文件、审批、网页（Page）。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/links.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/motion.dart';
import '../ui/format.dart';
import '../ui/kit.dart';
import 'block_actions.dart';
import '../ui/glass.dart';


class FileBlockView extends ConsumerWidget {
  const FileBlockView(this.block, {super.key});
  final FileBlock block;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final url = ref.read(apiProvider).fileUrl(block.path);
    if (block.isImage) {
      return Pressable(
        onTap: () => openUrl(url),
        semanticLabel: '图片 ${block.name}，打开原图',
        child: ClipRRect(
          borderRadius: BorderRadius.circular(Radii.md),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 320),
            child: Image.network(url, fit: BoxFit.cover, errorBuilder: (_, _, _) => _chip(context, url)),
          ),
        ),
      );
    }
    return _chip(context, url);
  }

  Widget _chip(BuildContext context, String url) {
    final ext = block.name.contains('.') ? block.name.split('.').last.toUpperCase() : 'FILE';
    return AppCard(
      onTap: () => openUrl(url),
      padding: const EdgeInsets.all(Sp.x3),
      child: Row(children: [
        Container(
          width: 40,
          height: 40,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
          child: Text(ext.length > 4 ? ext.substring(0, 4) : ext, style: context.text.labelSmall?.copyWith(color: context.palette.text2, fontSize: 10)),
        ),
        const SizedBox(width: Sp.x3),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(block.name, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
            Text(formatSize(block.size), style: context.text.bodySmall),
          ]),
        ),
        Icon(Icons.download_rounded, color: context.palette.text3),
      ]),
    );
  }
}

class ApprovalBlockView extends StatelessWidget {
  const ApprovalBlockView(this.block, {super.key});
  final ApprovalBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final onReply = BlockActions.of(context)?.onApproval;
    final (label, color) = switch (block.state) {
      'approved' => ('已批准', p.text2),
      'rejected' => ('已拒绝', p.text3),
      'expired' => ('已过期', p.text3),
      _ => ('等你确认', p.warning),
    };
    return AnimatedContainer(
      duration: Motion.base,
      curve: Motion.ease,
      padding: const EdgeInsets.all(Sp.x4),
      decoration: BoxDecoration(
        color: context.cardFill,
        borderRadius: BorderRadius.circular(Radii.md),
        border: Border.all(color: block.pending ? p.warning.withValues(alpha: 0.5) : context.hairline, width: block.pending ? 1.5 : 1),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.shield_outlined, size: 18, color: color),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text(block.title, style: context.text.titleMedium)),
          Text(label, style: context.text.labelSmall?.copyWith(color: color, fontWeight: Weights.title)),
        ]),
        if (block.detail.isNotEmpty) ...[
          const SizedBox(height: Sp.x2),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(Sp.x3),
            decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
            child: Text(block.detail, style: const TextStyle(fontFamily: 'monospace', fontSize: Fs.xs)),
          ),
        ],
        AnimatedSize(
          duration: Motion.base,
          curve: Motion.ease,
          child: block.pending && onReply != null
              ? Padding(
                  padding: const EdgeInsets.only(top: Sp.x3),
                  child: Row(children: [
                    Expanded(child: OutlinedButton(onPressed: () => onReply(block.id, false), child: const Text('拒绝'))),
                    const SizedBox(width: Sp.x2),
                    Expanded(child: FilledButton(onPressed: () => onReply(block.id, true), child: const Text('批准'))),
                  ]),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}

class PageBlockView extends StatelessWidget {
  const PageBlockView(this.block, {super.key});
  final PageBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return AppCard(
      onTap: () => openUrl(block.url),
      padding: const EdgeInsets.all(Sp.x3),
      child: Row(children: [
        Container(
          width: 52,
          height: 52,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(Radii.sm),
            color: context.tileFill,
          ),
          child: Icon(Icons.web_rounded, color: p.text2, weight: 300),
        ),
        const SizedBox(width: Sp.x3),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(block.title, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
            Text(block.url.replaceFirst(RegExp(r'^https?://'), ''), style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
        IconButton(
          icon: Icon(Icons.link_rounded, color: p.text3),
          tooltip: '复制链接',
          onPressed: () {
            Clipboard.setData(ClipboardData(text: block.url));
            showToast(context, '链接已复制');
          },
        ),
      ]),
    );
  }
}
