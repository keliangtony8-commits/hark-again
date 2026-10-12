// 我的 → 我的电脑（v1.25）：个人工作区（主聊天和定时任务用的那台云端 Linux）的状态页。
// 页头一句说明 → “状态”一节（ComputerSection：运行/休眠、内存、磁盘、正在跑的后台任务、重启）→ 文件入口
// → “浏览器登录”（v1.26 BrowserSessionsSection：按网站保存的登录，可退出）。下拉刷新两处一起刷。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/workspace.dart';
import '../../models/computer.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';
import '../projects/project_files_sheet.dart';
import 'browser_sessions_section.dart';
import 'computer_section.dart';

class ComputerScreen extends ConsumerWidget {
  const ComputerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(computerProvider(personalWorkspace));
    return SubPage(
      title: const Text('我的电脑'),
      body: PullRefresh(
        onRefresh: () => Future.wait([
          ref.read(computerProvider(personalWorkspace).notifier).reload(),
          ref.read(browserSessionsProvider.notifier).reload(),
        ]),
        child: PageBody(children: [
          PageIntro(
            summary: s.value == null ? (s.hasError ? '暂时看不到状态' : '正在查看…') : computerStateLabel(s.value!.state),
            line: '主聊天和定时任务用的云端 Linux：我在这里跑代码、装软件、做后台任务，产物放进“我的文件”。',
          ),
          const ComputerSection(ws: personalWorkspace, title: '状态'),
          FadeSlideIn(
            delay: Motion.stagger(1),
            child: Column(children: [
              const SectionTitle('文件'),
              GlassGroup(children: [
                RowTile(
                  icon: Icons.folder_outlined,
                  title: workspaceFilesTitle(personalWorkspace),
                  subtitle: '这台电脑上的文件，我做出来的也在这',
                  onTap: () => showProjectFiles(context, personalWorkspace),
                ),
              ]),
            ]),
          ),
          BrowserSessionsSection(delay: Motion.stagger(2)),
        ]),
      ),
    );
  }
}
