// “我的”里收拢几个入口的二级页（v2.81，docs/home-redesign.md B）：个人资料 = 记忆 + 技能；账户 = 连接器 + 保险箱。
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
  ]),
  accounts('账户', '我替你登录和调用的地方：一键授权的账号、MCP 服务器，以及加密保存的 API Key 和网站登录。', [
    (icon: Icons.hub_outlined, title: '连接的账号', to: '/me/connectors'),
    (icon: Icons.lock_outline_rounded, title: '密钥与网站登录', to: '/me/vault'),
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
