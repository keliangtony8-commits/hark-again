// 可交互的块：文件、审批、网页（Page）。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/links.dart';
import '../core/workspace.dart';
import '../models/block.dart';
import '../models/host.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/motion.dart';
import '../ui/format.dart';
import '../ui/kit.dart';
import 'block_actions.dart';
import 'block_frame.dart';
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
            Text(fileSubtitle(block.name, block.mime, block.size,
                    workspaceTitle: block.source == 'project' ? workspaceFilesTitle(block.projectId ?? '') : null),
                style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
        Icon(Icons.download_rounded, color: context.palette.text3),
      ]),
    );
  }
}

// 审批卡。普通审批（沙盒里的高风险命令等）：盾牌图标 + 标题 + 命令 + “拒绝 / 批准”。
// 主机命令卡（v1.49，target == host）：服务器图标、标题下一行“在 <机器名> 上，以 root”、为什么要你看一眼（note；危险时警示色），
// 底部除了“拒绝 / 批准（= 仅这一次）”，还有批准范围行（这段对话里都允许 / 以后都允许 X 开头的命令），依次浮入；
// 批准后按钮收起，换成“已选：…”一句（RiseSwitcher）。状态字 SwapSwitcher 换。
class ApprovalBlockView extends StatelessWidget {
  const ApprovalBlockView(this.block, {super.key});
  final ApprovalBlock block;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final actions = BlockActions.of(context);
    final onReply = actions?.onApproval;
    final onOption = actions?.onApprovalOption;
    final (label, color) = switch (block.state) {
      'approved' => ('已批准', p.text2),
      'rejected' => ('已拒绝', p.text3),
      'expired' => ('已过期', p.text3),
      _ => ('等你确认', p.warning),
    };
    final extras = onOption == null ? const <ApprovalOption>[] : approvalExtraOptions(block);
    final granted = approvalGrantedLine(block);
    final note = block.note ?? '';
    return Semantics(
      container: true,
      label: approvalSemantics(block),
      child: BlockFrame(
        tone: block.pending ? FrameTone.waiting : FrameTone.calm,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(block.onHost ? Icons.dns_outlined : Icons.shield_outlined, size: 18, color: color),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(block.title, style: context.text.titleMedium),
                if (block.onHost)
                  Text(block.host == null ? '在服务器本机上，以 root' : '在 ${block.host} 上，以 root',
                      style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              ]),
            ),
            SwapSwitcher(
              child: Text(label,
                  key: ValueKey(label), style: context.text.labelSmall?.copyWith(color: color, fontWeight: Weights.title)),
            ),
          ]),
          if (note.isNotEmpty) ...[
            const SizedBox(height: Sp.x2),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(block.warn ? Icons.warning_amber_rounded : Icons.info_outline_rounded,
                  size: 16, color: block.warn ? p.warning : p.text3),
              const SizedBox(width: Sp.x2),
              Expanded(
                child: Text(note, style: context.text.bodySmall?.copyWith(color: block.warn ? p.warning : p.text2)),
              ),
            ]),
          ],
          if (block.detail.isNotEmpty) ...[
            const SizedBox(height: Sp.x2),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(Sp.x3),
              decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
              child: SelectableText(block.detail, style: const TextStyle(fontFamily: 'monospace', fontSize: Fs.xs)),
            ),
          ],
          AnimatedSize(
            duration: Motion.base,
            curve: Motion.ease,
            child: block.pending && onReply != null
                ? Padding(
                    padding: const EdgeInsets.only(top: Sp.x3),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Row(children: [
                        Expanded(child: OutlinedButton(onPressed: () => onReply(block.id, false), child: const Text('拒绝'))),
                        const SizedBox(width: Sp.x2),
                        Expanded(
                          child: FilledButton(
                              onPressed: () => onReply(block.id, true),
                              child: Text(block.options.isNotEmpty ? block.options.first.label : '批准')),
                        ),
                      ]),
                      for (final (i, o) in extras.indexed)
                        FadeSlideIn(
                          key: ValueKey('opt-${o.id}'),
                          delay: Motion.stagger(i + 1),
                          child: _ScopeRow(option: o, onTap: () => onOption!(block.id, o.id)),
                        ),
                    ]),
                  )
                : const SizedBox(width: double.infinity),
          ),
          RiseSwitcher(
            child: granted == null
                ? null
                : Padding(
                    key: ValueKey(granted),
                    padding: const EdgeInsets.only(top: Sp.x2),
                    child: Text(granted, style: context.text.bodySmall),
                  ),
          ),
        ]),
      ),
    );
  }
}

/// 批准范围的一行：图标 + 文字 + 箭头，整行可点（= 带这个范围批准）。
class _ScopeRow extends StatelessWidget {
  const _ScopeRow({required this.option, required this.onTap});
  final ApprovalOption option;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Pressable(
        onTap: onTap,
        semanticLabel: '批准，${option.label}',
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x2),
          decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.sm)),
          child: Row(children: [
            Icon(option.id == 'rule' ? Icons.rule_rounded : Icons.forum_outlined, size: 18, color: p.text2),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: ExcludeSemantics(
                child: Text(option.label, style: context.text.bodyMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
              ),
            ),
            Icon(Icons.chevron_right_rounded, size: 18, color: p.text3),
          ]),
        ),
      ),
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
