// “浏览器登录”一节（v1.26）：云浏览器按网站保存的会话（后端 app/browser_sessions.py）。
//   [🌐] taobao.com                                 正在用   退出
//        上次用 3 分钟前 · 登录已保存
//   登录过期（v1.36，服务端判定）：行尾“已过期”警示色，说明行“登录过期了，用到时会请你重新登录”，图标换成 public_off。
// 在某个网站登录一次，之后的任务都接着用；“退出”= 关掉那个网站的浏览器并删掉保存的登录（确认后）。
// 只在“我的 → 我的电脑”（浏览器是整个账号共用的，不属于某个项目）。加载中 / 浏览器服务连不上 → 不画这一节。
// 数据只在 browserSessionsProvider；文案规则在 models/browser_session.dart。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/swr.dart';
import '../../models/browser_session.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 加载 / 静默刷新规则在 core/swr.dart（只在内存）；这里只管退出。
class BrowserSessionsNotifier extends SwrNotifier<List<BrowserSession>> {
  @override
  String get path => '/api/browser/sessions';
  Api get _api => ref.read(apiProvider);

  @override
  List<BrowserSession> parse(Object? j) => sortBrowserSessions(
      [for (final x in ((j as Map)['sessions'] as List? ?? const [])) BrowserSession.fromJson((x as Map).cast<String, dynamic>())]);

  /// 退出登录：成功后先从列表里拿掉（不等刷新），出错抛给调用方提示。
  Future<void> signOut(String name) async {
    await _api.delete('$path/${Uri.encodeComponent(name)}');
    state = AsyncData([for (final s in state.value ?? const <BrowserSession>[]) if (s.name != name) s]);
    resync();
  }
}

final browserSessionsProvider =
    AsyncNotifierProvider.autoDispose<BrowserSessionsNotifier, List<BrowserSession>>(BrowserSessionsNotifier.new);

class BrowserSessionsSection extends ConsumerStatefulWidget {
  const BrowserSessionsSection({super.key, this.delay = Duration.zero, this.titled = true});
  final Duration delay;

  /// false = 子页里用，不画节标题（v3.5.1）。
  final bool titled;

  @override
  ConsumerState<BrowserSessionsSection> createState() => _BrowserSessionsSectionState();
}

class _BrowserSessionsSectionState extends ConsumerState<BrowserSessionsSection> {
  final _busy = <String>{};

  Future<void> _signOut(BrowserSession s) async {
    if (!await confirmDanger(context, title: '退出 ${s.label}？', text: browserSignOutText(s), action: '退出')) return;
    setState(() => _busy.add(s.name));
    try {
      await ref.read(browserSessionsProvider.notifier).signOut(s.name);
      if (mounted) showToast(context, '已退出 ${s.label}');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，退出失败' : e.message);
    } finally {
      if (mounted) setState(() => _busy.remove(s.name));
    }
  }

  @override
  Widget build(BuildContext context) {
    final list = ref.watch(browserSessionsProvider).value;
    return FadeSwitcher(
      child: list == null
          ? const SizedBox.shrink(key: ValueKey('none'))
          : FadeSlideIn(
              key: const ValueKey('sessions'),
              delay: widget.delay,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (widget.titled) const SectionTitle('浏览器登录'),
                ListGroup(children: [
                  if (list.isEmpty)
                    const ListRow(icon: Icons.public_rounded, title: browserSessionsEmpty, subtitle: browserSessionsEmptyLine)
                  else
                    for (final (i, s) in list.indexed)
                      FadeSlideIn(
                        key: ValueKey('bs-${s.name}'),
                        delay: Motion.stagger(i),
                        child: _SessionRow(session: s, busy: _busy.contains(s.name), onSignOut: () => _signOut(s)),
                      ),
                ]),
              ]),
            ),
    );
  }
}

class _SessionRow extends StatelessWidget {
  const _SessionRow({required this.session, required this.busy, required this.onSignOut});
  final BrowserSession session;
  final bool busy;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final hint = browserSessionHint(session);
    return Semantics(
      label: browserSessionSemantics(session),
      child: ListRow(
        icon: session.expired ? Icons.public_off_rounded : Icons.public_rounded,
        title: session.label,
        subtitle: browserSessionDetail(session),
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          if (hint != null) ...[RowHint(hint, warn: session.expired), const SizedBox(width: Sp.x2)],
          TextButton(onPressed: busy ? null : onSignOut, child: Text(busy ? '正在退出' : '退出')),
        ]),
      ),
    );
  }
}
