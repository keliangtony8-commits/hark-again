// “为你准备”里的一张主动建议卡：标题 + 内容块 + 一排等宽胶囊（忽略 / [去处] / 去做，最后一个是主按钮）。
// 去处（HomeCard.target）是服务端说“这件事在客户端的哪一页看”，比如预算提醒 → 用量页。值 = 名字 或 名字:id
// （规则见后端 app/card_targets.py）。route 里的 {task} 换成卡上的 task_id（任务失败提醒 → 那个任务的详情），
// {id} 换成值里冒号后的 id（project:<id> → 那个项目）；缺了就退到列表页。
// 卡可以只有去处没有指令（重新连接账号这类只能本人做的事；系统提醒“连接已失效”也是）：眉题“需要你亲自处理”，
// 去处按钮是主按钮。眉题规则只在 cardEyebrow 一处（网页版 lib/cardTargets.ts cardEyebrow 同规则）。
// 标题右边一个“稍后提醒”小钮（features/home/card_snooze.dart）：先收起，到点再放回。
// 助手提议的卡（card.offered）：标题上方一行“可以替你做”，主按钮用卡上的字（actionText）。点了走 startOffer：
// 服务端开新对话并记在卡上，App 打开它并发指令；卡留在主页变成“已交给助手”（card.started），主按钮“查看对话”回到那段，
// 次按钮“收起”。系统提醒点“去做”直接把指令发进新对话（onDo），不收起（恢复后服务端自己收起）。
// 建议卡可带配图（card.imageUrl：卡顶一张宽图，淡入）和原页（card.linkUrl：正文下“来源 · 域名 ↗”，点图也去原页）。
// 映射只在 cardTargets 一处；不认识的值当没有（老 App 遇到新服务端不出错）。网页版 lib/cardTargets.ts 同一张表。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../blocks/block_view.dart';
import '../../blocks/content_blocks.dart';
import '../../core/links.dart';
import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import 'card_snooze.dart';
import 'inbox.dart';

typedef CardTarget = ({String label, IconData icon, String route});

// 图标与“我的”页各入口一致，用户认得出要去哪儿
const cardTargets = <String, CardTarget>{
  'usage': (label: '查看用量', icon: Icons.data_usage_rounded, route: '/me/usage'),
  'tasks': (label: '查看任务', icon: Icons.event_repeat_rounded, route: '/me/tasks/{task}'),
  'memory': (label: '打开记忆', icon: Icons.psychology_outlined, route: '/me/memory'),
  'skills': (label: '打开技能', icon: Icons.auto_awesome_outlined, route: '/me/skills'),
  'connectors': (label: '去连接器', icon: Icons.hub_outlined, route: '/me/connectors'),
  'vault': (label: '打开保险箱', icon: Icons.lock_outline_rounded, route: '/me/vault'),
  'pages': (label: '查看网页', icon: Icons.web_rounded, route: '/me/pages'),
  'project': (label: '打开项目', icon: Icons.folder_outlined, route: '/projects/{id}'),
};

/// 'project:abc' → ('project', 'abc')；'usage' → ('usage', null)。
(String, String?) splitTarget(String value) {
  final i = value.indexOf(':');
  if (i < 0) return (value, null);
  final arg = value.substring(i + 1).trim();
  return (value.substring(0, i), arg.isEmpty ? null : arg);
}

CardTarget? cardTarget(String? id) => id == null ? null : cardTargets[splitTarget(id).$1];

/// 打开某段对话，send 非空就在打开后发出去（主页传 openConversation）；projectId = 卡指向的项目（`project:<id>`），
/// v2.95 起服务器把指令发进那个项目的那段对话，客户端要切到那个项目里打开。
typedef OpenConversation = void Function(String conversationId, String? send, {String? projectId});

/// 点助手建议卡的主按钮（开始做 / 查看对话）的唯一入口。服务端说 started 才发指令，所以重复点不会重发。
/// 卡已经不在（404 等）→ 只刷新列表。先拿到 notifier 再跳走：跳转后这张卡的 context 可能失效。
Future<void> startOffer(WidgetRef ref, HomeCard card, OpenConversation open) async {
  final api = ref.read(apiProvider), cards = ref.read(cardsProvider.notifier), inbox = ref.read(inboxProvider.notifier);
  try {
    final j = await api.post('/api/cards/${card.id}/start') as Map<String, dynamic>;
    final (kind, arg) = splitTarget(card.target ?? '');
    open(j['conversation_id'] as String, j['started'] == true ? j['prompt'] as String? : null, projectId: kind == 'project' ? arg : null);
  } catch (_) {
    await cards.reload();
    return;
  }
  await cards.reload();
  await inbox.refresh();
}

/// 标题上方那行小字：已开始 → 已交给助手；助手提议且能替你做 → 可以替你做；
/// 没有指令只有去处（助手提议或系统提醒，如“连接已失效”）→ 需要你亲自处理；其余（普通系统提醒）没有。
String? cardEyebrow(HomeCard card, CardTarget? target) {
  if (card.started) return '已交给助手 · 查看进展';
  if (card.actionPrompt == null) return target != null ? '需要你亲自处理' : null;
  return card.offered ? '可以替你做' : null;
}

/// 去处的真实路由：{task} ← card.taskId，{id} ← target 里冒号后的 id；缺哪个就连同前面的 / 一起去掉（退到列表）。
String cardRoute(CardTarget t, HomeCard card) {
  final slots = {'task': card.taskId, 'id': card.target == null ? null : splitTarget(card.target!).$2};
  var route = t.route;
  slots.forEach((name, v) {
    route = v == null ? route.replaceAll('/{$name}', '') : route.replaceAll('{$name}', Uri.encodeComponent(v));
  });
  return route;
}

class ActionCard extends ConsumerWidget {
  const ActionCard({super.key, required this.card, required this.onDo, required this.onOpen});
  final HomeCard card;
  final void Function(String) onDo;
  final OpenConversation onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final target = cardTarget(card.target);

    Future<void> dismiss() async {
      await ref.read(cardsProvider.notifier).patch(card.id, {'dismissed': true});
      await ref.read(inboxProvider.notifier).refresh(); // 忽略的卡不再算未读
    }

    void open(CardTarget t) {
      if (card.unread) ref.read(inboxProvider.notifier).markRead([card.id]).ignore();
      // “我的”下的去处盖在外壳上（push），返回回到主页；聊天等 Tab 内去处直接切过去
      final route = cardRoute(t, card);
      route.startsWith('/me') ? context.push(route) : context.go(route);
    }

    void doIt() => card.offered ? startOffer(ref, card, onOpen) : onDo(card.actionPrompt!);

    // 按钮一排等宽：忽略（开始后叫“收起”）永远是次按钮；有“去做”时它是主按钮，否则去处是主按钮
    final started = card.started;
    final eyebrow = cardEyebrow(card, target);
    final buttons = <Widget>[
      PillButton(label: started ? '收起' : '忽略', onTap: dismiss),
      if (target != null) PillButton(label: target.label, icon: target.icon, primary: card.actionPrompt == null, onTap: () => open(target)),
      if (card.actionPrompt != null)
        PillButton(
            label: started ? '查看对话' : card.actionText,
            icon: started ? Icons.forum_rounded : null,
            primary: true,
            onTap: doIt),
    ];
    // 稍后钮是小图标，可点区域仍 ≥ A11y.minTap；用负边距把它的空白吃进卡片内边距，标题行不被撑高
    return Padding(
      padding: const EdgeInsets.only(bottom: Layout.cardGap),
      child: GlassCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (card.imageUrl != null) ...[OfferImage(card: card), const SizedBox(height: Sp.x3)],
          Row(children: [
            PopSwitcher(
              child: IconBadge(key: ValueKey(started), target?.icon ?? (started ? Icons.forum_rounded : Icons.auto_awesome_rounded)),
            ),
            const SizedBox(width: Sp.x3),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                if (eyebrow != null)
                  SwapSwitcher(
                    child: Text(eyebrow,
                        key: ValueKey(eyebrow), style: context.text.labelSmall?.copyWith(color: context.palette.text3)),
                  ),
                Text(card.title, style: context.text.titleMedium),
              ]),
            ),
            Transform.translate(
              offset: const Offset(Sp.x3, 0),
              child: IconButton(
                onPressed: () => showSnoozeSheet(context, ref, card),
                tooltip: '稍后提醒',
                icon: Icon(Icons.snooze_rounded, size: Fs.lg, color: context.palette.text3),
              ),
            ),
          ]),
          if (card.blocks.isNotEmpty) ...[const SizedBox(height: Sp.x3), BlockList(card.blocks)],
          // 来源行自带 ≥ minTap 的可点高度（字上下各有留白），前后只补 Sp.x1，别再叠一个 Sp.x4 撑出空洞
          if (card.linkHost != null) ...[const SizedBox(height: Sp.x1), OfferSource(card: card), const SizedBox(height: Sp.x1)]
          else const SizedBox(height: Sp.x4),
          Row(children: [
            for (var i = 0; i < buttons.length; i++) ...[
              if (i > 0) const SizedBox(width: Sp.x2),
              Expanded(child: buttons[i]),
            ],
          ]),
        ]),
      ),
    );
  }
}

/// 配图宽高比：窗口宽到阅读宽度上限（电脑 / 平板）就用更扁的 5:2，和网页同一断点（Layout.contentMax = 720）。
double offerImageRatioFor(double windowWidth) => windowWidth >= Layout.contentMax ? Layout.offerImageRatioWide : Layout.offerImageRatio;

/// 建议卡顶部配图：宽图圆角，加载完淡入，打不开显示占位；有原页时点图去原页。
class OfferImage extends StatelessWidget {
  const OfferImage({super.key, required this.card});
  final HomeCard card;

  @override
  Widget build(BuildContext context) {
    final image = ClipRRect(
      borderRadius: BorderRadius.circular(Radii.inner),
      child: AspectRatio(aspectRatio: offerImageRatioFor(MediaQuery.sizeOf(context).width), child: NetImage(card.imageUrl!)),
    );
    final link = card.linkUrl;
    return link == null
        ? Semantics(image: true, label: card.title, child: image)
        : Pressable(onTap: () => openUrl(link), semanticLabel: '打开原页 ${card.linkHost}', child: image);
  }
}

/// 正文下一行“来源 · 域名 ↗”：安静的小字，点了用浏览器打开原页。
class OfferSource extends StatelessWidget {
  const OfferSource({super.key, required this.card});
  final HomeCard card;

  @override
  Widget build(BuildContext context) {
    final style = context.text.labelSmall?.copyWith(color: context.palette.text3);
    return Pressable(
      onTap: () => openUrl(card.linkUrl!),
      semanticLabel: '打开原页 ${card.linkHost}',
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: A11y.minTap),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Flexible(child: Text('来源 · ${card.linkHost}', style: style, maxLines: 1, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: Sp.x1),
          Icon(Icons.north_east_rounded, size: Fs.sm, color: context.palette.text3),
        ]),
      ),
    );
  }
}
