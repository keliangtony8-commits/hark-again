// 连接器：账户（OAuth：Google、GitHub…）+ 我自己的 MCP 服务器 + 去保险箱存 API Key。
// 授权在系统浏览器里完成，服务器用深链把结果带回这一页（?connected= / ?error=）；
// 用户手动切回 App 时也会刷新一次状态。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/links.dart';
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

/// OAuth 回调带回来的结果（深链的查询参数）。没有结果时为 null。
class OAuthResult {
  const OAuthResult({this.connected, this.error});
  final String? connected;
  final String? error;

  static OAuthResult? fromQuery(Map<String, String> q) =>
      q['connected'] != null || q['error'] != null ? OAuthResult(connected: q['connected'], error: q['error']) : null;

  @override
  bool operator ==(Object other) => other is OAuthResult && other.connected == connected && other.error == error;
  @override
  int get hashCode => Object.hash(connected, error);
}

class ConnectorsScreen extends ConsumerStatefulWidget {
  const ConnectorsScreen({super.key, this.oauth});
  final OAuthResult? oauth;

  @override
  ConsumerState<ConnectorsScreen> createState() => _ConnectorsScreenState();
}

class _ConnectorsScreenState extends ConsumerState<ConnectorsScreen> {
  late final _life = AppLifecycleListener(onResume: () => ref.read(connectorsProvider.notifier).reload());

  @override
  void initState() {
    super.initState();
    _handleOAuth(widget.oauth);
  }

  @override
  void didUpdateWidget(ConnectorsScreen old) {
    super.didUpdateWidget(old);
    if (widget.oauth != old.oauth) _handleOAuth(widget.oauth); // 已在本页时深链只换参数
  }

  /// 提示一次授权结果，刷新列表，再把参数从地址里去掉（返回/重建时不重复提示）。
  void _handleOAuth(OAuthResult? r) {
    if (r == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      await ref.read(connectorsProvider.notifier).reload().catchError((_) {});
      if (!mounted) return;
      final list = ref.read(connectorsProvider).value ?? const <Connector>[];
      final name = list.where((c) => c.id == r.connected).firstOrNull?.name ?? r.connected;
      showToast(context, r.error == null ? '已连接 $name' : '连接没有完成：${r.error}');
      context.replace('/me/connectors');
    });
  }

  @override
  void dispose() {
    _life.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final accounts = ref.watch(connectorsProvider);
    final mcp = ref.watch(mcpServersProvider);
    return SubPage(
      title: const Text('连接器'),
      body: AsyncBody<Connector>(
        value: accounts,
        onRetry: () => ref.invalidate(connectorsProvider),
        builder: (list) {
          var i = 0; // 整页错峰序号：账户 → MCP → 其他服务一行一行进
          Duration next() => Motion.stagger(i++, from: 1);
          final servers = mcp.value;
          return PullRefresh(
            onRefresh: () => Future.wait([ref.read(connectorsProvider.notifier).reload(), ref.read(mcpServersProvider.notifier).reload()]),
            child: PageBody(children: [
              PageIntro(
                summary: connectorSummary(list, servers),
                line: '连接后我能读你的邮件、日历和代码仓库。发邮件、提交代码这类动作，永远先问你。',
              ),
              SectionTitle('账户', count: list.isEmpty ? null : list.length),
              ListGroup(children: [for (final c in sortAccounts(list)) _AccountRow(c, delay: next())]),
              SectionTitle('MCP 服务器',
                  trailing: servers == null || servers.isEmpty
                      ? null
                      : QuietAction(icon: const Icon(Icons.add_rounded), tooltip: '添加 MCP 服务器', onPressed: _addMcp)),
              FadeSwitcher(
                child: switch (mcp) {
                  AsyncData(:final value) when value.isEmpty => StarterCard(
                      key: const ValueKey('empty'),
                      title: '接入任何 MCP 服务',
                      text: '填一个支持 MCP（Streamable HTTP）的地址，我先连一次确认能用，之后就能用它的工具。',
                      starters: [PillButton(label: '添加 MCP 服务器', icon: Icons.add_rounded, onTap: _addMcp)],
                    ),
                  AsyncData(:final value) =>
                    ListGroup(key: const ValueKey('list'), children: [for (final s in value) _McpRow(s, delay: next())]),
                  AsyncError(:final error) => AppCard(key: const ValueKey('error'), child: Text('$error')),
                  _ => const SkeletonList(key: ValueKey('loading'), rows: 1),
                },
              ),
              const SectionTitle('其他服务'),
              ListGroup(children: [
                FadeSlideIn(
                  delay: next(),
                  child: RowTile(
                    icon: Icons.key_rounded,
                    title: 'API Key 与网站登录',
                    subtitle: '没有现成连接器的服务，把钥匙存进保险箱就能用',
                    onTap: () => context.push('/me/vault'),
                  ),
                ),
              ]),
            ]),
          );
        },
      ),
    );
  }

  Future<void> _addMcp() async {
    final v = await showFormSheet(context, title: '添加 MCP 服务器', subtitle: '保存前我会先连一次，确认能用', submit: '连接', fields: const [
      FieldSpec('name', '名称', hint: '比如：Notion'),
      FieldSpec('url', '地址', hint: 'https://…/mcp', keyboard: TextInputType.url),
      FieldSpec('token', '访问令牌（可选）', obscure: true, required: false),
    ]);
    if (v == null || !mounted) return;
    try {
      await ref.read(mcpServersProvider.notifier).create(v);
      if (mounted) showToast(context, '已连接 ${v['name']}');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    }
  }
}

class _AccountRow extends ConsumerWidget {
  const _AccountRow(this.c, {this.delay = Duration.zero});
  final Connector c;
  final Duration delay;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final usable = c.configured || c.connected;
    return FadeSlideIn(
      delay: delay,
      child: Dimmed(
        dimmed: !usable, // 服务器没配这个应用：留在列表里告诉你有这项，但点不了
        child: RowTile(
          icon: _icons[c.id] ?? Icons.link_rounded,
          title: c.name,
          subtitle: c.connected ? c.account : (c.configured ? c.desc : '服务器还没配置这个应用（见 .env.example）'),
          trailing: SwapSwitcher(
            child: c.connected
                ? const Pill('已连接', strong: true, key: ValueKey('on'))
                : (usable ? Text('连接', key: const ValueKey('off'), style: context.text.labelSmall) : const SizedBox.shrink(key: ValueKey('none'))),
          ),
          onTap: !usable ? null : () => c.connected ? _manage(context, ref) : _connect(context, ref),
        ),
      ),
    );
  }

  static const _icons = {'google': Icons.mail_outline_rounded, 'github': Icons.code_rounded};

  Future<void> _connect(BuildContext context, WidgetRef ref) async {
    try {
      final j = await ref.read(apiProvider).get('/api/connectors/${c.id}/start?client=app') as Map<String, dynamic>;
      await openUrl(j['url'] as String);
    } on ApiError catch (e) {
      if (context.mounted) showToast(context, e.message);
    }
  }

  void _manage(BuildContext context, WidgetRef ref) => showActionSheet<void>(context, title: '${c.name} · ${c.account}', actions: [
        SheetAction(Icons.refresh_rounded, '重新授权', onTap: () => _connect(context, ref)),
        SheetAction(Icons.link_off_rounded, '断开连接', onTap: () async {
          if (await confirmDanger(context, title: '断开 ${c.name}？', text: '我将不能再代你读写这个账户。', action: '断开')) {
            await ref.read(apiProvider).delete('/api/connectors/${c.id}');
            await ref.read(connectorsProvider.notifier).reload();
          }
        }, danger: true),
      ]);
}

class _McpRow extends ConsumerWidget {
  const _McpRow(this.s, {this.delay = Duration.zero});
  final McpServerItem s;
  final Duration delay;

  @override
  Widget build(BuildContext context, WidgetRef ref) => SwipeToDelete(
        id: s.id,
        confirm: () => confirmDanger(context, title: '移除 ${s.name}？'),
        onDelete: () => ref.read(mcpServersProvider.notifier).remove(s.id),
        child: FadeSlideIn(
          delay: delay,
          child: RowTile(
            icon: Icons.extension_outlined,
            title: s.name,
            // 连不上 / 令牌被拒：副标题先说问题（警示色），主页同时有一张“需要你亲自处理”的卡
            subtitle: s.problemText == null ? hostOf(s.url) : '${s.problemText} · ${hostOf(s.url)}',
            subtitleColor: s.problemText == null ? null : context.palette.warning,
            trailing: SwapSwitcher(
              child: s.problemText != null
                  ? Icon(Icons.error_outline_rounded, key: const ValueKey('problem'), size: 20, color: context.palette.warning,
                      semanticLabel: s.problemText)
                  : (s.hasToken ? const Pill('带令牌', key: ValueKey('token')) : const SizedBox.shrink(key: ValueKey('none'))),
            ),
            onTap: () => _showTools(context, ref),
          ),
        ),
      );

  Future<void> _showTools(BuildContext context, WidgetRef ref) async {
    final tools = ref.read(apiProvider).get('/api/connectors/mcp/${s.id}/tools');
    await showAppScrollSheet<void>(
      context,
      builder: (ctx, scroll) => FutureBuilder(
          future: tools,
          builder: (ctx, snap) {
            if (snap.hasError) return EmptyHint(icon: Icons.cloud_off_rounded, title: '连不上', text: '${snap.error}');
            if (!snap.hasData) return const Padding(padding: EdgeInsets.all(Sp.x5), child: SkeletonList());
            final list = snap.data as List;
            return ListView(controller: scroll, padding: const EdgeInsets.only(bottom: Sp.x5), children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x5, Sp.x3),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${list.length} 个工具 · ${hostOf(s.url)}', style: ctx.text.labelSmall),
                  const SizedBox(height: Sp.x1),
                  Text(s.name, style: ctx.text.titleLarge),
                ]),
              ),
              if (list.isEmpty)
                const EmptyHint(icon: Icons.handyman_outlined, title: '没有工具', text: '这个服务器连得上，但没有提供任何工具。'),
              for (final (i, t) in list.indexed)
                FadeSlideIn(
                  delay: Motion.stagger(i),
                  child: ListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: Sp.x5),
                    leading: const IconBadge(Icons.build_outlined),
                    title: Text('${t['name']}'),
                    subtitle: Text('${t['description'] ?? ''}', maxLines: 3, overflow: TextOverflow.ellipsis),
                  ),
                ),
            ]);
          },
        ),
    );
    // 打开工具列表 = 一次体检（后端据此放 / 收主页提醒）：关掉后刷新这一行的状态
    await tools.then((_) {}, onError: (_) {});
    if (context.mounted) await ref.read(mcpServersProvider.notifier).reload();
  }
}
