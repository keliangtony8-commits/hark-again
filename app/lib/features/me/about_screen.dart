// 关于（v2.81，对标 Hark 我的 → 关于）：这是什么、版本、连的哪台服务器、开源许可。一组行，没有别的。
// v2.86：名字和版本只来自 lib/brand.dart（brand/sync.py 由 brand/brand.json + VERSION 生成），不再靠编译参数；
// 服务器版本取 GET /api/version，单独一行，部署落后时一眼看出；低于服务器要求的最低版本时“版本”行写“请更新”。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../brand.dart';
import '../../core/perf_overlay.dart';
import '../../core/session.dart';
import '../../models/version.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';
import 'perf_probe_screen.dart';

class AboutScreen extends ConsumerStatefulWidget {
  const AboutScreen({super.key});

  @override
  ConsumerState<AboutScreen> createState() => _AboutScreenState();
}

class _AboutScreenState extends ConsumerState<AboutScreen> {
  final _streak = TapStreak(); // v3.5.2 连点“版本”5 次 = 隐藏的性能浮层开关（core/perf_overlay.dart）

  @override
  void dispose() {
    _streak.dispose();
    super.dispose();
  }

  Future<void> _tapVersion() async {
    if (!_streak.tap()) return;
    final on = await ref.read(perfOverlayProvider.notifier).toggle();
    if (mounted) showToast(context, on ? '性能浮层已打开，再连点 5 次关闭' : '性能浮层已关闭');
  }

  @override
  Widget build(BuildContext context) {
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
            Spotlight(
              id: 'version',
              row: true,
              // 不给 ListRow onTap：那会多一个箭头、像能点进去；这是隐藏开关
              child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: _tapVersion, child: ListRow(icon: Icons.tag_rounded, title: '版本', value: clientVersionLabel(sv))),
            ),
            // v3.5.3 性能自检（features/me/perf_probe_screen.dart）：只在性能浮层打开时出现，紧跟“版本”这个开关
            if (ref.watch(perfOverlayProvider).value ?? false)
              ListRow(key: const Key('perf-probe'), icon: Icons.speed_rounded, title: '性能自检', onTap: () => startPerfProbe(context)),
            ListRow(icon: Icons.dns_outlined, title: '服务器', value: host.isEmpty ? '未设置' : host),
            if (sv != null) ListRow(icon: Icons.update_rounded, title: '服务器版本', value: sv.version),
            const ListRow(icon: Icons.text_fields_rounded, title: '字体', value: 'MiSans（小米）'), // MiSans 许可要求在软件中注明（= 网页 AboutScreen）
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
