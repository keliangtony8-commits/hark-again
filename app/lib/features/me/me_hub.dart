// “我的”里收拢几个入口的二级页（v2.81，docs/home-redesign.md B）：个人资料 = 记忆 + 技能。
// （v2.96 “账户”收拢页删除：连接器与保险箱合成“连接的账号”一页，“我的”直达。）
// 只有 页头一句说明 + 一组行，行里没有副标题——说明写在这一页顶部一次。原来的子页（/me/memory 等）原样保留，深链照常能开。
// 新加一个收拢页 = 在 MeHub 里加一个值，不另写页面。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';

typedef HubRow = ({IconData icon, String title, String to});

enum MeHub {
  profile('个人资料', '我记住的你，和教我做事的方法。', [
    (icon: Icons.psychology_outlined, title: '记忆', to: '/me/memory'),
    (icon: Icons.auto_awesome_outlined, title: '技能', to: '/me/skills'),
  ]);

  const MeHub(this.title, this.line, this.rows);
  final String title, line;
  final List<HubRow> rows;
}

class MeHubScreen extends StatelessWidget {
  const MeHubScreen({super.key, required this.hub});
  final MeHub hub;

  @override
  Widget build(BuildContext context) => SubPage(
        title: Text(hub.title),
        body: PageBody(children: [
          SubPageLine(hub.line),
          FadeSlideIn(
            delay: Motion.stagger(1),
            child: GlassGroup(children: [
              for (final r in hub.rows) RowTile(icon: r.icon, title: r.title, onTap: () => context.push(r.to)),
            ]),
          ),
        ]),
      );
}
