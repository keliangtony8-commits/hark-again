// “安全”页的登录设备区块（v2.61，对标 Hark 设置 → 安全）：哪些设备登着这台服务器，退出某一台，或一键退出其他所有设备。
// 版式同“电脑 → 浏览器登录”：区块标题（带台数）→ 一组行，本机排第一、标“这台设备”，别的行尾一颗“退出”；
// 别的设备 ≥1 台时组尾多一行“退出其他所有设备”。退出前都要确认（confirmDanger）。规则在后端 app/login_sessions.py。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../models/login_session.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class LoginSessionsNotifier extends AsyncNotifier<List<LoginSession>?> {
  @override
  Future<List<LoginSession>?> build() async {
    final s = await ref.watch(sessionProvider.future);
    if (!s.signedIn) return null;
    return parseLoginSessions(await ref.read(apiProvider).get('/api/auth/sessions'));
  }

  /// 退出另一台：成功后先从列表拿掉（不等刷新）。本机不在这里退（“我的 → 退出登录”）。
  Future<void> revoke(LoginSession s) async {
    await ref.read(apiProvider).delete('/api/auth/sessions/${s.id}');
    state = AsyncData([for (final x in state.value ?? const <LoginSession>[]) if (x.id != s.id) x]);
  }

  /// 退出其他所有设备：返回退了几台；本机是老 token 时服务器换发新 token，这里接上。
  Future<int> revokeOthers() async {
    final j = await ref.read(apiProvider).post('/api/auth/sessions/revoke-others') as Map;
    await ref.read(sessionProvider.notifier).replaceToken('${j['token'] ?? ''}');
    state = AsyncData([for (final x in state.value ?? const <LoginSession>[]) if (x.current) x]);
    return (j['signed_out'] as num?)?.toInt() ?? 0;
  }
}

final loginSessionsProvider = AsyncNotifierProvider.autoDispose<LoginSessionsNotifier, List<LoginSession>?>(LoginSessionsNotifier.new);

class LoginSessionsSection extends ConsumerStatefulWidget {
  const LoginSessionsSection({super.key, this.delay = Duration.zero});
  final Duration delay;

  @override
  ConsumerState<LoginSessionsSection> createState() => _LoginSessionsSectionState();
}

class _LoginSessionsSectionState extends ConsumerState<LoginSessionsSection> {
  final _busy = <String>{};
  static const _all = '*';

  Future<void> _run(String key, Future<void> Function() job) async {
    setState(() => _busy.add(key));
    try {
      await job();
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '没连上服务器，没能退出' : e.message);
    } finally {
      if (mounted) setState(() => _busy.remove(key));
    }
  }

  Future<void> _revoke(LoginSession s) async {
    if (!await confirmDanger(context, title: '退出 ${s.label}？', text: '那台设备会立刻退出，要重新输入密码才能再用。', action: '退出')) return;
    await _run(s.id, () async {
      await ref.read(loginSessionsProvider.notifier).revoke(s);
      if (mounted) showToast(context, '已退出 ${s.label}');
    });
  }

  Future<void> _revokeOthers() async {
    if (!await confirmDanger(context, title: '退出其他所有设备？', text: '除了这台，别的手机、电脑、浏览器都会立刻退出。', action: '全部退出')) return;
    await _run(_all, () async {
      final n = await ref.read(loginSessionsProvider.notifier).revokeOthers();
      if (mounted) showToast(context, signedOutToast(n));
    });
  }

  @override
  Widget build(BuildContext context) {
    final list = ref.watch(loginSessionsProvider).value;
    return FadeSwitcher(
      child: list == null
          ? const SizedBox.shrink(key: ValueKey('none'))
          : FadeSlideIn(
              key: const ValueKey('sessions'),
              delay: widget.delay,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SectionTitle('登录设备', trailing: Text(loginSessionsSummary(list), style: context.text.labelSmall)),
                GlassGroup(children: [
                  for (final (i, s) in list.indexed)
                    FadeSlideIn(
                      key: ValueKey('ls-${s.id}'),
                      delay: Motion.stagger(i),
                      child: _Row(session: s, busy: _busy.contains(s.id), onRevoke: () => _revoke(s)),
                    ),
                  if (list.any((s) => !s.current))
                    RowTile(
                      key: const Key('ls-others'),
                      icon: Icons.logout_rounded,
                      title: _busy.contains(_all) ? '正在退出…' : '退出其他所有设备',
                      subtitle: '手机丢了、在别人电脑上登过时用',
                      onTap: _busy.contains(_all) ? null : _revokeOthers,
                    ),
                ]),
              ]),
            ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.session, required this.busy, required this.onRevoke});
  final LoginSession session;
  final bool busy;
  final VoidCallback onRevoke;

  @override
  Widget build(BuildContext context) {
    final s = session;
    return RowTile(
      icon: switch (s.kind) {
        'app' => Icons.smartphone_rounded,
        'browser' => Icons.laptop_rounded,
        _ => Icons.devices_other_rounded,
      },
      title: s.label,
      subtitle: loginSessionLine(s),
      trailing: s.current
          ? const RowHint('本机')
          : TextButton(onPressed: busy ? null : onRevoke, child: Text(busy ? '正在退出' : '退出')),
    );
  }
}
