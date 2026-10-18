// 电脑详情页：我的 → 我的电脑（个人工作区，v1.25）和项目首屏点“电脑”进来的 /projects/<id>/computer（v1.27）共用。
// v3.5.1（用户 10-18 真机截图：约 4.7 屏长、内存 / 服务重复出现）改成一屏概览 + 子页，能力一样不少：
//   标题行右侧玻璃圆钮“重启”（ComputerRestartButton，只在运行中给）
//   状态卡（ComputerStatusGroup：运行中、CPU / 内存 / 磁盘、内存条、打满警示 +“整台服务器”一行，
//     同一组里接着常驻服务 + 后台任务，只露前 3 行，多了一行“全部 N 个 ›”进子页 tasks）
//   一组单行导航（行尾一个值，紧张 = 警示色、已满 = 危险色）：端口 / 内存 / 正在运行的程序 / 磁盘（+ 个人电脑的 浏览器登录 / Pages / 主机模式），
//     点了进 ComputerDetailScreen（/me/computer/:part、/projects/:id/computer/:part），子页里是原来那一节（不重复节标题）。
//   页底一行小字：这台电脑是什么（原页头说明）。
// 设置搜索（me_index.dart）的 disk / browser-logins / host 定位到这里对应的导航行（Spotlight row）。
// 轮询在 ComputerPoll（computer_section.dart）；页面和每一行只 select 自己显示的值，轮询只重建变了的行。下拉刷新一起刷。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/workspace.dart';
import '../../models/computer.dart';
import '../../models/host.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sub_page.dart';
import '../me/pages_screen.dart';
import '../projects/project_files_sheet.dart';
import 'browser_sessions_section.dart';
import 'computer_details.dart';
import 'computer_section.dart';
import 'host_section.dart';

/// 这台电脑的页面路径（子页挂在下面）。
String computerPath(String ws) => isPersonalWorkspace(ws) ? '/me/computer' : '/projects/$ws/computer';

Future<void> _refreshAll(WidgetRef ref, String ws) => Future.wait([
      ref.read(computerProvider(ws).notifier).reload(),
      if (isPersonalWorkspace(ws)) ref.read(browserSessionsProvider.notifier).reload(),
      if (isPersonalWorkspace(ws)) ref.read(hostProvider.notifier).reload(),
    ]);

class ComputerScreen extends ConsumerWidget {
  const ComputerScreen({super.key, this.ws = personalWorkspace});
  final String ws;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final personal = isPersonalWorkspace(ws);
    void open(String part) => context.push('${computerPath(ws)}/$part');
    return SubPage(
      title: Text(personal ? '我的电脑' : '项目的电脑'),
      trailing: ComputerRestartButton(ws: ws),
      body: ComputerPoll(
        ws: ws,
        pollAlways: true,
        child: PullRefresh(
          onRefresh: () => _refreshAll(ref, ws),
          child: PageBody(children: [
            ComputerStatusGroup(ws: ws, limit: 3, onAll: () => open('tasks')),
            FadeSlideIn(
              delay: Motion.stagger(1),
              child: Padding(
                padding: const EdgeInsets.only(top: Sp.x5),
                child: ListGroup(children: [
                  _NavRow(
                    key: const Key('computer-nav-ports'),
                    icon: Icons.language_rounded,
                    title: '端口',
                    onTap: () => open('ports'),
                    value: (s) => s.running ? ('${s.ports.length} 个', _Tone.none) : null,
                    ws: ws,
                  ),
                  _NavRow(
                    key: const Key('computer-nav-memory'),
                    icon: Icons.memory_rounded,
                    title: '内存',
                    onTap: () => open('memory'),
                    value: _memoryValue,
                    ws: ws,
                  ),
                  _NavRow(
                    key: const Key('computer-nav-processes'),
                    icon: Icons.terminal_rounded,
                    title: '正在运行的程序',
                    onTap: () => open('processes'),
                    value: (s) => s.running ? ('${s.processes.length} 个', _Tone.none) : null,
                    ws: ws,
                  ),
                  Spotlight(
                    id: 'disk',
                    row: true,
                    child: _NavRow(
                      key: const Key('computer-nav-disk'),
                      icon: Icons.storage_rounded,
                      title: '磁盘',
                      onTap: () => open('disk'),
                      value: _diskValue,
                      ws: ws,
                    ),
                  ),
                  if (personal)
                    Spotlight(id: 'browser-logins', row: true, child: _BrowserNavRow(onTap: () => open('browser-logins'))),
                  if (personal) // v2.81：Pages 就是这台电脑替你做好、发布出去的网页
                    ListRow(key: const Key('computer-nav-pages'), icon: Icons.web_rounded, title: 'Pages', onTap: () => context.push('/me/pages')),
                  if (personal) Spotlight(id: 'host', row: true, child: _HostNavRow(onTap: () => open('host'))),
                ]),
              ),
            ),
            _Intro(ws: ws),
          ]),
        ),
      ),
    );
  }
}

enum _Tone { none, warning, danger }

typedef _Value = (String, _Tone)?;

_Value _memoryValue(ComputerStatus s) {
  final used = s.memory?.used ?? s.memoryUsed;
  final limit = s.memory?.limit ?? s.memoryLimit;
  if (!s.running || used == null) return null;
  final ratio = limit == null || limit <= 0 ? 0.0 : used / limit;
  final tone = s.oomKills > 0 || ratio >= 0.98 ? _Tone.danger : (ratio >= computerMemoryTight ? _Tone.warning : _Tone.none);
  return ('${formatSize(used)}${limit != null ? ' / ${formatSize(limit)}' : ''}', tone);
}

_Value _diskValue(ComputerStatus s) => (
      '${formatSize(s.diskUsed)}${s.diskPartial ? '+' : ''}${s.diskLimit != null ? ' / ${formatSize(s.diskLimit!)}' : ''}',
      s.diskFull ? _Tone.danger : (s.diskTight ? _Tone.warning : _Tone.none),
    );

/// 行尾的值：一行、按档位着色，后面跟箭头；值变了上下换（SwapSwitcher，过渡完不留透明度层）。
Widget _trailing(BuildContext context, _Value v) {
  final p = context.palette;
  return Row(mainAxisSize: MainAxisSize.min, children: [
    if (v != null) ...[
      ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Layout.rowValueMax),
        child: SwapSwitcher(
          child: Text(
            v.$1,
            key: ValueKey(v.$1),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: context.text.bodyMedium?.copyWith(
                color: switch (v.$2) { _Tone.danger => p.danger, _Tone.warning => p.warning, _Tone.none => p.text3 }),
          ),
        ),
      ),
      const SizedBox(width: Sp.x1),
    ],
    Icon(Icons.chevron_right_rounded, color: p.text3, size: Layout.rowIcon),
  ]);
}

/// 一行导航：只 select 自己行尾那个值。
class _NavRow extends ConsumerWidget {
  const _NavRow({super.key, required this.ws, required this.icon, required this.title, required this.onTap, required this.value});
  final String ws;
  final IconData icon;
  final String title;
  final VoidCallback onTap;
  final _Value Function(ComputerStatus s) value;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(computerProvider(ws).select((a) => a.value == null ? null : value(a.value!)));
    return ListRow(icon: icon, title: title, onTap: onTap, trailing: _trailing(context, v));
  }
}

class _BrowserNavRow extends ConsumerWidget {
  const _BrowserNavRow({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(browserSessionsProvider.select((a) => switch (a.value) {
          final l? => ('${l.length} 个网站', l.any((s) => s.expired) ? _Tone.warning : _Tone.none),
          _ => null,
        }));
    return ListRow(key: const Key('computer-nav-browser'), icon: Icons.public_rounded, title: '浏览器登录', onTap: onTap, trailing: _trailing(context, v));
  }
}

class _HostNavRow extends ConsumerWidget {
  const _HostNavRow({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final on = ref.watch(hostProvider.select((a) => a.value?.enabled));
    return ListRow(
      key: const Key('computer-nav-host'),
      icon: Icons.admin_panel_settings_outlined,
      title: '主机模式',
      onTap: onTap,
      trailing: _trailing(context, on == null ? null : (on ? '已打开' : '关闭', _Tone.none)),
    );
  }
}

/// 页底一行小字：这台电脑是什么（v2.85 说清是服务器上隔出来的一块、多大；原页头说明）。
class _Intro extends ConsumerWidget {
  const _Intro({required this.ws});
  final String ws;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final personal = isPersonalWorkspace(ws);
    final line = ref.watch(computerProvider(ws).select((a) => computerIntro(a.value, personal: personal)));
    return Padding(
      padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x4, Sp.x1, 0),
      child: Text(line, key: const Key('computer-intro'), style: context.text.labelSmall),
    );
  }
}

/// 子页（v3.5.1）：/me/computer/:part、/projects/:id/computer/:part。复用原来各节（不画节标题，页标题就是节名）。
/// part：tasks / ports / memory / processes / disk / browser-logins / pages / host。
class ComputerDetailScreen extends ConsumerWidget {
  const ComputerDetailScreen({super.key, this.ws = personalWorkspace, required this.part});
  final String ws;
  final String part;

  static const titles = {
    'tasks': '后台任务',
    'ports': '正在监听的端口',
    'memory': '内存',
    'processes': '正在运行的程序',
    'disk': '磁盘',
    'browser-logins': '浏览器登录',
    'host': hostSectionTitle,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (part == 'pages') return const PagesScreen();
    final personal = isPersonalWorkspace(ws);
    final known = titles.containsKey(part) && (personal || !const {'browser-logins', 'host'}.contains(part));
    final Widget body = switch (part) {
      _ when !known => const _Empty('没有这一页'),
      'tasks' => _OrEmpty(ws: ws, empty: (s) => s.services.isEmpty && s.jobs.isEmpty, text: '没有正在运行的服务和后台任务',
          child: ComputerJobsGroup(ws: ws)),
      'ports' => _OrEmpty(ws: ws, empty: (s) => !s.running || s.ports.isEmpty, text: '没有正在监听的端口',
          child: PortsSection(ws: ws, titled: false)),
      'memory' => _OrEmpty(ws: ws, empty: (s) => memoryViewOf(s) == null, text: '电脑没在运行，暂时看不到内存占用',
          child: MemorySection(ws: ws, titled: false)),
      'processes' => _OrEmpty(ws: ws, empty: (s) => !s.running || s.processes.isEmpty, text: '没有正在运行的程序',
          child: ProcessSection(ws: ws, titled: false)),
      'disk' => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          StorageSection(ws: ws, titled: false, onFiles: () => showProjectFiles(context, ws)),
          DiskJobsSection(ws: ws, delay: Motion.stagger(1)),
        ]),
      'browser-logins' => const BrowserSessionsSection(titled: false),
      _ => const HostSection(titled: false),
    };
    final computer = known && !const {'browser-logins', 'host'}.contains(part);
    final page = PullRefresh(
      onRefresh: () => switch (part) {
        'browser-logins' => ref.read(browserSessionsProvider.notifier).reload(),
        'host' => ref.read(hostProvider.notifier).reload(),
        _ => ref.read(computerProvider(ws).notifier).reload(),
      },
      child: PageBody(children: [body]),
    );
    return SubPage(
      title: Text(titles[part] ?? (personal ? '我的电脑' : '项目的电脑')),
      body: computer ? ComputerPoll(ws: ws, pollAlways: true, child: page) : page,
    );
  }
}

/// 子页里这一节没东西时说一句（原节在空时整块不画，单独成页就成了白屏）。
class _OrEmpty extends ConsumerWidget {
  const _OrEmpty({required this.ws, required this.empty, required this.text, required this.child});
  final String ws;
  final bool Function(ComputerStatus s) empty;
  final String text;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final none = ref.watch(computerProvider(ws).select((a) => a.value != null && empty(a.value!)));
    return none ? _Empty(text) : child;
  }
}

class _Empty extends StatelessWidget {
  const _Empty(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x1, vertical: Sp.x5),
        child: Text(text, textAlign: TextAlign.center, style: context.text.bodySmall),
      );
}
