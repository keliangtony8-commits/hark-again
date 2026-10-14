// 端口预览卡（v1.30，后端 PreviewBlock / app/preview.py）：工作区电脑里跑着的网页服务。
//   [🌐]  记账小工具                     ← 标题（没有就“端口 8000”）
//         端口 8000 · python3 -m http.server
//         24 小时内有效
//   [ 打开 ]  [ 复制链接 ]
// 点卡片或“打开”用系统浏览器开；过期后按钮换成一句“让我重新生成”。文案规则在 models/preview.dart。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/links.dart';
import '../models/block.dart';
import '../models/preview.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/kit.dart';
import '../ui/glass.dart';

class PreviewBlockView extends StatelessWidget {
  const PreviewBlockView(this.block, {super.key, this.now});
  final PreviewBlock block;

  /// 测试用：固定“现在”。
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = now ?? DateTime.now();
    final expired = previewExpired(block.expiresAt, t);
    final expiry = previewExpiry(block.expiresAt, t);
    final line = ['端口 ${block.port}', if (block.command.isNotEmpty) shortCommand(block.command)].join(' · ');
    return AppCard(
      onTap: expired ? null : () => openUrl(block.url),
      padding: const EdgeInsets.all(Sp.x3),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(Radii.inner), color: context.tileFill),
            child: Icon(Icons.language_rounded, color: expired ? p.text3 : p.ink, weight: 300),
          ),
          const SizedBox(width: Sp.x3),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(portTitle(block.port, block.title),
                  style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
              Text(line, style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              if (expiry.isNotEmpty)
                Text(expiry, style: context.text.bodySmall?.copyWith(color: expired ? p.warning : p.text3)),
            ]),
          ),
        ]),
        AnimatedSize(
          duration: Motion.base,
          curve: Motion.ease,
          child: Padding(
            padding: const EdgeInsets.only(top: Sp.x3),
            child: expired
                ? Text('链接已过期。服务仍在运行时，可让我重新生成。', style: context.text.bodySmall)
                : Row(children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: () => openUrl(block.url),
                        icon: const Icon(Icons.open_in_new_rounded, size: 18),
                        label: const Text('打开'),
                      ),
                    ),
                    const SizedBox(width: Sp.x2),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () {
                          Clipboard.setData(ClipboardData(text: block.url));
                          showToast(context, '链接已复制');
                        },
                        icon: const Icon(Icons.link_rounded, size: 18),
                        label: const Text('复制链接'),
                      ),
                    ),
                  ]),
          ),
        ),
      ]),
    );
  }
}
