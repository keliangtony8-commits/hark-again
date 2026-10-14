// 可复用的聊天区：消息列表 + 输入框。主聊天页和项目页都用它（projectId 区分）。
// 点一条消息 = 这条的时间开关（_timesShown，§I）；长按一条消息 = 它的动作菜单（MessageView）。
// 引用回复（§J）：长按 → “回复” → _quoting，输入框顶上出引用条，发出时随消息带 reply_to；气泡顶上的引用行点一下 = _reveal 回到原消息并闪一下。
// 编辑最后一条用户消息：长按气泡 → “编辑” → 输入框进入编辑态（顶部“编辑消息”条，返回键/叉号取消），
//   发送时走 ChatController.edit。编辑态只是界面状态，放在这里；那条消息不再可编辑（开始生成、换了对话）就自动退出。
// 定位（搜索命中）：ChatState.focus 指向的消息一进列表就取走 → 先回到底部，再一屏一屏往上找，直到它被建出来
//   （列表是懒加载、高度不定，没法直接算偏移），然后平滑滚到视口中间并 FlashHighlight 闪一下。
import 'package:flutter/material.dart';
import 'package:assistant/ui/brand_mark.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../blocks/block_actions.dart';
import '../../core/speech.dart';
import '../../core/workspace.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../models/message.dart';
import '../../models/reply_end.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../projects/save_reply.dart';
import 'chat_controller.dart';
import 'composer.dart';
import 'message_view.dart';
import 'open_conversation.dart';
import 'model_choice.dart';
import 'slash_actions.dart';

class ChatView extends ConsumerStatefulWidget {
  const ChatView({super.key, this.projectId = '', this.suggestions = const [], this.empty});
  final String projectId;
  final List<String> suggestions;

  /// 还没有消息时画什么（项目首屏 ProjectHome）；null = 通用的“今天想做点什么？”+ 建议。send = 发一条新消息。
  final Widget Function(BuildContext context, void Function(String text) send)? empty;

  @override
  ConsumerState<ChatView> createState() => _ChatViewState();
}

class _ChatViewState extends ConsumerState<ChatView> {
  final _scroll = ScrollController();
  EditDraft? _editing;

  /// 引用回复（§J）：长按菜单“回复”设上，发出 / ✕ / 换对话 / 进入编辑时清掉。界面状态，和编辑态同级。
  MessageQuote? _quoting;
  final _anchor = GlobalKey(); // 挂在要定位的那条消息上
  String? _target;

  /// §I（用户 17:45 定稿）：点哪条显示哪条的时间——每条各自开关，可同时开几条。会话内状态，不持久化；换对话清空。
  final Set<String> _timesShown = {};
  void _toggleTime(String id) {
    HapticFeedback.selectionClick();
    setState(() => _timesShown.contains(id) ? _timesShown.remove(id) : _timesShown.add(id));
  }

  int _flash = 0;
  bool _seeking = false;
  late final SpeechController _speech = ref.read(speechProvider.notifier); // dispose 里不能再用 ref

  /// 在 build 里发现有待定位的消息：下一帧取走并开始找（不在 build 里改状态）。
  void _maybeSeek(ChatState chat) {
    if (_seeking || chat.focus == null || !chat.messages.any((m) => m.id == chat.focus)) return;
    _seeking = true;
    SchedulerBinding.instance.addPostFrameCallback((_) async {
      final id = mounted ? ref.read(chatProvider(widget.projectId).notifier).takeFocus() : null;
      try {
        if (id != null) await _reveal(id);
      } finally {
        _seeking = false;
      }
    });
  }

  Future<void> _reveal(String id) async {
    final glide = context.motion(Motion.slow);
    setState(() => _target = id);
    await SchedulerBinding.instance.endOfFrame;
    if (!_scroll.hasClients) return;
    _scroll.jumpTo(0); // reverse 列表：0 = 最新一条；目标一定在上方
    for (var i = 0; i < Layout.seekPagesMax && mounted; i++) {
      await SchedulerBinding.instance.endOfFrame;
      final ctx = _anchor.currentContext;
      if (ctx != null) {
        if (!ctx.mounted) return;
        await Scrollable.ensureVisible(ctx, alignment: 0.5, duration: glide, curve: Motion.ease);
        if (mounted) setState(() => _flash++);
        return;
      }
      if (!_scroll.hasClients) return;
      final pos = _scroll.position;
      if (pos.pixels >= pos.maxScrollExtent) return; // 到顶还没有：不在这个列表里
      _scroll.jumpTo((pos.pixels + pos.viewportDimension * 0.9).clamp(0, pos.maxScrollExtent));
    }
  }

  /// 往上翻离最新一条超过 Layout.followSlack：输入胶囊上方出“回到最新”（v2.79，= 网页 useStickToBottom）。
  /// reverse 列表：offset 0 = 最新一条，所以“在底部” = offset 小；只在跨过阈值时 setState。
  bool _away = false;
  void _onScroll() {
    final away = _scroll.hasClients && _scroll.offset > Layout.followSlack;
    if (away != _away) setState(() => _away = away);
  }

  /// 回到最新：平滑滚回 0（减弱动效时直接跳）。自己发消息也走这里。
  void _toLatest() {
    if (!_scroll.hasClients || _scroll.offset == 0) return;
    final d = context.motion(Motion.slow);
    d == Duration.zero ? _scroll.jumpTo(0) : _scroll.animateTo(0, duration: d, curve: Motion.ease);
  }

  @override
  void initState() {
    super.initState();
    _speech; // 先取好，卸载时用
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _speech.stop(); // 离开聊天区就别再读了
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider(widget.projectId));
    final ctl = ref.read(chatProvider(widget.projectId).notifier);
    ref.listen(chatProvider(widget.projectId).select((s) => s.activeId), (_, _) {
      _speech.stop(); // 换对话 = 停读
      if (_timesShown.isNotEmpty || _quoting != null) {
        setState(() {
          _timesShown.clear();
          _quoting = null;
        });
      }
      // 换对话 = 回到最新一条：不然上一个对话往回翻的位置会带过来，新对话的卡片按钮压在输入胶囊下面
      SchedulerBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scroll.hasClients && _scroll.offset != 0) _scroll.jumpTo(0);
      });
    });
    final editing = _editing?.id == chat.editableId ? _editing : null;
    final inset = MediaQuery.paddingOf(context).top; // 有 AppBar 时为 0；主聊天里 = 状态栏 + 浮动顶栏
    _maybeSeek(chat);

    final composer = PopScope(
      canPop: editing == null, // 安卓返回键先退出编辑，不退页面
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) setState(() => _editing = null);
      },
      child: Composer(
        busy: chat.busy,
        streaming: chat.streaming,
        canSteer: chat.canSteer,
        onStop: chat.canStop ? ctl.stop : null,
        editing: editing,
        onCancelEdit: () => setState(() => _editing = null),
        quoting: editing == null ? _quoting : null,
        onCancelQuote: () => setState(() => _quoting = null),
        accessory: ModelChoice(scope: widget.projectId),
        workspace: workspaceOf(widget.projectId),
        onSlash: (call, files) => runSlash(context, ref, widget.projectId, call, files),
        onSend: (text, files) {
          if (editing != null) {
            ctl.edit(text);
            setState(() => _editing = null);
          } else {
            ctl.send(text, files: files, quote: _quoting);
            if (_quoting != null) setState(() => _quoting = null);
          }
          _toLatest(); // 自己发的消息一定看得见
        },
      ),
    );

    return BlockActions(
      onApproval: ctl.replyApproval,
      onApprovalOption: (id, option) => ctl.replyApproval(id, true, option),
      onForm: ctl.replyForm,
      onJobSettled: ctl.refreshActive,
      onUndoChanges: ctl.undoChanges,
      onFollowUp: ctl.followUp,
      onOpenConversation: (id, projectId) => openConversation(context, ref, id, projectId: projectId),
      // 设计 v2：列表铺满整个聊天区，上面从浮动顶栏下滚过、下面从输入胶囊下滚过；
      // 让位都读 MediaQuery.padding（顶 = ShellPage，底 = FloatingFooter 量出的胶囊高度）。离线条浮在让位线下方，不推动列表。
      child: FloatingFooter(
        footer: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          RiseSwitcher(child: _away && chat.messages.isNotEmpty ? JumpLatest(key: const ValueKey('latest'), onTap: _toLatest) : null),
          RiseSwitcher(child: chat.error == null ? null : _ErrorBar(key: ValueKey(chat.error), text: chat.error!, onRetry: chat.canRegenerate && chat.messages.last.isUser ? ctl.regenerate : null)),
          composer,
        ]),
        child: Builder(builder: (context) {
          final bottom = MediaQuery.paddingOf(context).bottom;
          return Stack(children: [
            Positioned.fill(
              child: chat.messages.isEmpty
                  ? Padding(padding: EdgeInsets.only(top: inset, bottom: bottom), child: widget.empty?.call(context, (s) => ctl.send(s)) ?? _Empty(suggestions: widget.suggestions, onPick: (s) => ctl.send(s)))
                  : Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: Layout.contentMax),
                        // reverse：新消息贴底，键盘弹出也不用手动滚动
                        child: ListView.separated(
                          controller: _scroll,
                          reverse: true,
                          padding: EdgeInsets.fromLTRB(Sp.x4, Layout.topFadeRamp + inset, Sp.x4, Sp.x2 + bottom),
                          itemCount: chat.messages.length,
                          separatorBuilder: (_, _) => const SizedBox(height: Sp.x4),
                          itemBuilder: (_, i) {
                            final idx = chat.messages.length - 1 - i;
                            final m = chat.messages[idx];
                            final regen = i == 0 && !m.isUser && chat.canRegenerate; // 只有最后一条回复能重新生成
                            final target = m.id == _target;
                            // 点这条（气泡 / 回复正文 / 卡片空白处）= 这条的时间开关；卡片里的按钮 / 链接是更内层的手势，照旧先赢
                            final row = FlashHighlight(
                              key: target ? _anchor : ValueKey(m.id),
                              play: target ? _flash : 0,
                              child: GestureDetector(
                                onTap: m.pending ? null : () => _toggleTime(m.id),
                                child: MessageView(m,
                                  key: ValueKey(m.id),
                                  onResend: ctl.resend,
                                  onDiscard: ctl.discard,
                                  onRegenerate: regen ? ctl.regenerate : null,
                                  onContinue: regen && m.end.continuable ? () => ctl.send(continueText) : null,
                                  onSave: m.isUser || m.pending ? null : () => saveReplyToProject(context, ref, messageId: m.id, projectId: widget.projectId),
                                  onRate: m.isUser || m.pending ? null : (kind, {note}) => ctl.rate(m.id, kind, note: note),
                                  showTime: _timesShown.contains(m.id),
                                  // 回复这条：已落库（有服务器 id）、生成完的消息才能引用
                                  onQuote: m.pending || m.unsent || m.id.startsWith(ChatController.localPrefix)
                                      ? null
                                      : () => setState(() {
                                            _quoting = MessageQuote.of(m);
                                            _editing = null;
                                          }),
                                  onJumpQuote: _reveal,
                                  onEdit: m.id == chat.editableId
                                      ? () => setState(() {
                                            _editing = EditDraft.of(m);
                                            _quoting = null;
                                          })
                                      : null),
                              ),
                            );
                            // 跨天处在消息上方插一行日期（今天 / 昨天 / 10月9日 星期五）
                            if (!startsNewDay(chat.messages, idx)) return row;
                            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [DaySeparator(m.createdAt!), row]);
                          },
                        ),
                      ),
                    ),
            ),
            Positioned(
              top: inset,
              left: 0,
              right: 0,
              child: SlideDownSwitcher(
                child: chat.showOffline
                    ? OfflineBar(
                        key: const ValueKey('offline'),
                        onRetry: ctl.sync,
                        // 断线时还在生成 = 服务器支持续传，回答在那边接着写（chat_controller 续传）
                        text: chat.offline
                            ? '离线 · 显示的是上次同步的内容'
                            : chat.streaming
                                ? '连接断开 · 回答还在服务器上继续写，连上后接着显示'
                                : '连接断开 · 消息会在连上后自动发出',
                      )
                    : null,
              ),
            ),
          ]);
        }),
      ),
    );
  }
}

/// 输入胶囊上方的“↓ 回到最新”小玻璃胶囊（往上翻看前文时出现，点了平滑回到最新一条）。
class JumpLatest extends StatelessWidget {
  const JumpLatest({super.key, required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Center(
        child: Semantics(
          button: true,
          label: '回到最新',
          excludeSemantics: true,
          child: Pressable(
            onTap: onTap,
            scale: 0.96,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: A11y.minTap),
              child: Center(
                widthFactor: 1,
                child: GlassSurface(
                  radius: Radii.full,
                  blur: true, // 浮在滚动的文字上：真模糊才读得清
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x2),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.arrow_downward_rounded, size: Fs.md, color: p.text2),
                    const SizedBox(width: Sp.x1),
                    Text('回到最新', style: context.text.labelMedium?.copyWith(color: p.text2)),
                  ]),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 输入胶囊上方的错误条：玻璃底（下面是滚动的消息，要读得清），上一轮失败时带“重试”。
class _ErrorBar extends StatelessWidget {
  const _ErrorBar({super.key, required this.text, this.onRetry});
  final String text;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x2, Sp.x3, 0),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: Layout.contentMax),
          child: GlassSurface(
            blur: true,
            radius: Radii.card,
            borderColor: p.danger.withValues(alpha: 0.4),
            padding: const EdgeInsets.only(left: Sp.x4),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: A11y.minTap),
              child: Row(children: [
                Icon(Icons.error_outline_rounded, size: 18, color: p.danger),
                const SizedBox(width: Sp.x2),
                Expanded(child: Text(text, style: context.text.bodySmall?.copyWith(color: p.danger))),
                if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('重试')) else const SizedBox(width: Sp.x3),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// 离线条：告诉用户眼前是缓存或长连接断了，点“重试”立刻重连并重新同步。待发送的消息由 chat_controller 的发件箱在连上后送出。
class OfflineBar extends StatefulWidget {
  const OfflineBar({super.key, required this.onRetry, this.text = '离线 · 显示的是上次同步的内容'});
  final Future<void> Function() onRetry;
  final String text;

  @override
  State<OfflineBar> createState() => _OfflineBarState();
}

class _OfflineBarState extends State<OfflineBar> {
  bool _busy = false;

  Future<void> _retry() async {
    setState(() => _busy = true);
    try {
      await widget.onRetry();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      liveRegion: true,
      child: Container(
        margin: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, 0),
        padding: const EdgeInsets.only(left: Sp.x3),
        decoration: BoxDecoration(
          color: p.warning.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(Radii.full),
        ),
        child: Row(children: [
          Icon(Icons.cloud_off_rounded, size: 18, color: p.warning),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text(widget.text, style: context.text.bodySmall?.copyWith(color: p.text2))),
          AnimatedSwitcher(
            duration: context.motion(Motion.fast),
            child: _busy
                ? const SizedBox(width: A11y.minTap, height: A11y.minTap, child: Center(child: TypingDots()))
                : TextButton(onPressed: _retry, child: const Text('重试')),
          ),
        ]),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.suggestions, required this.onPick});
  final List<String> suggestions;
  final void Function(String) onPick;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(Sp.x5),
        child: Column(children: [
          const FadeSlideIn(child: BrandMark()),
          const SizedBox(height: Sp.x3),
          FadeSlideIn(delay: Motion.stagger(2), child: Text('今天想做点什么？', style: context.text.titleLarge)),
          const SizedBox(height: Sp.x5),
          Wrap(
            spacing: Sp.x2,
            runSpacing: Sp.x2,
            alignment: WrapAlignment.center,
            children: [
              for (var i = 0; i < suggestions.length; i++)
                FadeSlideIn(
                  delay: Motion.stagger(i, from: 3),
                  child: GlassChip(label: suggestions[i], onTap: () => onPick(suggestions[i])),
                ),
            ],
          ),
        ]),
      ),
    );
  }
}
