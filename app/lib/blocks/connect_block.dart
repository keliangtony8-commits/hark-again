// 连接卡（v2.36，后端 ConnectBlock / app/connector_accounts.py）：助手请你连一个账户。
//   [✉]  Google                              ← 名字
//        Gmail、日历、云端硬盘 / 已连接 · me@gmail.com / 授权失效 · …
//        “读你的日历排明天的事”                ← 助手写的理由（有才显示）
//   [ 连接 Google ]                           ← 已连接时消失（换号卡留“换个账户”）
// 授权在系统浏览器里本人完成；回到 App（或深链回来）时重新拉一次连接器列表，卡片原地换成“已连接”。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/connect.dart';
import '../core/resource.dart';
import '../models/block.dart';
import '../models/connect.dart';
import '../models/resources.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import 'block_frame.dart';

class ConnectBlockView extends ConsumerStatefulWidget {
  const ConnectBlockView(this.block, {super.key});
  final ConnectBlock block;

  @override
  ConsumerState<ConnectBlockView> createState() => _ConnectBlockViewState();
}

class _ConnectBlockViewState extends ConsumerState<ConnectBlockView> {
  // 从授权页切回来：列表可能变了
  late final _life = AppLifecycleListener(onResume: () => ref.read(connectorsProvider.notifier).reload().catchError((_) {}));

  @override
  void dispose() {
    _life.dispose();
    super.dispose();
  }

  static const _icons = {'google': Icons.mail_outline_rounded, 'github': Icons.code_rounded};

  @override
  Widget build(BuildContext context) {
    final b = widget.block;
    final p = context.palette;
    final list = ref.watch(connectorsProvider).value ?? const <Connector>[];
    final live = list.where((c) => c.id == b.provider).firstOrNull;
    final s = connectCardState(b, live);
    final lineColor = switch (s.tone) {
      ConnectTone.warning => p.warning,
      ConnectTone.done => p.ink,
      _ => p.text2,
    };
    return BlockFrame(
      tone: s.tone == ConnectTone.warning ? FrameTone.waiting : FrameTone.calm,
      padding: const EdgeInsets.all(Sp.x3),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: A11y.minTap,
            height: A11y.minTap,
            decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
            child: Icon(_icons[b.provider] ?? Icons.link_rounded, color: s.tone == ConnectTone.off ? p.text3 : p.ink, weight: 300),
          ),
          const SizedBox(width: Sp.x3),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(b.name, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
              SwapSwitcher(
                child: Row(key: ValueKey(s.line), children: [
                  if (s.tone == ConnectTone.done) ...[
                    Icon(Icons.check_circle_rounded, size: 14, color: p.ink),
                    const SizedBox(width: Sp.x1),
                  ],
                  Flexible(
                    child: Text(s.line,
                        style: context.text.bodySmall?.copyWith(color: lineColor), maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ]),
              ),
              if (b.reason != null && b.reason!.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: Sp.x1),
                  child: Text(b.reason!, style: context.text.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
                ),
            ]),
          ),
        ]),
        AnimatedSize(
          duration: Motion.base,
          curve: Motion.ease,
          child: s.button == null
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.only(top: Sp.x3),
                  child: s.tone == ConnectTone.done
                      ? OutlinedButton(onPressed: () => startConnect(context, ref, b.provider), child: Text(s.button!))
                      : FilledButton.icon(
                          onPressed: () => startConnect(context, ref, b.provider),
                          icon: const Icon(Icons.open_in_new_rounded, size: 18),
                          label: Text(s.button!),
                        ),
                ),
        ),
      ]),
    );
  }
}
