// 设计 v2：用户 = 右侧墨色气泡；助手 = 左侧回复卡，两者最宽 Layout.bubbleMax（按聊天区宽，不按屏宽——平板双栏也对）。
// §I（v2.84，对标 Hark）：气泡下面没有常驻按钮。
// - 点哪条显示哪条的时间（ChatView._timesShown，每条各自开关），这里只按 showTime 在自己那侧画一行灰色时间。
// - 长按 = 原地聚焦菜单（§J，ui/focus_menu.dart）：用户气泡（复制、回复，最后一条另有“编辑”）；
//   回复（复制、选择文字、回复，再往后 朗读、重新生成、存成文件、有用 / 不好——超过 5 项收进“更多”）。
//   回复正文不原地可选（ProseScope），选字走菜单里的“选择文字”。
// - 引用：用户气泡 / 不紧挨着原话的回复顶上一行 QuoteLine（quote_line.dart），点一下回到原消息（onJumpQuote）。
// - 照常显示的状态行：待发送 / 发送失败、没正常说完（ReplyEnd.label）、“继续”、正在朗读（点了停止）。
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
import '../../ui/focus_menu.dart';
import '../../ui/sheets.dart';
import '../projects/save_reply.dart';
import 'activity_view.dart';
import 'quote_line.dart';
import 'reply_rating.dart';
import 'retry_line.dart';
import 'thought_view.dart';

class MessageView extends StatelessWidget {
  const MessageView(this.message,
      {super.key,
      this.onResend,
      this.onDiscard,
      this.onRegenerate,
      this.onContinue,
      this.onEdit,
      this.onSave,
      this.onRate,
      this.onQuote,
      this.onJumpQuote,
      this.showQuote = true,
      this.showTime = false});
  final Message message;

  /// 这条的时间开着（ChatView._timesShown 唯一状态）：在气泡同侧画一行时间（formatClock）；没有时间（还没落库）就不画。
  final bool showTime;
  final void Function(String id)? onResend, onDiscard;
  final VoidCallback? onRegenerate;

  /// “继续”：最后一条没正常说完的回复（[ReplyEnd.continuable]）且能发消息时才给（ChatView 决定）。
  final VoidCallback? onContinue;

  /// 只有最后一条可编辑的用户消息才给（由 ChatView 按 ChatState.editableId 决定）。
  final VoidCallback? onEdit;

  /// 存成文件（features/projects/save_reply.dart）；ChatView 给已落库的回复。
  final VoidCallback? onSave;

  /// 👍 / 👎（features/chat/reply_rating.dart）；ChatView 只给已落库的回复。
  final RateReply? onRate;

  /// 菜单里的“回复”（§J 引用回复）；ChatView 只给已落库、生成完的消息。
  final VoidCallback? onQuote;

  /// 顶上画不画引用行（ChatView 按 [showsQuote] 算：助手回复紧挨着原话时不画）。
  final bool showQuote;

  /// 点气泡顶上的引用行：回到被引用的那条（ChatView._reveal）。
  final void Function(String id)? onJumpQuote;

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
    final origin = message.blocks.whereType<OriginBlock>().firstOrNull;
    final bubble = Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      if (skills.isNotEmpty || agents.isNotEmpty || origin != null) // 来自 X / `@子助手` / `$技能`：一排小标签（skill_chip.dart）
        Padding(
          padding: const EdgeInsets.only(bottom: Sp.x2),
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: maxWidth),
            child: Wrap(alignment: WrapAlignment.end, spacing: Sp.x2, runSpacing: Sp.x1, children: [
              if (origin != null) OriginChip(origin),
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
            decoration: BoxDecoration(color: p.ink, borderRadius: BorderRadius.circular(Radii.card)), // v2.1：用户气泡是墨色，不是橙色
            child: Text(text, style: context.text.bodyLarge?.copyWith(color: p.onInk)),
          ),
        ),
    ]);
    // 长按 = 聚焦菜单（代替文字选择，两者手势冲突）；没发出的消息走状态行上的菜单
    final pressable = FocusPressable(enabled: !message.unsent, alignEnd: true, actions: () => _userActions(context, text), child: bubble);
    final quote = showQuote ? message.quote : null;
    return Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      if (quote != null) QuoteLine(quote, alignEnd: true, onTap: onJumpQuote == null ? null : () => onJumpQuote!(quote.id)),
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
      RiseSwitcher(child: _time(context, end: true)),
    ]);
  }

  /// 点一下露出的时间行（§I）：灰色小字，靠气泡那侧。
  Widget? _time(BuildContext context, {required bool end}) {
    final t = formatClock(message.createdAt);
    if (!showTime || t.isEmpty) return null;
    return Padding(
      key: const ValueKey('time'),
      padding: const EdgeInsets.fromLTRB(Sp.x2, Sp.x1, Sp.x2, 0),
      child: Align(
        alignment: end ? Alignment.centerRight : Alignment.centerLeft,
        child: Text(t, style: context.text.labelSmall?.copyWith(color: context.palette.text3)),
      ),
    );
  }

  /// 长按回复的菜单项（§J 排序：最常用的复制 / 选择文字 / 回复在前；其余跟后，多了由 FocusMenu 收进“更多”）。
  List<SheetAction<void>> _replyActions(BuildContext context) {
    final text = copyText(message.blocks);
    final spoken = speakableText(message.blocks);
    final speech = ProviderScope.containerOf(context, listen: false);
    final speaking = speech.read(speechProvider).phaseOf(message.id) != SpeechPhase.idle;
    return [
      if (text.isNotEmpty) _copy(context, text),
      if (text.isNotEmpty) SheetAction(Icons.text_fields_rounded, '选择文字', onTap: () => _selectText(context, text)),
      if (onQuote != null) SheetAction(Icons.reply_rounded, '回复', onTap: onQuote),
      if (spoken.isNotEmpty)
        SheetAction(speaking ? Icons.stop_rounded : Icons.volume_up_rounded, speaking ? '停止朗读' : '朗读', onTap: () async {
          final err = await speech.read(speechProvider.notifier).toggle(message.id, spoken);
          if (err != null && context.mounted) showToast(context, err);
        }),
      if (onRegenerate != null) SheetAction(Icons.refresh_rounded, '重新生成', onTap: onRegenerate),
      if (text.isNotEmpty && onSave != null) SheetAction(Icons.drive_folder_upload_outlined, saveReplyLabel, onTap: onSave),
      if (onRate != null) ...ratingActions(context, onRate!, message.feedback),
    ];
  }

  SheetAction<void> _copy(BuildContext context, String text) => SheetAction(Icons.content_copy_rounded, '复制', onTap: () {
        Clipboard.setData(ClipboardData(text: text));
        showToast(context, '已复制');
      });

  /// “选择文字”：整条回复放进一张可选中的弹层（聊天里原地选字会抢点按和长按）。
  void _selectText(BuildContext context, String text) => showAppScrollSheet<void>(
        context,
        builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x3),
            child: Text('选择文字', style: ctx.text.titleMedium),
          ),
          SheetList(padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x5), children: [AppMarkdown(text)]),
        ]),
      );

  List<SheetAction<void>> _userActions(BuildContext context, String text) => [
        if (text.isNotEmpty) _copy(context, text),
        if (onQuote != null) SheetAction(Icons.reply_rounded, '回复', onTap: onQuote),
        if (onEdit != null) SheetAction(Icons.edit_outlined, '编辑', onTap: onEdit),
      ];

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
            radius: Radii.card,
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
    // 活动时间线（v1.28）：用过工具就在回复上方多一行“做了 N 步”，生成中有完成的步骤时就出现（“已做 N 步”）
    final activity = message.steps.isNotEmpty && (!message.pending || message.steps.any((s) => !s.running));
    final quote = showQuote ? message.quote : null;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // §C：回复不紧挨着它回应的那句时，顶上一行连接线 + 原话（和用户引用同一个 QuoteLine）
      if (quote != null) QuoteLine(quote, onTap: onJumpQuote == null ? null : () => onJumpQuote!(quote.id)),
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
      _pressable(
        context,
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
      // 没正常说完：一行说明（原来挤在操作行尾）；正在朗读：一行“点按停止”（原来是操作行里的停止键）
      RiseSwitcher(child: !message.pending && message.end.label != null ? _EndLine(key: const ValueKey('end'), end: message.end) : null),
      if (!message.pending) _SpeakingLine(id: message.id),
      RiseSwitcher(child: message.pending ? null : _time(context, end: false)),
      // 用户发了别的、或开始生成：“继续”平滑收起
      RiseSwitcher(
        child: !message.pending && onContinue != null ? _ContinueRow(key: const ValueKey('continue'), end: message.end, onTap: onContinue!) : null,
      ),
    ]);
  }

  /// 回复卡：正文不原地可选（ProseScope）；生成完的回复长按出聚焦菜单。卡片里自己的按钮/链接照旧优先。
  Widget _pressable(BuildContext context, Widget child) =>
      FocusPressable(enabled: !message.pending, actions: () => _replyActions(context), child: ProseScope(isSelectable: false, child: child));
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

/// 没正常说完的说明行：图标 + ReplyEnd.label（太长就省略）。
class _EndLine extends StatelessWidget {
  const _EndLine({super.key, required this.end});
  final ReplyEnd end;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(Sp.x2, Sp.x1, Sp.x2, 0),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(replyEndIcon(end), size: 14, color: end.warn ? p.warning : p.text3),
        const SizedBox(width: Sp.x1),
        Flexible(child: Text(end.label!, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodySmall?.copyWith(color: p.text3))),
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

/// 正在朗读这条（从长按菜单开始的）：一行“正在朗读 · 点按停止”，准备语音时是闪烁小点；同一时间只有一条在读（core/speech.dart）。
class _SpeakingLine extends ConsumerWidget {
  const _SpeakingLine({required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final phase = ref.watch(speechProvider.select((s) => s.phaseOf(id)));
    return RiseSwitcher(
      child: phase == SpeechPhase.idle
          ? null
          : Pressable(
              key: const ValueKey('speaking'),
              onTap: () => ref.read(speechProvider.notifier).stop(),
              semanticLabel: '停止朗读',
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: A11y.minTap),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x2),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    phase == SpeechPhase.loading ? PulseDot(color: p.text2) : Icon(Icons.stop_rounded, size: 14, color: p.text2),
                    const SizedBox(width: Sp.x1),
                    Text(phase == SpeechPhase.loading ? '准备朗读…' : '正在朗读 · 点按停止', style: context.text.bodySmall?.copyWith(color: p.text2)),
                  ]),
                ),
              ),
            ),
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
