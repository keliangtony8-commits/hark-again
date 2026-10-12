// 每个对话选模型（快速 / 深度）：可选列表 + 输入框上的切换钮。
// 列表来自 GET /api/catalog/models（服务器 .env 的 CHAT_MODELS），离线可读：先用缓存，后台刷新。
// 选择本身归 ChatController（ChatState.model，null = 默认）；这里只负责“画出来、点了告诉 controller”。
// 两项 → 点一下就切换（标签上下错开换字）；三项及以上 → 弹选择菜单。列表不足两项时整个钮不出现。
// 思考强度钮（EffortChip）紧挨着：当前模型能调（≥2 档，后端 reasoning.catalog）才出现，点开选档（带一行说明）。
// 两个钮由 ModelChoice 排成一行；换到不能调的模型时思考钮淡出收起。
// 计划模式钮（PlanModeChip，v1.71）：点一下开 / 关。开着时助手只看不改，先交方案给你批准（后端 app/plan_mode.py）；
// 方案被批准后服务器推 conversation.mode，钮自己关掉。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/cache.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import '../../ui/kit.dart';
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

  static IconData iconFor(String id, ModelCatalog cat) => cat.isAuto(id)
      ? Icons.alt_route_rounded
      : id == cat.defaultId
          ? Icons.bolt_rounded
          : Icons.auto_awesome_outlined;

  Future<void> _choose(BuildContext context, WidgetRef ref, ModelCatalog cat, String current) async {
    final ctl = ref.read(chatProvider(scope).notifier);
    String? picked;
    if (cat.options.length == 2) {
      picked = cat.options.firstWhere((o) => o.id != current).id;
    } else {
      picked = await showActionSheet<String>(context, title: '这个对话用哪个模型', actions: [
        for (final o in cat.options)
          SheetAction(o.id == current ? Icons.check_rounded : iconFor(o.id, cat), o.label,
              subtitle: cat.isAuto(o.id) ? cat.autoHint() : null, value: o.id),
      ]);
    }
    if (picked != null && picked != current) await ctl.setModel(cat.toChoice(picked));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cat = ref.watch(modelCatalogProvider).value;
    if (cat == null || !cat.selectable) return const SizedBox.shrink();
    final (choice, routed) = ref.watch(chatProvider(scope).select((s) => (s.model, s.routed)));
    final eff = cat.effective(choice)!;
    final label = cat.chipLabel(eff, routed);
    final strong = eff.id != cat.defaultId; // 非默认（通常是更贵的模型）用强调色，一眼看出这轮在花更多钱
    final p = context.palette;
    final fg = strong ? p.text : p.text2;
    return Pressable(
      onTap: () => _choose(context, ref, cat, eff.id),
      scale: 0.92,
      semanticLabel: '模型：$label，点按切换',
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
              child: Row(key: ValueKey(label), mainAxisSize: MainAxisSize.min, children: [
                Icon(iconFor(eff.id, cat), size: 15, color: fg),
                const SizedBox(width: Sp.x1),
                Text(label, style: context.text.labelMedium?.copyWith(color: fg)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// 输入框里的“模型选择”：模型钮 + 思考强度钮（当前模型能调才有）+ 计划模式开关。
class ModelChoice extends StatelessWidget {
  const ModelChoice({super.key, required this.scope});
  final String scope;

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        ModelChip(scope: scope),
        EffortChip(scope: scope), // 自带 FadeSwitcher（淡入淡出 + 收起宽度）
        PlanModeChip(scope: scope),
      ]);
}

/// 思考强度钮：显示当前档（非默认档一圈细边，和模型钮同一规则），点开选档。
class EffortChip extends ConsumerWidget {
  const EffortChip({super.key, required this.scope});
  final String scope;

  static String semantics(EffortLevel eff) => '思考强度：${eff.label}，点按选择';

  Future<void> _choose(BuildContext context, WidgetRef ref, ModelEfforts efforts, EffortLevel current) async {
    final picked = await showActionSheet<String>(context, title: '想多深', actions: [
      for (final l in efforts.levels)
        SheetAction(l.id == current.id ? Icons.check_rounded : Icons.psychology_outlined,
            l.id == efforts.defaultId ? '${l.label}（默认）' : l.label,
            subtitle: l.description.isEmpty ? null : l.description, value: l.id),
    ]);
    if (picked != null && picked != current.id) await ref.read(chatProvider(scope).notifier).setEffort(efforts.toChoice(picked));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cat = ref.watch(modelCatalogProvider).value;
    final choice = ref.watch(chatProvider(scope).select((s) => (s.model, s.effort)));
    final model = cat?.effective(choice.$1);
    final efforts = model == null ? null : cat!.effortsFor(model.id);
    final eff = efforts?.effective(choice.$2);
    final p = context.palette;
    final strong = eff != null && eff.id != efforts!.defaultId;
    final fg = strong ? p.text : p.text2;
    return FadeSwitcher(
      child: eff == null
          ? const SizedBox.shrink(key: ValueKey('none'))
          : Padding(
              key: const ValueKey('effort'),
              padding: const EdgeInsets.only(left: Sp.x1),
              child: Pressable(
                onTap: () => _choose(context, ref, efforts!, eff),
                scale: 0.92,
                semanticLabel: semantics(eff),
                child: SizedBox(
                  height: A11y.minTap,
                  child: Center(
                    child: AnimatedContainer(
                      duration: context.motion(Motion.base),
                      curve: Motion.ease,
                      padding: const EdgeInsets.symmetric(horizontal: Sp.x2 + 2, vertical: Sp.x1 + 2),
                      decoration: BoxDecoration(
                        color: context.tileFill,
                        border: Border.all(color: strong ? p.text3 : Colors.transparent),
                        borderRadius: BorderRadius.circular(Radii.full),
                      ),
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.psychology_outlined, size: 15, color: fg),
                        const SizedBox(width: Sp.x1),
                        SwapSwitcher(child: Text(eff.label, key: ValueKey(eff.id), style: context.text.labelMedium?.copyWith(color: fg))),
                      ]),
                    ),
                  ),
                ),
              ),
            ),
    );
  }
}

/// 计划模式开关：关着只是一枚淡色地图图标（输入框一行很挤），开着换成实心图标 +“计划”+ 一圈细边（和非默认模型同一规则）。
class PlanModeChip extends ConsumerWidget {
  const PlanModeChip({super.key, required this.scope});
  final String scope;

  static String semantics(bool on) => on ? '计划模式已开：只看不改，先交方案给你批准。点按关闭' : '计划模式已关。点按打开：先出方案、你批准后再动手';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final on = ref.watch(chatProvider(scope).select((s) => s.planMode));
    final p = context.palette;
    final fg = on ? p.text : p.text2;
    return Padding(
      padding: const EdgeInsets.only(left: Sp.x1),
      child: Pressable(
        onTap: () {
          ref.read(chatProvider(scope).notifier).setPlanMode(!on);
          showToast(context, on ? '已退出计划模式' : '计划模式：先出方案，你批准后再动手');
        },
        scale: 0.92,
        semanticLabel: semantics(on),
        child: SizedBox(
          height: A11y.minTap,
          child: Center(
            child: AnimatedContainer(
              duration: context.motion(Motion.base),
              curve: Motion.ease,
              padding: EdgeInsets.symmetric(horizontal: on ? Sp.x2 + 2 : Sp.x1 + 2, vertical: Sp.x1 + 2),
              decoration: BoxDecoration(
                color: context.tileFill,
                border: Border.all(color: on ? p.text3 : Colors.transparent),
                borderRadius: BorderRadius.circular(Radii.full),
              ),
              child: SwapSwitcher(
                child: Row(key: ValueKey(on), mainAxisSize: MainAxisSize.min, children: [
                  Icon(on ? Icons.map_rounded : Icons.map_outlined, size: 15, color: fg),
                  if (on) ...[
                    const SizedBox(width: Sp.x1),
                    Text('计划', style: context.text.labelMedium?.copyWith(color: fg)),
                  ],
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
