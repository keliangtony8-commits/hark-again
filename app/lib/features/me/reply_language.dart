// 回复语言（v2.67）：“我的 → 外观与偏好”里的一行 + 选择菜单（ui/sheets.dart 的 showActionSheet，选中项打勾）。
// 选了立即生效：先改界面（乐观），PATCH 失败退回原值并提示。对话里说“以后用英文回我”时助手调 set_reply_language
// 改的是同一个设置；provider 是 autoDispose，每次进“我的”页都重新取，所以那边改了这里也看得到。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../models/preferences.dart';
import '../../ui/kit.dart';
import '../../ui/sheets.dart';

class PreferencesNotifier extends AsyncNotifier<Preferences?> {
  static const _path = '/api/preferences';
  Api get _api => ref.read(apiProvider);

  /// 没登录 / 老服务器（没有这个接口）→ null：那一行显示默认说明、点不开，也不触发自动重试。
  @override
  Future<Preferences?> build() async {
    final s = await ref.watch(sessionProvider.future);
    if (!s.signedIn) return null;
    try {
      return Preferences.fromJson(Map<String, dynamic>.from(await _api.get(_path) as Map));
    } on ApiError {
      return null;
    }
  }

  /// 乐观更新；出错退回并抛给调用方提示。
  Future<void> setReplyLanguage(String code) async {
    final old = state.value;
    if (old == null || old.replyLanguage == code) return;
    state = AsyncData(old.copyWith(replyLanguage: code));
    try {
      state = AsyncData(Preferences.fromJson(Map<String, dynamic>.from(await _api.patch(_path, {'reply_language': code}) as Map)));
    } catch (_) {
      state = AsyncData(old);
      rethrow;
    }
  }
}

final preferencesProvider = AsyncNotifierProvider.autoDispose<PreferencesNotifier, Preferences?>(PreferencesNotifier.new);

class ReplyLanguageTile extends ConsumerWidget {
  const ReplyLanguageTile({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final prefs = ref.watch(preferencesProvider).value;
    return RowTile(
      key: const Key('reply-language'),
      icon: Icons.translate_rounded,
      title: '回复语言',
      subtitle: prefs?.replyLanguageLabel ?? '跟随我的语言',
      onTap: prefs == null || prefs.choices.isEmpty ? null : () => _pick(context, ref, prefs),
    );
  }

  Future<void> _pick(BuildContext context, WidgetRef ref, Preferences prefs) async {
    final code = await showActionSheet<String>(context, title: '回复语言', actions: [
      for (final c in prefs.choices)
        SheetAction(
          c.code == prefs.replyLanguage ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
          c.label,
          subtitle: Preferences.hintFor(c.code),
          value: c.code,
        ),
    ]);
    if (code == null) return;
    try {
      await ref.read(preferencesProvider.notifier).setReplyLanguage(code);
    } catch (_) {
      if (context.mounted) showToast(context, '没改成，稍后再试');
    }
  }
}
