// 每个对话选模型（快速 / 深度）：可选列表 + 输入框上的切换钮。
// 列表来自 GET /api/catalog/models（服务器 .env 的 CHAT_MODELS），离线可读：先用缓存，后台刷新。
// 选择本身归 ChatController（ChatState.model，null = 默认）；这里只负责“画出来、点了告诉 controller”。
// 两项 → 点一下就切换（标签上下错开换字）；三项及以上 → 弹选择菜单。列表不足两项时整个钮不出现。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/cache.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'chat_controller.dart';
import '../../ui/glass.dart';

class ModelCatalogNotifier extends AsyncNotifier<ModelCatalog> {
  static const _key = 'models';

  @override
  Future<ModelCatalog> build() async {
    final cache = ref.read(cacheStoreProvider);
    final cached = await cache.read(_key);
    if (cached is Map) {
      Future.microtask(_revalidate);
      return ModelCatalog.fromJson(cached.cast<String, dynamic>());
    }
    return _fetch();
  }

  Future<ModelCatalog> _fetch() async {
    final raw = await ref.read(apiProvider).get('/api/catalog/models') as Map<String, dynamic>;
    unawaited(ref.read(cacheStoreProvider).write(_key, raw));
    return ModelCatalog.fromJson(raw);
  }

  Future<void> _revalidate() async {
    try {
      state = AsyncData(await _fetch());
    } catch (_) {} // 断网等：缓存照常用
  }
}

final modelCatalogProvider = AsyncNotifierProvider<ModelCatalogNotifier, ModelCatalog>(ModelCatalogNotifier.new);

/// 输入框里的模型钮。[scope] = chatProvider 的 family 参数（'' 主聊天 / 项目 id）。
class ModelChip extends ConsumerWidget {
  const ModelChip({super.key, required this.scope});
  final String scope;

  static IconData iconFor(String id, ModelCatalog cat) =>
      id == cat.defaultId ? Icons.bolt_rounded : Icons.auto_awesome_outlined;

  Future<void> _choose(BuildContext context, WidgetRef ref, ModelCatalog cat, String current) async {
    final ctl = ref.read(chatProvider(scope).notifier);
    String? picked;
    if (cat.options.length == 2) {
      picked = cat.options.firstWhere((o) => o.id != current).id;
    } else {
      picked = await showActionSheet<String>(context, title: '这个对话用哪个模型', actions: [
        for (final o in cat.options) SheetAction(o.id == current ? Icons.check_rounded : iconFor(o.id, cat), o.label, value: o.id),
      ]);
    }
    if (picked != null && picked != current) await ctl.setModel(cat.toChoice(picked));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cat = ref.watch(modelCatalogProvider).value;
    if (cat == null || !cat.selectable) return const SizedBox.shrink();
    final choice = ref.watch(chatProvider(scope).select((s) => s.model));
    final eff = cat.effective(choice)!;
    final strong = eff.id != cat.defaultId; // 非默认（通常是更贵的模型）用强调色，一眼看出这轮在花更多钱
    final p = context.palette;
    final fg = strong ? p.text : p.text2;
    return Pressable(
      onTap: () => _choose(context, ref, cat, eff.id),
      scale: 0.92,
      semanticLabel: '模型：${eff.label}，点按切换',
      child: SizedBox(
        height: A11y.minTap,
        child: Center(
          child: AnimatedContainer(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            padding: const EdgeInsets.symmetric(horizontal: Sp.x2 + 2, vertical: Sp.x1 + 2),
            decoration: BoxDecoration(
              color: context.tileFill,
              border: Border.all(color: strong ? p.text3 : Colors.transparent), // 非默认模型：一圈细边，不再上橙色
              borderRadius: BorderRadius.circular(Radii.full),
            ),
            child: SwapSwitcher(
              child: Row(key: ValueKey(eff.id), mainAxisSize: MainAxisSize.min, children: [
                Icon(iconFor(eff.id, cat), size: 15, color: fg),
                const SizedBox(width: Sp.x1),
                Text(eff.label, style: context.text.labelMedium?.copyWith(color: fg)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
