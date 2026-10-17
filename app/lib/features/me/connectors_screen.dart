// 连接的账号（v2.96 一页）：账户（OAuth：Google、GitHub…）→ MCP 服务器 → 网站登录 → API Key → 环境变量，按“越省事越靠前”分区；
// 页头 + 是唯一的添加入口（四类同一张表 addKinds）。原来的保险箱页、“账户”收拢页已并进来、删除。
// 授权在系统浏览器里完成，服务器用深链把结果带回这一页（?connected= / ?error=）；
// 用户手动切回 App 时也会刷新一次状态。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/connect.dart';
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
import 'oauth_setup_sheet.dart';
import 'secret_rows.dart';
import 'task_wall.dart' show withRetried;

/// OAuth 回调带回来的结果（深链的查询参数）。没有结果时为 null。
class OAuthResult {
  const OAuthResult({this.connected, this.error, this.retried});
  final String? connected;
  final String? error;

  /// v2.19 连好后服务端顺手重跑的碰壁任务那句话（?retried=），没有 = null。
  final String? retried;

  static OAuthResult? fromQuery(Map<String, String> q) => q['connected'] != null || q['error'] != null
      ? OAuthResult(connected: q['connected'], error: q['error'], retried: q['retried'])
      : null;

  @override
  bool operator ==(Object other) =>
      other is OAuthResult && other.connected == connected && other.error == error && other.retried == retried;
  @override
  int get hashCode => Object.hash(connected, error, retried);
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
      showToast(context, r.error == null ? withRetried('已连接 $name', r.retried) : '连接没有完成：${r.error}');
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
    final secrets = ref.watch(secretsProvider);
    return SubPage(
      title: const Text('连接的账号'),
      actions: [IconButton(icon: const Icon(Icons.add_rounded), tooltip: '添加', onPressed: _add)],
      body: AsyncBody<Connector>(
        value: accounts,
        onRetry: () => ref.invalidate(connectorsProvider),
        builder: (list) {
          final shown = sortAccounts(list), missing = missingSetup(list);
          var i = 0; // 整页错峰序号：账户 → MCP → 密钥一行一行进
          Duration next() => Motion.stagger(i++, from: 1);
          final servers = mcp.value, keys = secrets.value;
          final g = keys == null ? null : groupSecrets(keys);
          Widget secretGroup(String title, List<SecretItem> items) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SectionTitle(title, count: items.length),
                ListGroup(children: [for (final s in items) SecretRow(s, delay: next())]),
              ]);
          return PullRefresh(
            onRefresh: () => Future.wait([
              ref.read(connectorsProvider.notifier).reload(),
              ref.read(mcpServersProvider.notifier).reload(),
              ref.read(secretsProvider.notifier).reload(),
            ]),
            child: PageBody(children: [
              PageIntro(
                summary: connectorSummary(list, servers, keys),
                line: '一键授权的账号、MCP 服务器，以及加密保存的网站登录、API Key 和环境变量。发邮件、推送代码这类动作，永远先问你；密钥我只知道“有”，看不到内容。',
              ),
              // v2.90.2 只画服务器配好了的（或已连过的）；缺配置时给部署者一行，点开是引导，不放点了会失败的按钮
              if (shown.isNotEmpty || missing.isNotEmpty) ...[
                SectionTitle('账户', count: shown.isEmpty ? null : shown.length),
                ListGroup(children: [
                  for (final c in shown) _AccountRow(c, delay: next()),
                  if (missing.isNotEmpty)
                    FadeSlideIn(
                      delay: next(),
                      child: ListRow(
                        icon: Icons.tune_rounded,
                        title: '服务器还差一步',
                        subtitle: setupLine(missing),
                        onTap: () => showOAuthSetupSheet(context, missing),
                      ),
                    ),
                ]),
              ],
              if (servers != null && servers.isNotEmpty) ...[
                SectionTitle('MCP 服务器', count: servers.length),
                ListGroup(children: [for (final s in sortServers(servers)) _McpRow(s, delay: next())]),
              ],
              if (g != null && g.logins.isNotEmpty) secretGroup('网站登录', g.logins),
              if (g != null && g.keys.isNotEmpty) secretGroup('API Key', g.keys),
              if (g != null && g.envs.isNotEmpty) secretGroup('环境变量', g.envs),
              FadeSwitcher(
                child: switch ((mcp, secrets)) {
                  (AsyncError(:final error), _) || (_, AsyncError(:final error)) =>
                    AppCard(key: const ValueKey('error'), child: Text('$error')),
                  (AsyncData(value: final a), AsyncData(value: final b)) when a.isEmpty && b.isEmpty => Padding(
                      key: const ValueKey('empty'),
                      padding: const EdgeInsets.only(top: Sp.x4),
                      child: StarterCard(
                        title: '接入更多服务',
                        text: '没有一键授权的服务，也能接进来：填一个 MCP 地址我就能用它的工具；存一个网站登录，我在云浏览器里替你登录；'
                            '存一个 API Key，我就能调用那个服务；存一个环境变量，你电脑上的程序就能读到它。',
                        starters: [
                          for (final k in addKinds) PillButton(label: k.label, icon: _addIcon(k.kind), onTap: () => _addKind(k.kind)),
                        ],
                      ),
                    ),
                  (AsyncData(), AsyncData()) => const SizedBox.shrink(key: ValueKey('done')),
                  _ => const SkeletonList(key: ValueKey('loading'), rows: 1),
                },
              ),
            ]),
          );
        },
      ),
    );
  }

  /// 唯一的添加入口：先问加什么，再弹那一类的表单。
  Future<void> _add() async {
    final kind = await showActionSheet<String>(context, title: '添加什么？', actions: [
      for (final k in addKinds) SheetAction(_addIcon(k.kind), '${k.label} · ${k.desc}', value: k.kind),
    ]);
    if (kind != null && mounted) await _addKind(kind);
  }

  Future<void> _addKind(String kind) => kind == 'mcp' ? _addMcp() : addSecret(context, ref, kind: kind);

  static IconData _addIcon(String kind) => kind == 'mcp' ? Icons.extension_outlined : secretKindIcon(kind);

  Future<void> _addMcp() async {
    final v = await showFormSheet(context, title: '添加 MCP 服务器', subtitle: '保存前我会先连一次，确认能用', submit: '连接', fields: const [
      FieldSpec('name', '名称', hint: '比如：Notion'),
      FieldSpec('url', '地址', hint: 'https://…/mcp', keyboard: TextInputType.url),
      FieldSpec('token', '访问令牌（可选）', obscure: true, required: false),
    ]);
    if (v == null || !mounted) return;
    try {
      final added = await ref.read(mcpServersProvider.notifier).create(v);
      if (mounted) showToast(context, withRetried('已连接 ${v['name']}', added.retriedNote));
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
    // 能画出来的行要么已连过、要么服务器配好了；只有“连过但服务器后来删了配置”时 authorizable 为假：照实说状态，不给按钮
    final can = c.authorizable;
    return FadeSlideIn(
      delay: delay,
      child: ListRow(
        icon: _icons[c.id] ?? Icons.link_rounded,
        title: c.name,
        subtitle: c.connected ? c.account : c.desc,
        problem: c.expired ? '授权失效' : null, // v2.36：失效的账户在这一行就说，点一下重新连接
        // 状态是小字，动作才是按钮：已连接 = 安静的说明；能连 = 墨色小胶囊“连接”
        trailing: SwapSwitcher(
          child: c.expired && can
              ? PillButton(key: const ValueKey('expired'), label: '重新连接', primary: true, dense: true, onTap: () => _connect(context, ref))
              : c.connected
              ? RowHint(c.expired ? '授权失效' : '已连接', key: const ValueKey('on'))
              : PillButton(key: const ValueKey('off'), label: '连接', primary: true, dense: true, onTap: () => _connect(context, ref)),
        ),
        onTap: () => c.connected ? _manage(context, ref) : _connect(context, ref),
      ),
    );
  }

  static const _icons = {'google': Icons.mail_outline_rounded, 'github': Icons.code_rounded};

  Future<void> _connect(BuildContext context, WidgetRef ref) => startConnect(context, ref, c.id);

  void _manage(BuildContext context, WidgetRef ref) => showActionSheet<void>(context, title: '${c.name} · ${c.account}', actions: [
        if (c.authorizable) SheetAction(Icons.refresh_rounded, '重新授权', onTap: () => _connect(context, ref)),
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
          child: ListRow(
            icon: Icons.extension_outlined,
            title: s.name,
            // 连不上 / 令牌被拒：副标题最前面说问题（只那几个字警示色），主页同时有一张“需要你亲自处理”的卡
            subtitle: hostOf(s.url),
            problem: s.problemText,
            trailing: SwapSwitcher(
              child: s.problemText != null
                  ? Icon(Icons.error_outline_rounded, key: const ValueKey('problem'), size: 20, color: context.palette.warning,
                      semanticLabel: s.problemText)
                  : (s.hasToken ? const RowHint('带令牌', key: ValueKey('token')) : const SizedBox.shrink(key: ValueKey('none'))),
            ),
            onTap: () => _showTools(context, ref),
          ),
        ),
      );

  Future<void> _showTools(BuildContext context, WidgetRef ref) async {
    final tools = ref.read(apiProvider).get('/api/connectors/mcp/${s.id}/tools');
    await showAppScrollSheet<void>(
      context,
      title: s.name,
      builder: (ctx) => FutureBuilder(
          future: tools,
          builder: (ctx, snap) {
            if (snap.hasError) return EmptyHint(icon: Icons.cloud_off_rounded, title: '无法连接', text: '${snap.error}');
            if (!snap.hasData) return const Padding(padding: EdgeInsets.all(Sp.x5), child: SkeletonList());
            final list = snap.data as List;
            return Column(mainAxisSize: MainAxisSize.min, children: [SheetList(padding: const EdgeInsets.only(bottom: Sp.x5), children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x5, Sp.x3),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${list.length} 个工具 · ${hostOf(s.url)}', style: ctx.text.labelSmall),
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
            ])]);
          },
        ),
    );
    // 打开工具列表 = 一次体检（后端据此放 / 收主页提醒）：关掉后刷新这一行的状态
    await tools.then((_) {}, onError: (_) {});
    if (context.mounted) await ref.read(mcpServersProvider.notifier).reload();
  }
}
