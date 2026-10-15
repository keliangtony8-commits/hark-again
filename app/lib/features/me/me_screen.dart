// 我的：点右上角头像进入的全屏页（v2.81 按 docs/home-redesign.md B 做减法，对照 Hark 个人页，一屏装下）。
// 从上到下：页头一行（返回钮 + 名字大字 / 服务器域名小字）→ 用量卡（本月花费 + 查看用量）
//   → 组 1：个人资料（记忆、技能）· 定时任务 · 账户（连接器、保险箱）· 钱包 · 我的电脑（状态、文件、Pages）
//   → 组 2：安全（两步验证、登录设备、服务器）· 偏好设置（外观、透明度、头像颜色、回复语言）· 反馈 · 关于
//   → 一颗“退出登录”胶囊。每行只有 图标 + 标题 + 箭头，说明都在子页顶部；路由在 app.dart，子页是 ui/sub_page.dart 的 SubPage。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/profile.dart';
import '../../core/session.dart';
import '../../models/usage.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../theme/look.dart';
import 'profile_sheet.dart';
import 'usage_screen.dart';
import '../../models/version.dart';

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
    final host = Uri.tryParse(server)?.host ?? '';
    final profile = ref.watch(profileProvider).value;
    const gap = SizedBox(height: Sp.x4);

    return PageBody(children: [
      // 页头一行：返回钮 + 名字/域名（不再单独占一行返回钮 + 一行页名，整页省出一屏）
      FadeSlideIn(
        child: Row(children: [
          root
              ? GlassIconButton(icon: Icons.close_rounded, tooltip: '回到主页', onTap: () => context.go('/home'))
              : GlassIconButton(icon: Icons.arrow_back_rounded, tooltip: '返回', onTap: () => Navigator.of(context).maybePop()),
          const SizedBox(width: Sp.x4),
          // v2.92 §P：头像 + 名字一起点 → 改称呼 / 助手名 / 头像
          Expanded(
            child: Pressable(
              key: const Key('me-identity'),
              onTap: profile == null ? null : () => showProfileSheet(context),
              scale: 0.98,
              child: Row(children: [
                if (profile != null) ...[
                  ExcludeSemantics(
                      child: Avatar(
                    initial: profile.initial,
                    image: profile.avatar == null ? null : ref.read(apiProvider).fileUrl(profile.avatar!),
                    color: ref.watch(lookProvider.select((l) => l.value?.avatar)),
                    onTap: null,
                    tooltip: '头像',
                  )),
                  const SizedBox(width: Sp.x3),
                ],
                Expanded(child: _Identity(name: profile?.name, host: host)),
              ]),
            ),
          ),
        ]),
      ),
      const SizedBox(height: Sp.x5),
      FadeSlideIn(delay: Motion.stagger(1), child: _UsageCard(report: ref.watch(usageProvider).value)),
      gap,
      FadeSlideIn(
        delay: Motion.stagger(2),
        child: ListGroup(children: [
          ListRow(icon: Icons.person_outline_rounded, title: '个人资料', onTap: () => context.push('/me/profile')),
          ListRow(icon: Icons.schedule_rounded, title: '定时任务', onTap: () => context.push('/me/tasks')),
          ListRow(icon: Icons.hub_outlined, title: '连接的账号', onTap: () => context.push('/me/connectors')),
          ListRow(icon: Icons.credit_card_rounded, title: '钱包', onTap: () => context.push('/me/wallet')),
          ListRow(icon: Icons.computer_rounded, title: '我的电脑', onTap: () => context.push('/me/computer')),
        ]),
      ),
      gap,
      FadeSlideIn(
        delay: Motion.stagger(3),
        child: ListGroup(children: [
          ListRow(icon: Icons.shield_outlined, title: '安全', onTap: () => context.push('/me/security')),
          ListRow(icon: Icons.tune_rounded, title: '偏好设置', onTap: () => context.push('/me/preferences')),
          ListRow(icon: Icons.feedback_outlined, title: '反馈', onTap: () => context.push('/me/feedback')),
          ListRow(icon: Icons.info_outline_rounded, title: '关于', value: clientOutdated(ref.watch(serverVersionProvider).value) ? '请更新' : null, onTap: () => context.push('/me/about')),
        ]),
      ),
      const SizedBox(height: Sp.x4),
      FadeSlideIn(
        delay: Motion.stagger(4),
        child: Center(
          child: PillButton(
            key: const Key('logout'),
            label: '退出登录',
            onTap: () async {
              if (await confirmDanger(context, title: '退出登录？', action: '退出')) await ref.read(sessionProvider.notifier).logout();
            },
          ),
        ),
      ),
    ]);
  }
}

/// 页头：名字大字 + 服务器域名小字（Hark 个人页：名字 + 邮箱，没有大头像）。名字没取到（加载中 / 老服务器）就写“我的”，取到后换态淡入；高度不变不跳版。
class _Identity extends StatelessWidget {
  const _Identity({required this.name, required this.host});
  final String? name;
  final String host;

  @override
  Widget build(BuildContext context) {
    final where = host.isEmpty ? '未设置服务器' : host;
    final n = name;
    return Semantics(
      label: n == null ? '服务器 $where' : '已登录 $n，服务器 $where',
      excludeSemantics: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SwapSwitcher(child: Text(n ?? '我的', key: ValueKey(n ?? ''), style: context.text.displayMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
        const SizedBox(height: Sp.x1),
        Text(where, style: context.text.bodyMedium?.copyWith(color: context.palette.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
      ]),
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
              // 一行：“本月 ¥12.30”（像 Hark 方案卡左边一行字）；有预算才多一行小字
              Semantics(
                label: '本月花费 $value',
                excludeSemantics: true,
                child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                  Text('本月', style: context.text.bodyMedium?.copyWith(color: p.text3)),
                  const SizedBox(width: Sp.x2),
                  Flexible(child: CountUp(value, style: context.text.titleLarge)),
                ]),
              ),
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
