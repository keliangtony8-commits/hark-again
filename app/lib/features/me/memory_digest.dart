// “我对你的了解”卡片：记忆页顶部，把全部记忆浓缩成一段话。
// 数据流：GET 很轻（零模型调用）——进页取一次，记忆列表每次变化（增删改）再静默取一次，拿到最新的 stale；
// POST 会花 token，只在用户点“生成/更新”时发，从不自动。老服务器没有这个接口（取失败）→ 整张卡不显示。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/memory.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';

@immutable
class DigestState {
  const DigestState({this.digest, this.loading = true, this.unavailable = false, this.generating = false, this.error});
  final MemoryDigest? digest;
  final bool loading, unavailable, generating;
  final String? error; // 上一次“生成”失败的提示；再点一次或成功后清掉

  DigestState copy({MemoryDigest? digest, bool? loading, bool? unavailable, bool? generating, String? error}) => DigestState(
      digest: digest ?? this.digest,
      loading: loading ?? this.loading,
      unavailable: unavailable ?? this.unavailable,
      generating: generating ?? this.generating,
      error: error);
}

class MemoryDigestController extends Notifier<DigestState> {
  static const path = '/api/memory-digest';

  @override
  DigestState build() {
    ref.listen(memoriesProvider, (prev, next) {
      if (prev != null && prev.hasValue && next.hasValue && !identical(prev.value, next.value)) fetch();
    });
    Future.microtask(fetch);
    return const DigestState();
  }

  Future<void> fetch() async {
    try {
      final j = (await ref.read(apiProvider).get(path) as Map).cast<String, dynamic>();
      if (!ref.mounted) return;
      state = state.copy(digest: MemoryDigest.fromJson(j), loading: false, unavailable: false, error: state.error);
    } catch (_) {
      if (!ref.mounted) return;
      if (state.digest == null) state = state.copy(loading: false, unavailable: true, error: state.error);
    }
  }

  Future<void> generate() async {
    if (state.generating) return;
    state = state.copy(generating: true);
    try {
      final j = (await ref.read(apiProvider).post(path) as Map).cast<String, dynamic>();
      if (!ref.mounted) return;
      state = state.copy(digest: MemoryDigest.fromJson(j), generating: false);
    } catch (_) {
      if (!ref.mounted) return;
      state = state.copy(generating: false, error: '生成失败，稍后再试');
    }
  }
}

final memoryDigestProvider = NotifierProvider.autoDispose<MemoryDigestController, DigestState>(MemoryDigestController.new);

class MemoryDigestCard extends ConsumerWidget {
  const MemoryDigestCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(memoryDigestProvider);
    final d = s.digest;
    final hidden = s.loading || s.unavailable || d == null || (d.memories == 0 && !d.hasText);
    return AnimatedSize(
      duration: context.motion(Motion.base),
      curve: Motion.ease,
      alignment: Alignment.topCenter,
      child: hidden
          ? const SizedBox(width: double.infinity)
          : FadeSlideIn(
              child: Padding(
                padding: const EdgeInsets.only(top: Sp.x2),
                child: Semantics(container: true, child: _Card(state: s, onGenerate: ref.read(memoryDigestProvider.notifier).generate)),
              ),
            ),
    );
  }
}

class _Card extends StatelessWidget {
  const _Card({required this.state, required this.onGenerate});
  final DigestState state;
  final VoidCallback onGenerate;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = state.digest!;
    final busy = state.generating;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const IconBadge(Icons.auto_awesome_rounded),
          const SizedBox(width: Sp.x3),
          Expanded(child: Text('我对你的了解', style: context.text.titleMedium)),
          if (d.hasText && d.stale && !busy) const Pill('记忆有更新', strong: true),
        ]),
        const SizedBox(height: Sp.x3),
        SwapSwitcher(
          child: KeyedSubtree(
            key: ValueKey(d.hasText ? 'text:${d.generatedAt}' : 'empty'),
            child: SizedBox(
              width: double.infinity,
              child: d.hasText
                  ? AnimatedOpacity(
                      duration: context.motion(Motion.base),
                      opacity: busy ? 0.5 : 1,
                      child: Text(d.text!, style: context.text.bodyMedium?.copyWith(height: Fs.lineHeight)),
                    )
                  : Text('把你的 ${d.memories} 条记忆浓缩成一段话。只在你点生成时调用一次便宜模型。',
                      style: context.text.bodyMedium?.copyWith(color: p.text2)),
            ),
          ),
        ),
        const SizedBox(height: Sp.x3),
        Row(children: [
          Expanded(
            child: Text(
              state.error ?? (d.hasText ? '根据 ${d.count} 条记忆 · ${formatWhen(d.generatedAt)}' : ''),
              style: context.text.bodySmall?.copyWith(color: state.error != null ? p.danger : p.text3),
            ),
          ),
          _GenerateButton(label: d.hasText ? '更新' : '生成', busy: busy, prominent: !d.hasText || d.stale, onPressed: onGenerate),
        ]),
      ]),
    );
  }
}

class _GenerateButton extends StatelessWidget {
  const _GenerateButton({required this.label, required this.busy, required this.prominent, required this.onPressed});
  final String label;
  final bool busy, prominent;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final icon = SwapSwitcher(
      child: busy
          ? SizedBox.square(key: const ValueKey('busy'), dimension: Sp.x4, child: CircularProgressIndicator(strokeWidth: 2, color: p.text3))
          : const Icon(Icons.refresh_rounded, key: ValueKey('idle'), size: Sp.x4 + 2),
    );
    final text = Text(busy ? '生成中…' : label);
    return prominent
        ? FilledButton.tonalIcon(onPressed: busy ? null : onPressed, icon: icon, label: text)
        : TextButton.icon(onPressed: busy ? null : onPressed, icon: icon, label: text);
  }
}
