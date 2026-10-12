// 设计 v2：用户 = 右侧强调色胶囊；助手 = 左侧玻璃卡（假玻璃，不模糊），两者最宽 Layout.bubbleMax（按聊天区宽，不按屏宽——平板双栏也对）。
// 一条消息：用户 = 右侧气泡（没发出的带“待发送/发送失败”状态行；长按出菜单：复制，最后一条另有“编辑”）；助手 = 全宽块列表 + 工具进度 + 思考动画，
// 生成完的回复下方一行操作（复制、朗读、存成文件；最后一条另有“重新生成”，由 ChatView 决定给不给 onRegenerate）。
// 没正常说完的最后一条（停止 / 被打断 / 步数用完 / 原地打转）操作行下再给一颗“继续”（v1.56，发出去就是一句“继续”）。
// 操作行只常驻在最后一条（和没正常说完的回复）上；更早的回复点一下卡片才露出来（v1.17，ChatView 记住露出的是哪条，同时只露一条）。
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../blocks/block_view.dart';
import '../../blocks/skill_chip.dart';
import '../../core/speech.dart';
import '../../models/activity.dart';
import '../../models/block.dart';
import '../../models/message.dart';
import '../../models/reply_end.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/markdown.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../projects/save_reply.dart';
import 'activity_view.dart';
import 'retry_line.dart';
import 'thought_view.dart';

class MessageView extends StatelessWidget {
  const MessageView(this.message, {super.key, this.onResend, this.onDiscard, this.onRegenerate, this.onContinue, this.onEdit, this.onSave, this.last = false, this.revealed = false, this.onReveal});
  final Message message;

  /// 是不是对话里最后一条回复：只有它常驻“复制 / 重新生成”一排小图标（版面更干净）。
  final bool last;

  /// 更早的回复：点一下卡片露出 / 收起操作行（复制 · 朗读 · 存成文件）。用点按不用长按——
  /// 回复是可选中文字，长按归系统选字；点正文经 TextTapScope 传上来，点卡片空白处由外层 GestureDetector 收。
  /// onReveal 只给已完成、非最后一条的回复（ChatView 决定）；revealed = 现在是不是露着。
  final bool revealed;
  final VoidCallback? onReveal;
  final void Function(String id)? onResend, onDiscard;
  final VoidCallback? onRegenerate;

  /// “继续”：最后一条没正常说完的回复（[ReplyEnd.continuable]）且能发消息时才给（ChatView 决定）。
  final VoidCallback? onContinue;

  /// 只有最后一条可编辑的用户消息才给（由 ChatView 按 ChatState.editableId 决定）。
  final VoidCallback? onEdit;

  /// 存成文件（features/projects/save_reply.dart）；ChatView 给已落库的回复。
  final VoidCallback? onSave;

  @override
  Widget build(BuildContext context) => FadeSlideIn(
        child: LayoutBuilder(
          builder: (context, c) => message.isUser ? _user(context, c.maxWidth * Layout.bubbleMax) : _assistant(context, c.maxWidth),
        ),
      );

  Widget _user(BuildContext context, double maxWidth) {
    final p = context.palette;
    final text = plainText(message.blocks);
    final files = message.blocks.whereType<FileBlock>().toList();
    final skills = message.blocks.whereType<SkillBlock>().toList();
    final agents = message.blocks.whereType<AgentBlock>().toList();
    final bubble = Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      if (skills.isNotEmpty || agents.isNotEmpty) // `@子助手` / `$技能`：一排小标签（skill_chip.dart）
        Padding(
          padding: const EdgeInsets.only(bottom: Sp.x2),
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: maxWidth),
            child: Wrap(alignment: WrapAlignment.end, spacing: Sp.x2, runSpacing: Sp.x1, children: [
              for (final a in agents) AgentChip(a),
              for (final s in skills) SkillChip(s),
            ]),
          ),
        ),
      for (final f in files)
        Padding(
          padding: const EdgeInsets.only(bottom: Sp.x2),
          child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 280), child: BlockView(f)),
        ),
      if (text.isNotEmpty)
        ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x4 + 2, vertical: Sp.x3 - 2),
            // 一行时就是胶囊；多行时四角一样圆（不再做“小尾巴”，和玻璃卡同一套圆角语言）
            decoration: BoxDecoration(color: p.ink, borderRadius: BorderRadius.circular(Radii.lg)), // v2.1：用户气泡是墨色，不是橙色
            child: Text(text, style: context.text.bodyLarge?.copyWith(color: p.onInk)),
          ),
        ),
    ]);
    // 长按菜单代替文字选择（两者手势冲突）：复制整条最常用；没发出的消息走状态行上的菜单
    final pressable = message.unsent
        ? bubble
        : Semantics(
            onLongPressHint: '更多操作',
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onLongPress: () {
                HapticFeedback.selectionClick();
                _userMenu(context, text);
              },
              child: bubble,
            ),
          );
    return Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      // 待发送时气泡变淡，发出后渐变回实色
      AnimatedOpacity(
        opacity: message.outbox == Outbox.queued ? 0.6 : 1,
        duration: context.motion(Motion.base),
        curve: Motion.ease,
        child: pressable,
      ),
      AnimatedSize(
        duration: context.motion(Motion.base),
        curve: Motion.ease,
        alignment: Alignment.topRight,
        child: AnimatedSwitcher(
          duration: context.motion(Motion.fast),
          child: switch (message.outbox) {
            Outbox.sent when message.steer =>
              _OutboxStatus(key: const ValueKey('s'), icon: Icons.call_merge_rounded, label: Message.steerLabel, color: p.text3),
            Outbox.sent => const SizedBox.shrink(),
            Outbox.queued => _OutboxStatus(key: const ValueKey('q'), icon: Icons.schedule_rounded, label: '待发送', color: p.text3),
            Outbox.failed => _OutboxStatus(
                key: const ValueKey('f'),
                icon: Icons.error_outline_rounded,
                label: '发送失败 · 点按重发',
                color: p.danger,
                onTap: () => _failedMenu(context),
              ),
          },
        ),
      ),
    ]);
  }

  void _userMenu(BuildContext context, String text) => showActionSheet<void>(context, actions: [
        if (text.isNotEmpty)
          SheetAction(Icons.content_copy_rounded, '复制', onTap: () {
            Clipboard.setData(ClipboardData(text: text));
            showToast(context, '已复制');
          }),
        if (onEdit != null) SheetAction(Icons.edit_outlined, '编辑', onTap: onEdit),
      ]);

  void _failedMenu(BuildContext context) => showActionSheet<void>(context, title: '这条消息没发出去', actions: [
        SheetAction(Icons.refresh_rounded, '重发', onTap: () => onResend?.call(message.id)),
        SheetAction(Icons.delete_outline_rounded, '删除', danger: true, onTap: () => onDiscard?.call(message.id)),
      ]);

  /// 回复 = 若干段（models/block.dart replySegments）：正文段是左侧玻璃回复卡（最宽 bubbleMax），
  /// 卡片块（审批/订单/表单/商品/摘要/浏览器）单独成卡、占满聊天区（平板封顶 Layout.chatCardMax）。
  /// 运行中的工具小条跟在最后一段正文里；最后一段是卡片时另起一张小回复卡。
  Widget _assistant(BuildContext context, double width) {
    final maxWidth = width * Layout.bubbleMax;
    final running = message.pending ? message.steps.where((t) => t.running).toList() : const <ActivityStep>[];
    final thinking = message.pending && message.blocks.isEmpty && running.isEmpty;
    final segments = replySegments(message.blocks);
    final chips = [for (final t in running) _ToolChip(t)];
    if (chips.isNotEmpty && (segments.isEmpty || segments.last.card)) segments.add(const ReplySegment.prose([]));
    Widget prose(ReplySegment s, {required bool tail}) => ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: GlassSurface(
            radius: Radii.lg,
            shadow: false,
            padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (s.blocks.isNotEmpty) BlockList(s.blocks),
              if (tail)
                for (final (i, c) in chips.indexed) Padding(padding: EdgeInsets.only(top: s.blocks.isEmpty && i == 0 ? 0 : Sp.x2), child: c),
            ]),
          ),
        );
    // 还一个字都没有：只是一颗小玻璃胶囊里三个跳点，不先撑开一张空卡；
    // 推理模型吐出思考内容后，胶囊长成小卡，滚动露出最新两行（不存库，正文一来就换成回复卡）
    final body = thinking
        ? message.thought.trim().isEmpty
            ? const GlassSurface(
                key: ValueKey('thinking'),
                radius: Radii.full,
                shadow: false,
                padding: EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
                child: TypingDots(),
              )
            : ThinkingCard(key: const ValueKey('thought'), text: message.thought, since: message.thinkFrom)
        : Column(key: const ValueKey('card'), crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final (i, s) in segments.indexed)
              Padding(
                padding: EdgeInsets.only(top: i == 0 ? 0 : Sp.x3),
                child: s.card
                    ? ConstrainedBox(
                        constraints: BoxConstraints(maxWidth: math.min(width, Layout.chatCardMax)),
                        child: BlockView(s.blocks.single),
                      )
                    : prose(s, tail: i == segments.length - 1),
              ),
          ]);
    // 思考卡收成回复上方的一行（正文开始流出时就收），用 RiseSwitcher 长出来，不是一跳
    final summary = !thinking && message.thought.trim().isNotEmpty;
    // 活动时间线（v1.28）：用过工具就在回复上方多一行“用了 N 步”，生成中有完成的步骤时就出现（“已用 N 步”）
    final activity = message.steps.isNotEmpty && (!message.pending || message.steps.any((s) => !s.running));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: RiseSwitcher(child: summary ? ThoughtSummary(key: const ValueKey('summary'), message: message) : null),
      ),
      ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: RiseSwitcher(
            child: activity ? ActivitySummary(key: const ValueKey('activity'), steps: message.steps, pending: message.pending) : null),
      ),
      // 模型调用失败在自动重试 / 换了备用模型（v1.50）：只在生成中出现，回复完成随占位消息一起换掉
      ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: RiseSwitcher(
            child: message.pending && message.retry != null ? RetryLine(key: const ValueKey('retry'), notice: message.retry!) : null),
      ),
      _tappable(
        AnimatedSize(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          alignment: Alignment.topLeft,
          child: AnimatedSwitcher(
            duration: context.motion(Motion.fast),
            layoutBuilder: (current, previous) => Stack(alignment: Alignment.topLeft, children: [...previous, ?current]),
            child: body,
          ),
        ),
      ),
      // 操作行长出 / 收起都走 RiseSwitcher（回复不再是最后一条时也是平滑收起，不是一跳）
      RiseSwitcher(
        child: !message.pending && (last || message.end.continuable || revealed)
            ? _ReplyActions(
                key: const ValueKey('actions'),
                id: message.id,
                text: copyText(message.blocks),
                spoken: speakableText(message.blocks),
                end: message.end,
                onRegenerate: onRegenerate,
                onSave: onSave,
              )
            : null,
      ),
      // 用户发了别的、或开始生成：“继续”平滑收起
      RiseSwitcher(
        child: !message.pending && onContinue != null ? _ContinueRow(key: const ValueKey('continue'), end: message.end, onTap: onContinue!) : null,
      ),
    ]);
  }

  /// 较早的回复：整块（正文 + 卡片空白处）点一下切换操作行；卡片里自己的按钮/链接照旧优先。
  Widget _tappable(Widget child) {
    final reveal = onReveal;
    if (reveal == null) return child;
    void tap() {
      HapticFeedback.selectionClick();
      reveal();
    }

    return TextTapScope(
      onTap: tap,
      child: Semantics(
        onTapHint: revealed ? '收起操作' : '显示复制等操作',
        child: GestureDetector(onTap: tap, child: child),
      ),
    );
  }
}

/// 跨天时消息上方的日期：居中小灰字（今天 / 昨天 / 10月9日 星期五）。读屏当作标题，方便按天跳。
class DaySeparator extends StatelessWidget {
  const DaySeparator(this.day, {super.key});
  final DateTime day;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: Sp.x3, bottom: Sp.x4),
        child: Semantics(
          header: true,
          child: Text(formatDay(day), textAlign: TextAlign.center, style: context.text.labelSmall?.copyWith(color: context.palette.text3)),
        ),
      );
}

/// 气泡下方的发送状态行；失败时整行可点（外圈补足最小点击区）。
class _OutboxStatus extends StatelessWidget {
  const _OutboxStatus({super.key, required this.icon, required this.label, required this.color, this.onTap});
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final row = Semantics(
      liveRegion: true,
      child: ConstrainedBox(
        constraints: BoxConstraints(minHeight: onTap == null ? 0 : A11y.minTap),
        child: Padding(
          padding: const EdgeInsets.only(top: Sp.x1, left: Sp.x2),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 14, color: color),
            const SizedBox(width: Sp.x1),
            Text(label, style: context.text.bodySmall?.copyWith(color: color)),
          ]),
        ),
      ),
    );
    return onTap == null ? row : Pressable(onTap: onTap, child: row);
  }
}

/// 回复下方的操作行：低调的小图标（kit QuietAction，不抢内容）。回复完成时逐个错峰浮现；
/// 复制 → 对勾、朗读 → 停止都是原地 PopSwitcher；“重新生成”随可用状态淡入淡出。
class _ReplyActions extends StatelessWidget {
  const _ReplyActions({super.key, required this.id, required this.text, required this.spoken, this.end = ReplyEnd.done, this.onRegenerate, this.onSave});
  final String id;
  final String text;
  final String spoken; // 只含正文，没有就不给朗读键
  final ReplyEnd end; // 没正常说完：行尾标一句说明（ReplyEnd.label），太长就省略

  final VoidCallback? onRegenerate;
  final VoidCallback? onSave; // 存成文件：有可复制的内容才给

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final items = <Widget>[
      if (text.isNotEmpty) CopyAction(text: text),
      if (spoken.isNotEmpty) _SpeakButton(id: id, text: spoken),
      AnimatedSwitcher(
        duration: context.motion(Motion.fast),
        child: onRegenerate == null
            ? const SizedBox.shrink()
            : QuietAction(
                key: const ValueKey('regen'),
                icon: const Icon(Icons.refresh_rounded),
                tooltip: '重新生成',
                onPressed: onRegenerate,
              ),
      ),
      // 把回复带走（存成文件）排在“就地重来”之后，和网页同序：复制 · 朗读 · 重新生成 · 存成文件（v1.16）
      if (text.isNotEmpty && onSave != null)
        QuietAction(icon: const Icon(Icons.drive_folder_upload_outlined), tooltip: saveReplyLabel, onPressed: onSave),
    ];
    final label = end.label;
    // 和卡片里的正文左缘对齐：图标键自带 8px 内边距，再补一点。说明文字占剩下的宽，窄屏省略不溢出
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x1, left: Sp.x1),
      child: Row(children: [
        for (var i = 0; i < items.length; i++) FadeSlideIn(delay: Motion.stagger(i, from: 1), child: items[i]),
        if (label != null)
          Flexible(
            child: FadeSlideIn(
              delay: Motion.stagger(items.length, from: 1),
              child: Padding(
                padding: const EdgeInsets.only(left: Sp.x1),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(replyEndIcon(end), size: 14, color: end.warn ? p.warning : p.text3),
                  const SizedBox(width: Sp.x1),
                  Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodySmall?.copyWith(color: p.text3))),
                ]),
              ),
            ),
          ),
      ]),
    );
  }
}

/// 没正常说完的图标：停止方块 / 断电 / 沙漏 / 打转。
IconData replyEndIcon(ReplyEnd end) => switch (end) {
      ReplyEnd.interrupted => Icons.power_off_outlined,
      ReplyEnd.wrapped => Icons.hourglass_bottom_rounded,
      ReplyEnd.looped => Icons.sync_problem_rounded,
      _ => Icons.stop_circle_outlined,
    };

/// 最后一条没正常说完的回复下的“继续”：小号胶囊（tile 底，不占强调色），点了等于发一句“继续”，轻触感。
class _ContinueRow extends StatelessWidget {
  const _ContinueRow({super.key, required this.end, required this.onTap});
  final ReplyEnd end;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.centerLeft,
        child: Padding(
          padding: const EdgeInsets.only(left: Sp.x2),
          child: FadeSlideIn(
            delay: Motion.stagger(2, from: 1),
            child: Semantics(
              container: true, // 自成一个读屏节点，不并进上面回复的可选文字里
              hint: end.continueHint,
              child: PillButton(
                dense: true,
                icon: Icons.play_arrow_rounded,
                label: continueText,
                onTap: () {
                  HapticFeedback.selectionClick();
                  onTap();
                },
              ),
            ),
          ),
        ),
      );
}

/// 朗读键：喇叭 →（向服务器要语音时）闪烁的小点 → 停止方块；同一时间只有一条在读（core/speech.dart）。
class _SpeakButton extends ConsumerWidget {
  const _SpeakButton({required this.id, required this.text});
  final String id;
  final String text;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final phase = ref.watch(speechProvider.select((s) => s.phaseOf(id)));
    final icon = switch (phase) {
      SpeechPhase.idle => const Icon(Icons.volume_up_rounded, key: ValueKey('idle')),
      SpeechPhase.loading => SizedBox.square(
          key: const ValueKey('loading'), dimension: QuietAction.iconSize, child: Center(child: PulseDot(color: p.text2))),
      SpeechPhase.playing => Icon(Icons.stop_rounded, key: const ValueKey('playing'), color: p.ink),
    };
    return QuietAction(
      onPressed: () async {
        final err = await ref.read(speechProvider.notifier).toggle(id, text);
        if (err != null && context.mounted) showToast(context, err);
      },
      tooltip: phase == SpeechPhase.idle ? '朗读' : '停止朗读',
      icon: icon,
    );
  }
}

/// 正在跑的那一步：转圈 + “运行命令 · ls -la…”（摘要等宽、一行省略）。
class _ToolChip extends StatelessWidget {
  const _ToolChip(this.step);
  final ActivityStep step;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Align(
      alignment: Alignment.centerLeft,
      child: FadeSlideIn(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x1 + 2),
          decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.full)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.6, color: p.accent)),
            const SizedBox(width: Sp.x2),
            Text(step.detail.isEmpty ? '正在${step.title}…' : '正在${step.title}', style: context.text.bodySmall),
            if (step.detail.isNotEmpty)
              Flexible(
                child: Text(' · ${step.detail}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.bodySmall?.copyWith(fontFamily: 'monospace', fontSize: Fs.xs, color: p.text2)),
              ),
          ]),
        ),
      ),
    );
  }
}
