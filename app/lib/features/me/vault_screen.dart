// 保险箱：API Key 和网站登录。只能存、看脱敏预览、删；明文永不回到手机上。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class VaultScreen extends ConsumerWidget {
  const VaultScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final secrets = ref.watch(secretsProvider);
    return SubPage(
      title: const Text('保险箱'),
      floatingActionButton: FloatingActionButton(onPressed: () => _add(context, ref), tooltip: '存入', child: const Icon(Icons.add_rounded)),
      body: AsyncBody<SecretItem>(
        value: secrets,
        onRetry: () => ref.invalidate(secretsProvider),
        empty: const EmptyHint(
          icon: Icons.lock_outline_rounded,
          title: '保险箱是空的',
          text: '存一个 API Key 或网站登录。我只在请求对应域名时使用它，回复里永远看不到明文。',
        ),
        builder: (list) {
          final keys = [for (final s in list) if (!s.isLogin) s];
          final logins = [for (final s in list) if (s.isLogin) s];
          return PageBody(children: [
            if (keys.isNotEmpty) ...[const SectionTitle('API Key'), ListGroup(children: [for (final s in keys) _SecretRow(s)])],
            if (logins.isNotEmpty) ...[const SectionTitle('网站登录'), ListGroup(children: [for (final s in logins) _SecretRow(s)])],
            const SizedBox(height: Sp.x3),
            Center(child: Text('加密保存在你自己的服务器上', style: context.text.labelSmall)),
          ]);
        },
      ),
    );
  }

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final kind = await showActionSheet<String>(context, title: '存入什么？', actions: const [
      SheetAction(Icons.key_rounded, 'API Key', value: 'api_key'),
      SheetAction(Icons.person_outline_rounded, '网站登录（用户名 + 密码）', value: 'login'),
    ]);
    if (kind == null || !context.mounted) return;
    final login = kind == 'login';
    final v = await showFormSheet(context, title: login ? '新网站登录' : '新 API Key', submit: '加密保存', fields: [
      FieldSpec('name', '名称', hint: login ? '比如：学校教务系统' : '比如：OpenWeather'),
      FieldSpec('hosts', '用于哪些域名', hint: login ? 'jwxt.example.edu.cn' : 'api.openweathermap.org（多个用逗号分开）', keyboard: TextInputType.url),
      if (login) const FieldSpec('username', '用户名'),
      FieldSpec('value', login ? '密码' : 'Key', obscure: true),
    ]);
    if (v == null || !context.mounted) return;
    try {
      await ref.read(secretsProvider.notifier).create({
        'kind': kind,
        'name': v['name'],
        'value': v['value'],
        'hosts': [for (final h in v['hosts']!.split(RegExp(r'[,，\s]+'))) if (h.isNotEmpty) h],
        if (login) 'username': v['username'],
      });
    } on ApiError catch (e) {
      if (context.mounted) showToast(context, e.message);
    }
  }
}

class _SecretRow extends ConsumerWidget {
  const _SecretRow(this.s);
  final SecretItem s;

  @override
  Widget build(BuildContext context, WidgetRef ref) => SwipeToDelete(
        id: s.id,
        confirm: () => confirmDanger(context, title: '删除「${s.name}」？', text: '用到它的任务会失败，直到你重新存入。'),
        onDelete: () => ref.read(secretsProvider.notifier).remove(s.id),
        child: FadeSlideIn(
          child: RowTile(
            icon: s.isLogin ? Icons.person_outline_rounded : Icons.key_rounded,
            title: s.name,
            subtitle: [if (s.username != null) s.username!, s.hosts.join('、')].join(' · '),
            trailing: Text(s.preview, style: context.text.labelSmall?.copyWith(fontFamily: 'monospace')),
          ),
        ),
      );
}
