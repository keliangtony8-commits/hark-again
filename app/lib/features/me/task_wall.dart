// v2.15 碰壁条（后端 app/task_wall.py）：任务 / 面板最近一次运行碰到的障碍——
// “需要登录 jw.example.edu”“需要重新连接 github”这类要你处理的，或“被验证码挡住、之后会再试”这类它自己会好的。
// 一处组件，两个地方用：任务详情页头卡（自动暂停说明条下面）和 Home 面板卡（标题行下面、内容上面，内容还是上一次的）。
// 样式同 _PauseNote：小块底色 + 警示色图标，文字正文色；要你处理的带“去处理”（wallOpen → cardTargets 的页面）和“重试”。
// 出现 / 收起用 FadeSwitcher（碰壁修好、下一次成功后服务端清掉，条子平滑收起）。
// v2.19：你存了对应登录 / 连好连接器后服务端自动排重跑（wallRetrying）→ 图标换成同步、小字说正在重跑、不再显示“重试”，同样淡入淡出切换。文案只用服务端给的 wallLabel / wallReason。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../home/action_card.dart' show cardTargets;

/// 碰壁条下面那句小字：要你处理的说清怎么好；不要你管的说它会自己再试；已排上重跑的说正在跑。
String wallHint(ScheduledTask t) {
  if (t.wallRetrying) return '已经在重新运行，成功后这条会自动收起。';
  if (!t.wallFixable) return '不用你管，下次会自动再试。';
  return t.isPanel ? '面板先显示上一次的内容。处理好后会自动重跑，也可以点“重试”。' : '处理好后会自动重跑，也可以点“重试”。';
}

/// v2.19 存登录 / 连连接器之后的那条提示：服务端给了“已重新运行”那句就接在后面。
String withRetried(String head, String? note) => note == null || note.isEmpty ? head : '$head。$note';

/// 有壁时一块说明条，没壁时什么都不占；外面包了 FadeSwitcher，壁出现 / 清掉都是平滑的。
class WallNotice extends StatelessWidget {
  const WallNotice({super.key, required this.task, this.onRetry, this.padding = const EdgeInsets.only(top: Sp.x3)});
  final ScheduledTask task;

  /// 点“重试”（立即运行一次）；null = 不显示这个按钮（比如正在跑）。
  final VoidCallback? onRetry;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) => FadeSwitcher(
        alignment: AlignmentDirectional.topStart,
        child: task.walled
            ? Padding(
                key: ValueKey('wall:${task.wallLabel}:${task.wallRetrying}'),
                padding: padding,
                child: _WallBody(task: task, onRetry: task.wallRetrying ? null : onRetry),
              )
            : const SizedBox(width: double.infinity, key: ValueKey('no-wall')),
      );
}

class _WallBody extends StatelessWidget {
  const _WallBody({required this.task, this.onRetry});
  final ScheduledTask task;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final target = task.wallOpen == null ? null : cardTargets[task.wallOpen];
    final reason = task.wallReason;
    final buttonStyle = TextButton.styleFrom(minimumSize: const Size(0, A11y.minTap), padding: const EdgeInsets.symmetric(horizontal: Sp.x3));
    return Semantics(
      container: true,
      label: '碰壁：${task.wallLabel}${reason == null ? '' : '，$reason'}，${wallHint(task)}',
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x3, Sp.x3, Sp.x1),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          ExcludeSemantics(
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(
                task.wallRetrying ? Icons.sync_rounded : (task.wallFixable ? Icons.lock_outline_rounded : Icons.hourglass_top_rounded),
                size: Sp.x5,
                color: task.wallRetrying ? p.text2 : p.warning,
              ),
              const SizedBox(width: Sp.x2),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(task.wallLabel!, style: context.text.bodyMedium?.copyWith(color: p.text, fontWeight: FontWeight.w600)),
                  if (reason != null) Text(reason, maxLines: 3, overflow: TextOverflow.ellipsis, style: context.text.bodySmall?.copyWith(color: p.text2)),
                  Text(wallHint(task), style: context.text.bodySmall?.copyWith(color: p.text3)),
                ]),
              ),
            ]),
          ),
          if (task.wallFixable && (target != null || onRetry != null))
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              if (target != null)
                TextButton.icon(
                  style: buttonStyle,
                  onPressed: () => context.push(target.route.replaceAll('{task}', task.id)),
                  icon: Icon(target.icon, size: Fs.lg),
                  label: Text(target.label),
                ),
              if (onRetry != null) TextButton(style: buttonStyle, onPressed: onRetry, child: const Text('重试')),
            ])
          else
            const SizedBox(height: Sp.x2),
        ]),
      ),
    );
  }
}
