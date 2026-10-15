// 我的：点右上角头像进入的全屏页（v2.81 按 docs/home-redesign.md B 做减法，对照 Hark 个人页，一屏装下）。
// 从上到下：页头一行（返回钮 + 名字大字 / 服务器域名小字）→ 用量卡（本月花费 + 查看用量）
//   → 组 1：个人资料（记忆、技能）· 定时任务 · 连接的账号 · 钱包 · 我的电脑（状态、文件、Pages）
//   → 组 2：安全（两步验证、登录设备）· 偏好设置（外观、透明度、头像颜色、回复语言）· 反馈 · 关于
//   → 一颗“退出登录”胶囊。每行只有 图标 + 标题 + 箭头，说明都在子页顶部；路由在 app.dart，子页是 ui/sub_page.dart 的 SubPage。
// v3.0：底部一颗玻璃搜索胶囊 = 全 App 唯一的设置搜索（索引 me_index.dart；对话在历史抽屉里搜）。输入即筛：页头保留，
//   下面换成结果（分区图标 + 标亮标题 + 所在位置），点了直达，带定位 id 的进页后滚到那一项闪一下（ui/kit.dart Spotlight）。
//   胶囊放在 FloatingFooter 里：它量出胶囊实高交给 PageBody 留白，滚到底“退出登录”不会被挡住。
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
import 'me_index.dart';
import 'profile_sheet.dart';
import 'usage_screen.dart';
import '../../models/version.dart';

class MeScreen extends ConsumerStatefulWidget {
  const MeScreen({super.key});

  @override
  ConsumerState<MeScreen> createState() => _MeScreenState();
}

class _MeScreenState extends ConsumerState<MeScreen> {
  final _search = TextEditingController();
  final _focus = FocusNode();
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _clear() {
    _search.clear();
    setState(() => _query = '');
  }

  void _open(MeEntry e) {
    _focus.unfocus();
    context.push(e.location);
  }

  @override
  Widget build(BuildContext context) {
    // 通常是从头像 push 进来，返回即回去；深链（OAuth 回调）直接落在 /me/… 时栈底就是这里，返回改去主页而不是退出 App
    final root = ModalRoute.of(context)?.isFirst ?? false; // 按“本页在导航栈底”判断（context.canPop 看的是整个路由器，上面压着子页时也为真）
    final searching = _query.trim().isNotEmpty;
    return PopScope(
      canPop: !root && !searching, // 搜着的时候返回键先清空搜索（= iOS 设置搜索的“取消”）
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        if (searching) {
          _clear();
        } else {
          context.go('/home');
        }
      },
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: Backdrop(
          child: FloatingFooter(
            footer: _SearchBar(
              controller: _search,
              focusNode: _focus,
              onChanged: (v) => setState(() => _query = v),
              onClear: _clear,
              onSubmitted: (v) {
                final hits = searchMe(v);
                if (hits.isNotEmpty) _open(hits.first); // 回车 = 打开第一条
              },
            ),
            child: _MeBody(root: root, query: _query, onOpen: _open),
          ),
        ),
      ),
    );
  }
}

/// 底部搜索胶囊：和主页输入胶囊同一位置、同一玻璃材质（GlassSurface blur），单行所以是全圆角药丸。
class _SearchBar extends StatelessWidget {
  const _SearchBar({required this.controller, required this.focusNode, required this.onChanged, required this.onClear, required this.onSubmitted});
  final TextEditingController controller;
  final FocusNode focusNode;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;
  final ValueChanged<String> onSubmitted;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x2, Sp.x3, Sp.x3),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: Layout.contentMax),
              child: GlassSurface(
                key: const Key('me-search'),
                blur: true,
                radius: Radii.full,
                child: SearchField(
                  controller: controller,
                  focusNode: focusNode,
                  hint: '搜索设置',
                  floating: true,
                  onChanged: onChanged,
                  onClear: onClear,
                  onSubmitted: onSubmitted,
                ),
              ),
            ),
          ),
        ),
      );
}

class _MeBody extends ConsumerWidget {
  const _MeBody({required this.root, required this.query, required this.onOpen});
  final bool root;
  final String query;
  final ValueChanged<MeEntry> onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(sessionProvider).value?.server ?? '';
    final host = Uri.tryParse(server)?.host ?? '';
    final profile = ref.watch(profileProvider).value;
    final hits = searchMe(query);
    final searching = query.trim().isNotEmpty;

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
      // 原页面 ↔ 搜索结果 ↔ 没找到：三态交叉淡化；同一态里随输入更新不再过渡（key 只随态变）
      FadeSwitcher(
        child: !searching
            ? const _MeHome(key: ValueKey('home'))
            : hits.isEmpty
                ? const EmptyHint(
                    key: ValueKey('none'),
                    icon: Icons.search_off_rounded,
                    title: '没有找到相关设置',
                    text: '换个说法试试；要找聊天内容，请在历史记录里搜索。',
                  )
                : _MeResults(key: const ValueKey('hits'), query: query, hits: hits, onOpen: onOpen),
      ),
    ]);
  }
}

/// 没在搜索时的“我的”：用量卡 → 两组行 → 退出登录。
class _MeHome extends ConsumerWidget {
  const _MeHome({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    const gap = SizedBox(height: Sp.x4);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
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

/// 搜索结果：一组行，行首 = 所在分区的图标，标题里命中的词标亮，副标题 = 在哪（像 iOS 设置搜索的路径）。
class _MeResults extends StatelessWidget {
  const _MeResults({super.key, required this.query, required this.hits, required this.onOpen});
  final String query;
  final List<MeEntry> hits;
  final ValueChanged<MeEntry> onOpen;

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SectionTitle('搜索结果', count: hits.length), // 上距 = 区块间距，和原页面页头到用量卡同一节奏
        ListGroup(children: [
          for (final e in hits)
            ListRow(
              key: ValueKey('hit-${e.id}'),
              icon: e.section.icon,
              title: e.title,
              titleWidget: HighlightText(e.title, query: query, style: context.text.bodyLarge),
              subtitle: e.where,
              semanticLabel: '${e.title}，在${e.where}',
              onTap: () => onOpen(e),
            ),
        ]),
      ]);
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
