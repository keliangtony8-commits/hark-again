// 我的：点右上角头像进入的全屏页（设计 v2）。不是 Tab，没有 AppBar——和一级页面同一张壁纸、同一套玻璃。
// 从上到下：返回钮 → 页头（大头像，点它改颜色；衬线“我的” + 服务器）→ 用量卡（本月花费 / 预算 + 查看用量）
//   → 分组卡：了解你（记忆、技能、定时任务）· 连接（连接器、保险箱、Pages）· 外观与偏好（浅深色、减少透明度、头像颜色）
//   → 服务器 → 单独一行“退出登录”。页头身份行：用户名（GET /api/auth/me，取到后淡入）+ 服务器域名。每项一个子页面，路由在 app.dart（子页面是 ui/sub_page.dart 的 SubPage：同一张壁纸 + 玻璃标题栏）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/session.dart';
import '../../models/usage.dart';
import '../../theme/app_theme.dart';
import '../../theme/appearance.dart';
import '../../theme/look.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'avatar_color_sheet.dart';
import 'usage_screen.dart';

class MeScreen extends ConsumerWidget {
  const MeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // 通常是从头像 push 进来，返回即回去；深链（OAuth 回调）直接落在 /me/… 时栈底就是这里，返回改去主页而不是退出 App
    final root = ModalRoute.of(context)?.isFirst ?? false; // 按“本页在导航栈底”判断（context.canPop 看的是整个路由器，上面压着子页时也为真）
    return PopScope(
      canPop: !root,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) context.go('/home');
      },
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: Backdrop(child: _MeBody(root: root)),
      ),
    );
  }
}

class _MeBody extends ConsumerWidget {
  const _MeBody({required this.root});
  final bool root;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(sessionProvider).value?.server ?? '';
    final appearance = ref.watch(appearanceProvider).value ?? Appearance.system;
    final look = ref.watch(lookProvider).value ?? const Look();
    final host = Uri.tryParse(server)?.host ?? '';
    const gap = SizedBox(height: Sp.x4);

    return PageBody(children: [
      Align(
        alignment: Alignment.centerLeft,
        child: root
            ? GlassIconButton(icon: Icons.close_rounded, tooltip: '回到主页', onTap: () => context.go('/home'))
            : GlassIconButton(icon: Icons.arrow_back_rounded, tooltip: '返回', onTap: () => Navigator.of(context).maybePop()),
      ),
      const SizedBox(height: Sp.x5),
      FadeSlideIn(
        child: Row(children: [
          Avatar(initial: '我', size: Layout.avatarLarge, color: look.avatar, tooltip: '更换头像颜色', onTap: () => showAvatarColorSheet(context)),
          const SizedBox(width: Sp.x4),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('我的', style: context.text.displayMedium),
              const SizedBox(height: Sp.x1),
              _Identity(name: ref.watch(accountNameProvider).value, host: host),
            ]),
          ),
        ]),
      ),
      const SizedBox(height: Sp.x5),
      FadeSlideIn(delay: Motion.stagger(1), child: _UsageCard(report: ref.watch(usageProvider).value)),
      gap,
      FadeSlideIn(
        delay: Motion.stagger(2),
        child: GlassGroup(children: [
          RowTile(icon: Icons.psychology_outlined, title: '记忆', subtitle: '我记住的偏好和事实', onTap: () => context.push('/me/memory')),
          RowTile(icon: Icons.auto_awesome_outlined, title: '技能', subtitle: '教我做事的固定方法', onTap: () => context.push('/me/skills')),
          RowTile(icon: Icons.schedule_rounded, title: '定时任务', subtitle: '简报、提醒和面板刷新', onTap: () => context.push('/me/tasks')),
        ]),
      ),
      gap,
      FadeSlideIn(
        delay: Motion.stagger(3),
        child: GlassGroup(children: [
          RowTile(icon: Icons.hub_outlined, title: '连接器', subtitle: 'Google、GitHub 和 MCP 服务器', onTap: () => context.push('/me/connectors')),
          RowTile(icon: Icons.lock_outline_rounded, title: '保险箱', subtitle: 'API Key 和网站登录，加密保存', onTap: () => context.push('/me/vault')),
          RowTile(icon: Icons.computer_rounded, title: '我的电脑', subtitle: '云端 Linux 的状态、后台任务和文件', onTap: () => context.push('/me/computer')),
          RowTile(icon: Icons.web_rounded, title: 'Pages', subtitle: '我为你做好并发布的网页', onTap: () => context.push('/me/pages')),
        ]),
      ),
      const SectionTitle('外观与偏好'),
      FadeSlideIn(
        delay: Motion.stagger(4),
        child: GlassGroup(children: [
          Padding(
            padding: const EdgeInsets.all(Sp.x3),
            child: SegmentedButton<Appearance>(
              key: const Key('appearance'),
              showSelectedIcon: false,
              segments: [for (final a in Appearance.values) ButtonSegment(value: a, label: Text(a.label), icon: Icon(a.icon, size: 18))],
              selected: {appearance},
              onSelectionChanged: (s) => ref.read(appearanceProvider.notifier).set(s.first),
            ),
          ),
          RowTile(
            icon: Icons.blur_off_rounded,
            title: '减少透明度',
            subtitle: '玻璃和壁纸换成实色，也更省电',
            trailing: Switch(key: const Key('solid'), value: look.solid, onChanged: (v) => ref.read(lookProvider.notifier).setSolid(v)),
          ),
          RowTile(
            icon: Icons.palette_outlined,
            title: '头像颜色',
            trailing: Avatar(initial: '', onTap: null, size: Sp.x5, color: look.avatar, tooltip: '当前头像颜色'),
            onTap: () => showAvatarColorSheet(context),
          ),
        ]),
      ),
      gap,
      FadeSlideIn(
        delay: Motion.stagger(5),
        child: GlassGroup(children: [
          RowTile(icon: Icons.dns_outlined, title: '服务器', subtitle: server.isEmpty ? '未设置' : '$server · 退出后可在登录页更换'),
        ]),
      ),
      gap,
      FadeSlideIn(
        delay: Motion.stagger(6),
        child: GlassGroup(children: [
          RowTile(
            icon: Icons.logout_rounded,
            title: '退出登录',
            trailing: const SizedBox.shrink(),
            onTap: () async {
              if (await confirmDanger(context, title: '退出登录？', action: '退出')) await ref.read(sessionProvider.notifier).signOut();
            },
          ),
        ]),
      ),
    ]);
  }
}

/// 页头身份行：“用户名 · 域名”。用户名没取到（加载中 / 老服务器）只显示域名；取到后整行换态淡入，不跳版（高度一行）。
class _Identity extends StatelessWidget {
  const _Identity({required this.name, required this.host});
  final String? name;
  final String host;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final where = host.isEmpty ? '未设置服务器' : host;
    final n = name;
    return SwapSwitcher(
      child: Text.rich(
        key: ValueKey(n ?? ''),
        TextSpan(children: [
          if (n != null) ...[
            TextSpan(text: n, style: context.text.titleSmall?.copyWith(color: p.text)),
            TextSpan(text: '  ·  ', style: context.text.bodySmall?.copyWith(color: p.text3)),
          ],
          TextSpan(text: where, style: context.text.bodySmall),
        ]),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        semanticsLabel: n == null ? '服务器 $where' : '已登录 $n，服务器 $where',
      ),
    );
  }
}

/// 用量卡：本月花了多少（没配单价就是 token 数）、预算多少、离预算多近（细条），右边“查看用量”。
class _UsageCard extends StatelessWidget {
  const _UsageCard({required this.report});
  final UsageReport? report;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = report;
    final value = r == null ? '—' : (r.priced.isEmpty ? '${formatTokens(r.month.tokens)} token' : formatMoney(r.month.cost, r.currency));
    final ratio = r?.budgetRatio;
    return GlassCard(
      onTap: () => context.push('/me/usage'),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('本月花费', style: context.text.bodySmall),
              Semantics(label: '本月花费 $value', excludeSemantics: true, child: CountUp(value, style: context.text.displaySmall)),
              if (r?.budget != null) Text('预算 ${formatMoney(r!.budget!, r.currency)}', style: context.text.labelSmall),
            ]),
          ),
          const SizedBox(width: Sp.x3),
          PillButton(label: '查看用量', primary: true, onTap: () => context.push('/me/usage')),
        ]),
        if (ratio != null) ...[
          const SizedBox(height: Sp.x3),
          MeterBar(value: ratio.clamp(0, 1).toDouble(), color: budgetColor(p, r!.level)),
        ],
      ]),
    );
  }
}
