// 关于（v2.81，对标 Hark 我的 → 关于）：这是什么、版本、连的哪台服务器、开源许可。一组行，没有别的。
// v2.86：名字和版本只来自 lib/brand.dart（brand/sync.py 由 brand/brand.json + VERSION 生成），不再靠编译参数；
// 服务器版本取 GET /api/version，单独一行，部署落后时一眼看出；低于服务器要求的最低版本时“版本”行写“请更新”。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../brand.dart';
import '../../core/session.dart';
import '../../models/version.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';

class AboutScreen extends ConsumerWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(sessionProvider).value?.server ?? '';
    final host = Uri.tryParse(server)?.host ?? '';
    final sv = ref.watch(serverVersionProvider).value;
    return SubPage(
      title: const Text('关于'),
      body: PageBody(children: [
        const PageIntro(line: '$appName 是你自己的私人助手：运行在你自己的服务器上，用你自己的模型密钥，数据只在那里。'),
        FadeSlideIn(
          delay: Motion.stagger(1),
          child: ListGroup(children: [
            ListRow(icon: Icons.tag_rounded, title: '版本', value: clientVersionLabel(sv)),
            ListRow(icon: Icons.dns_outlined, title: '服务器', value: host.isEmpty ? '未设置' : host),
            if (sv != null) ListRow(icon: Icons.update_rounded, title: '服务器版本', value: sv.version),
            ListRow(
              icon: Icons.description_outlined,
              title: '开源许可',
              onTap: () => showLicensePage(context: context, applicationName: appName, applicationVersion: '$appVersion ($appBuild)'),
            ),
          ]),
        ),
      ]),
    );
  }
}
