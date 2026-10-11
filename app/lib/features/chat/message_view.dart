// 设计 v2：用户 = 右侧强调色胶囊；助手 = 左侧玻璃卡（假玻璃，不模糊），两者最宽 Layout.bubbleMax（按聊天区宽，不按屏宽——平板双栏也对）。
// 一条消息：用户 = 右侧气泡（没发出的带“待发送/发送失败”状态行；长按出菜单：复制，最后一条另有“编辑”）；助手 = 全宽块列表 + 工具进度 + 思考动画，
// 生成完的回复下方一行操作（复制、朗读；最后一条另有“重新生成”，由 ChatView 决定给不给 onRegenerate）。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../blocks/block_view.dart';
import '../../core/speech.dart';
import '../../models/block.dart';
import '../../models/message.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'thought_view.dart';

class MessageView extends StatelessWidget {
  const MessageView(this.message, {super.key, this.onResend, this.onDiscard, this.onRegenerate, this.onEdit, this.last = false});
  final Message message;

  /// 是不是对话里最后一条回复：只有它常驻“复制 / 重新生成”一排小图标（版面更干净）。
  /// 更早的回复要复制就长按文字用系统选择（回复是可选中文字；再加长按菜单会和文字选择抢手势）。
  final bool last;
  final void Function(String id)? onResend, onDiscard;
  final VoidCallback? onRegenerate;

  /// 只有最后一条可编辑的用户消息才给（由 ChatView 按 ChatState.editableId 决定）。
  final VoidCallback? onEdit;

  @override
  Widget build(BuildContext context) => FadeSlideIn(
        child: LayoutBuilder(
          builder: (context, c) => message.isUser ? _user(context, c.maxWidth * Layout.bubbleMax) : _assistant(context, c.maxWidth * Layout.bubbleMax),
        ),
      );

  Widget _user(BuildContext context, double maxWidth) {
    final p = context.palette;
    final text = plainText(message.blocks);
    final files = message.blocks.whereType<FileBlock>().toList();
    final bubble = Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
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

  Widget _assistant(BuildContext context, double maxWidth) {
    final running = message.pending ? message.tools.where((t) => t.running).toList() : const <ToolRun>[];
    final thinking = message.pending && message.blocks.isEmpty && running.isEmpty;
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
        : GlassSurface(
            key: const ValueKey('card'),
            radius: Radii.lg,
            shadow: false,
            padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x4, Sp.x3),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (message.blocks.isNotEmpty) BlockList(message.blocks),
              for (final t in running) Padding(padding: EdgeInsets.only(top: message.blocks.isEmpty ? 0 : Sp.x2), child: _ToolChip(t.label)),
            ]),
          );
    // 思考卡收成回复上方的一行（正文开始流出时就收），用 RiseSwitcher 长出来，不是一跳
    final summary = !thinking && message.thought.trim().isNotEmpty;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          RiseSwitcher(child: summary ? ThoughtSummary(key: const ValueKey('summary'), message: message) : null),
          AnimatedSize(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            alignment: Alignment.topLeft,
            child: AnimatedSwitcher(duration: context.motion(Motion.fast), child: body),
          ),
        ]),
      ),
      if (!message.pending && (last || message.stopped))
        _ReplyActions(id: message.id, text: copyText(message.blocks), spoken: speakableText(message.blocks), stopped: message.stopped, onRegenerate: onRegenerate),
    ]);
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
  const _ReplyActions({required this.id, required this.text, required this.spoken, this.stopped = false, this.onRegenerate});
  final String id;
  final String text;
  final String spoken; // 只含正文，没有就不给朗读键
  final bool stopped; // 半截回复：行尾标“已停止”，提醒内容不完整（重新生成就能补全）
  final VoidCallback? onRegenerate;

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
      if (stopped)
        Padding(
          padding: const EdgeInsets.only(left: Sp.x1),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.stop_circle_outlined, size: 14, color: p.text3),
            const SizedBox(width: Sp.x1),
            Text('已停止', style: context.text.bodySmall?.copyWith(color: p.text3)),
          ]),
        ),
    ];
    // 和卡片里的正文左缘对齐：图标键自带 8px 内边距，再补一点
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x1, left: Sp.x1),
      child: Row(children: [
        for (var i = 0; i < items.length; i++) FadeSlideIn(delay: Motion.stagger(i, from: 1), child: items[i]),
      ]),
    );
  }
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

class _ToolChip extends StatelessWidget {
  const _ToolChip(this.label);
  final String label;

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
            Text('$label…', style: context.text.bodySmall),
          ]),
        ),
      ),
    );
  }
}
