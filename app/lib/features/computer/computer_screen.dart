// 电脑详情页：我的 → 我的电脑（个人工作区，v1.25）和项目首屏点“电脑”进来的 /projects/<id>/computer（v1.27）共用。
// 页头一句说明 → “状态”（ComputerSection：运行/休眠、CPU/内存、内存打满警示、后台任务、重启；运行中一直刷新）
// → “正在监听的端口”（PortsSection，v1.30：点一下预览网页）→ “正在运行的程序”（ProcessSection）→ “磁盘”（StorageSection：按用途拆开、点“文件”开文件弹层、装过的工具、清理）
// → 个人电脑才有的“浏览器登录”（v1.26 BrowserSessionsSection）和“服务器主机”（v1.49 HostSection：主机模式开关 + 以后都允许的命令）。下拉刷新一起刷。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/workspace.dart';
import '../../models/computer.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../projects/project_files_sheet.dart';
import 'browser_sessions_section.dart';
import 'computer_details.dart';
import 'computer_section.dart';
import 'host_section.dart';

class ComputerScreen extends ConsumerWidget {
  const ComputerScreen({super.key, this.ws = personalWorkspace});
  final String ws;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(computerProvider(ws));
    final personal = isPersonalWorkspace(ws);
    return SubPage(
      title: Text(personal ? '我的电脑' : '项目的电脑'),
      body: PullRefresh(
        onRefresh: () => Future.wait([
          ref.read(computerProvider(ws).notifier).reload(),
          if (personal) ref.read(browserSessionsProvider.notifier).reload(),
          if (personal) ref.read(hostProvider.notifier).reload(),
        ]),
        child: PageBody(children: [
          PageIntro(
            summary: s.value == null ? (s.hasError ? '暂时看不到状态' : '正在查看…') : computerStateLabel(s.value!.state),
            line: personal
                ? '主聊天和定时任务用的云端 Linux：我在这里跑代码、装软件、做后台任务，产物放进“我的文件”。'
                : '这个项目专用的云端 Linux：项目里的对话都在这里跑代码、装软件、做后台任务，文件就是项目文件。',
          ),
          ComputerSection(ws: ws, title: '状态', pollAlways: true),
          PortsSection(ws: ws, delay: Motion.stagger(1)),
          ProcessSection(ws: ws, delay: Motion.stagger(2)),
          StorageSection(ws: ws, delay: Motion.stagger(3), onFiles: () => showProjectFiles(context, ws)),
          if (personal) BrowserSessionsSection(delay: Motion.stagger(4)),
          if (personal) HostSection(delay: Motion.stagger(5)),
        ]),
      ),
    );
  }
}
