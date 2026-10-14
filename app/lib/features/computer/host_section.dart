// “服务器主机”一节（v1.49）：服务器主机模式的开关和“以后都允许”的命令规则（后端 app/host_mode.py）。
//   [▣] 主机模式已关闭                              (开关)
//       vps-1 · Debian GNU/Linux 12 · 已开机 3 天
//   打开前确认一次（说明每条命令都要批准）；没装主机代理 → 开关灰掉，下面一句怎么装；装了连不上 → 行尾“连不上”警示。
//   规则（只在有规则或开着时出现）：
//   [≡] systemctl status                             删除
//       放行过 4 次 · 上次 3 分钟前
// 只在“我的 → 我的电脑”（主机是整台 VPS，不属于某个项目）。加载中 / 后端太旧没有这个接口 → 不画这一节。
// 数据只在 hostProvider；文案规则在 models/host.dart。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../models/host.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class HostNotifier extends AsyncNotifier<HostStatus> {
  static const _path = '/api/host';
  Api get _api => ref.read(apiProvider);

  @override
  Future<HostStatus> build() async => _parse(await _api.get(_path));

  HostStatus _parse(dynamic j) => HostStatus.fromJson((j as Map).cast<String, dynamic>());

  Future<void> reload() async {
    try {
      state = AsyncData(_parse(await _api.get(_path)));
    } on ApiError {
      if (!state.hasValue) rethrow;
    }
  }

  /// 开 / 关。出错（没装 409、断网）抛给调用方提示，状态不变。
  Future<void> setEnabled(bool on) async {
    state = AsyncData(_parse(await _api.put(_path, {'enabled': on})));
  }

  Future<void> deleteRule(String id) async {
    state = AsyncData(_parse(await _api.delete('$_path/rules/${Uri.encodeComponent(id)}')));
  }
}

final hostProvider = AsyncNotifierProvider.autoDispose<HostNotifier, HostStatus>(HostNotifier.new);

class HostSection extends ConsumerStatefulWidget {
  const HostSection({super.key, this.delay = Duration.zero});
  final Duration delay;

  @override
  ConsumerState<HostSection> createState() => _HostSectionState();
}

class _HostSectionState extends ConsumerState<HostSection> {
  bool _toggling = false;
  final _deleting = <String>{};

  Future<void> _toggle(HostStatus s, bool on) async {
    if (on && !await confirmDanger(context, title: '打开服务器主机模式？', text: hostEnableText, action: '打开')) return;
    setState(() => _toggling = true);
    try {
      await ref.read(hostProvider.notifier).setEnabled(on);
      if (mounted) showToast(context, on ? '主机模式已打开' : '主机模式已关闭');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，切换失败' : e.message);
    } finally {
      if (mounted) setState(() => _toggling = false);
    }
  }

  Future<void> _delete(HostRule r) async {
    if (!await confirmDanger(context, title: '删除这条规则？', text: hostRuleDeleteText(r))) return;
    setState(() => _deleting.add(r.id));
    try {
      await ref.read(hostProvider.notifier).deleteRule(r.id);
      if (mounted) showToast(context, '已删除');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，删除失败' : e.message);
    } finally {
      if (mounted) setState(() => _deleting.remove(r.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(hostProvider).value;
    return FadeSwitcher(
      child: s == null
          ? const SizedBox.shrink(key: ValueKey('none'))
          : FadeSlideIn(
              key: const ValueKey('host'),
              delay: widget.delay,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const SectionTitle(hostSectionTitle),
                GlassGroup(children: [_ToggleRow(status: s, busy: _toggling, onChanged: (on) => _toggle(s, on))]),
                RiseSwitcher(
                  child: s.installed
                      ? null
                      : Padding(
                          key: const ValueKey('install'),
                          padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, 0),
                          child: Text(hostInstallHint, style: context.text.bodySmall),
                        ),
                ),
                AnimatedSize(
                  duration: Motion.base,
                  curve: Motion.ease,
                  alignment: Alignment.topCenter,
                  child: s.rules.isEmpty && !s.enabled
                      ? const SizedBox(width: double.infinity)
                      : Padding(
                          padding: const EdgeInsets.only(top: Sp.x3),
                          child: GlassGroup(children: [
                            if (s.rules.isEmpty)
                              const RowTile(icon: Icons.rule_rounded, title: hostRulesEmpty, subtitle: hostRulesEmptyLine)
                            else
                              for (final (i, r) in s.rules.indexed)
                                FadeSlideIn(
                                  key: ValueKey('rule-${r.id}'),
                                  delay: Motion.stagger(i),
                                  child: _RuleRow(rule: r, busy: _deleting.contains(r.id), onDelete: () => _delete(r)),
                                ),
                          ]),
                        ),
                ),
              ]),
            ),
    );
  }
}

class _ToggleRow extends StatelessWidget {
  const _ToggleRow({required this.status, required this.busy, required this.onChanged});
  final HostStatus status;
  final bool busy;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final hint = hostHint(status);
    return RowTile(
      icon: Icons.dns_outlined,
      title: hostToggleTitle(status),
      subtitle: hostDetail(status),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        if (hint != null) ...[RowHint(hint, warn: true), const SizedBox(width: Sp.x2)],
        Switch(
          value: status.enabled,
          onChanged: busy || !status.canToggle ? null : onChanged,
        ),
      ]),
    );
  }
}

class _RuleRow extends StatelessWidget {
  const _RuleRow({required this.rule, required this.busy, required this.onDelete});
  final HostRule rule;
  final bool busy;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '以后都允许 ${rule.text} 开头的命令，${hostRuleDetail(rule)}',
      child: RowTile(
        icon: Icons.rule_rounded,
        title: rule.text,
        subtitle: hostRuleDetail(rule),
        trailing: TextButton(onPressed: busy ? null : onDelete, child: Text(busy ? '正在删除' : '删除')),
      ),
    );
  }
}
