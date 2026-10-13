// 保险箱：API Key、网站登录、命令环境变量。只能存、看脱敏预览、删；明文永不回到手机上。
// 版式与技能/定时任务页同一套：页头摘要 + 说明 → 空时起步卡 → 分组（带数量）→ 行错峰进场。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'connector_library.dart';
import 'task_wall.dart' show withRetried;

class VaultScreen extends ConsumerWidget {
  const VaultScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final secrets = ref.watch(secretsProvider);
    return SubPage(
      title: const Text('保险箱'),
      actions: [IconButton(icon: const Icon(Icons.add_rounded), tooltip: '存入', onPressed: () => addSecret(context, ref))],
      body: AsyncBody<SecretItem>(
        value: secrets,
        onRetry: () => ref.invalidate(secretsProvider),
        builder: (list) {
          final g = groupSecrets(list);
          var i = 0; // 整页错峰序号
          Widget rows(List<SecretItem> items) => ListGroup(children: [for (final s in items) _SecretRow(s, delay: Motion.stagger(i++, from: 1))]);
          return PullRefresh(
            onRefresh: () => ref.read(secretsProvider.notifier).reload(),
            child: PageBody(children: [
              PageIntro(summary: vaultSummary(list), line: '加密存在你自己的服务器上，只用于你指定的网站或你电脑上的命令。我只知道“有这把钥匙”，回复里永远看不到内容。'),
              if (list.isEmpty) const _Starters(),
              if (g.logins.isNotEmpty) ...[SectionTitle('网站登录', count: g.logins.length), rows(g.logins)],
              if (g.keys.isNotEmpty) ...[SectionTitle('API Key', count: g.keys.length), rows(g.keys)],
              if (g.envs.isNotEmpty) ...[SectionTitle('环境变量', count: g.envs.length), rows(g.envs)],
            ]),
          );
        },
      ),
    );
  }
}

/// 存入一把钥匙：没给 [kind] 先问存哪类，再弹对应表单。页头 +、起步卡共用。
Future<void> addSecret(BuildContext context, WidgetRef ref, {String? kind}) async {
  kind ??= await showActionSheet<String>(context, title: '存入什么？', actions: [
    for (final k in secretKinds) SheetAction(_kindIcon(k.kind), '${k.label} · ${k.desc}', value: k.kind),
  ]);
  if (kind == null || !context.mounted) return;
  if (kind == 'env') return addEnv(context, ref);
  final login = kind == 'login';
  final v = await showFormSheet(context,
      title: login ? '新网站登录' : '新 API Key',
      subtitle: '保存后不会再显示，发往其他网站的请求不会带上它',
      submit: '加密保存',
      fields: [
        FieldSpec('name', '名称', hint: login ? '比如：学校教务系统' : '比如：OpenWeather'),
        FieldSpec('hosts', login ? '网站域名' : '只用于这些域名',
            hint: login ? 'jwxt.example.edu.cn' : 'api.openweathermap.org（多个用逗号分开）', keyboard: TextInputType.url),
        if (login) const FieldSpec('username', '用户名 / 手机号 / 邮箱'),
        FieldSpec('value', login ? '密码' : 'Key', obscure: true),
      ]);
  if (v == null || !context.mounted) return;
  await _save(context, ref, {
    'kind': kind,
    'name': v['name'],
    'value': v['value'],
    'hosts': [for (final h in v['hosts']!.split(RegExp(r'[,，\s]+'))) if (h.isNotEmpty) h],
    if (login) 'username': v['username'],
  }, v['name']!);
}

/// 新环境变量；给了 [name] = 给已有变量换值（同名保存即覆盖，名字不可改）。
Future<void> addEnv(BuildContext context, WidgetRef ref, {String? name}) async {
  final v = await showFormSheet(context,
      title: name == null ? '新环境变量' : '给 \$$name 换个值',
      subtitle: '只注入你电脑上跑的命令（含后台、常驻、定时脚本），输出里显示成 [\$名字]；常驻程序重启后用新值',
      submit: '加密保存',
      fields: [
        if (name == null) const FieldSpec('name', '变量名', hint: 'TELEGRAM_BOT_TOKEN', keyboard: TextInputType.visiblePassword),
        const FieldSpec('value', '值', obscure: true),
      ]);
  if (v == null || !context.mounted) return;
  final n = name ?? envName(v['name']!);
  final err = name == null ? envNameError(n) : null;
  if (err != null) {
    showToast(context, err);
    return;
  }
  await _save(context, ref, {'kind': 'env', 'name': n, 'value': v['value']}, '\$$n');
}

Future<void> _save(BuildContext context, WidgetRef ref, Map<String, dynamic> body, String label) async {
  try {
    final notifier = ref.read(secretsProvider.notifier);
    final saved = await notifier.create(body);
    if (body['kind'] == 'env') await notifier.reload(); // 同名环境变量是覆盖：旧那条服务器已删，重拉一次免得列表里出现两条
    if (context.mounted) showToast(context, withRetried('已加密保存「$label」', saved.retriedNote));
  } on ApiError catch (e) {
    if (context.mounted) showToast(context, e.message);
  }
}

IconData _kindIcon(String kind) => switch (kind) {
      'login' => Icons.person_outline_rounded,
      'env' => Icons.terminal_rounded,
      _ => Icons.key_rounded,
    };

/// 空保险箱：两类各一个起步按钮，直接打开对应表单。
class _Starters extends ConsumerWidget {
  const _Starters();

  @override
  Widget build(BuildContext context, WidgetRef ref) => Padding(
        padding: const EdgeInsets.only(top: Sp.x4),
        child: StarterCard(
          title: '保险箱是空的',
          text: '存一个网站登录，我在云浏览器里能替你登录；存一个 API Key，我就能调用那个服务；存一个环境变量，你电脑上的程序就能读到它。',
          starters: [
            for (final k in secretKinds)
              PillButton(label: k.label, icon: _kindIcon(k.kind), onTap: () => addSecret(context, ref, kind: k.kind)),
          ],
        ),
      );
}

Future<bool> _confirmDelete(BuildContext context, SecretItem s) =>
    confirmDanger(context, title: '删除「${s.name}」？', text: '用到它的任务会失败，直到你重新存入。');

class _SecretRow extends ConsumerWidget {
  const _SecretRow(this.s, {this.delay = Duration.zero});
  final SecretItem s;
  final Duration delay;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hint = secretHint(s);
    return SwipeToDelete(
      id: s.id,
      confirm: () => _confirmDelete(context, s),
      onDelete: () => ref.read(secretsProvider.notifier).remove(s.id),
      child: FadeSlideIn(
        delay: delay,
        child: RowTile(
          icon: _kindIcon(s.kind),
          title: s.name,
          subtitle: secretWhere(s),
          trailing: hint.isEmpty ? null : Text(hint, style: context.text.labelSmall),
          onTap: () => _manage(context, ref),
        ),
      ),
    );
  }

  /// 点一行：看清它用于哪里，删除也在这里（左滑之外的明面入口）。
  void _manage(BuildContext context, WidgetRef ref) => showActionSheet<void>(context, title: '${s.name} · ${secretWhere(s)}', actions: [
        if (s.isEnv) SheetAction(Icons.edit_outlined, '换个值', onTap: () => addEnv(context, ref, name: s.name)),
        SheetAction(Icons.delete_outline_rounded, '删除', danger: true, onTap: () async {
          if (await _confirmDelete(context, s)) await ref.read(secretsProvider.notifier).remove(s.id);
        }),
      ]);
}
