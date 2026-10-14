// 关于（v2.81，对标 Hark 我的 → 关于）：这是什么、连的哪台服务器、开源许可。一组行，没有别的。
// 版本号来自编译参数 APP_VERSION（CI 打包时 --dart-define=APP_VERSION=vX.Y），没传就不显示那一行。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';

const appVersion = String.fromEnvironment('APP_VERSION');

class AboutScreen extends ConsumerWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(sessionProvider).value?.server ?? '';
    final host = Uri.tryParse(server)?.host ?? '';
    return SubPage(
      title: const Text('关于'),
      body: PageBody(children: [
        const SubPageLine('你自己的私人助手：跑在你自己的服务器上，用你自己的模型密钥，数据只在那里。'),
        FadeSlideIn(
          delay: Motion.stagger(1),
          child: GlassGroup(children: [
            if (appVersion.isNotEmpty) RowTile(icon: Icons.tag_rounded, title: '版本', value: appVersion),
            RowTile(icon: Icons.dns_outlined, title: '服务器', value: host.isEmpty ? '未设置' : host),
            RowTile(
              icon: Icons.description_outlined,
              title: '开源许可',
              onTap: () => showLicensePage(context: context, applicationName: '助手', applicationVersion: appVersion.isEmpty ? null : appVersion),
            ),
          ]),
        ),
      ]),
    );
  }
}
