// v2.91 §N 项目对话的标题药丸：浮在标题栏下方，写这段对话的总结标题（服务器 conversations.title，和列表同一个值）。
// 标题栏写的是项目（“📚 考研复习”），药丸写的是这段对话在谈什么——两层不重复。
// 什么时候浮出：进入一段已有对话；往上翻看历史累计超过 Motion.pillReveal；标题被重新总结（旧标题非空且变了）。
// 什么时候收起：往下滑超过 Motion.pillHide、停下 Timing.pillHold、回到最新一条（reverse 列表 offset 0）。
// 新建对话发第一句时不弹（还没有标题），占位标题出现也不弹（旧标题为空）。
// 性能：显隐只在 ValueNotifier 里，滚动不触发 ChatView 的 setState；药丸自己一层 RepaintBoundary。动效见 ui/motion.dart DropIn。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';

class TitlePill extends StatefulWidget {
  const TitlePill({super.key, required this.scroll, required this.conversationId, required this.title});

  /// 聊天列表的滚动（reverse：offset 0 = 最新一条，往上翻 offset 变大）。
  final ScrollController scroll;
  final String? conversationId;
  final String title;

  static const maxWidth = 280.0;

  @override
  State<TitlePill> createState() => TitlePillState();
}

class TitlePillState extends State<TitlePill> {
  /// 测试读它：药丸现在该不该显示。
  final shown = ValueNotifier(false);
  Timer? _idle;
  double _last = 0, _up = 0, _down = 0;
  bool _settling = false; // 换对话那一帧 ChatView 会把列表跳回最新：这一跳不算“回到底部”

  @override
  void initState() {
    super.initState();
    widget.scroll.addListener(_onScroll);
    _sync();
    if (widget.conversationId != null && widget.title.isNotEmpty) _enter();
  }

  @override
  void didUpdateWidget(TitlePill oldWidget) {
    final old = oldWidget;
    super.didUpdateWidget(old);
    if (old.scroll != widget.scroll) {
      old.scroll.removeListener(_onScroll);
      widget.scroll.addListener(_onScroll);
      _sync();
    }
    if (old.conversationId != widget.conversationId) {
      _up = _down = 0;
      if (widget.conversationId != null && widget.title.isNotEmpty) {
        _enter();
      } else {
        _hide();
      }
    } else if (old.title != widget.title && old.title.isNotEmpty && widget.title.isNotEmpty) {
      _show(); // 话题变了、标题被重新总结：浮出来让你看到新名字
    }
  }

  @override
  void dispose() {
    _idle?.cancel();
    widget.scroll.removeListener(_onScroll);
    shown.dispose();
    super.dispose();
  }

  void _sync() => _last = widget.scroll.hasClients ? widget.scroll.offset : 0;

  void _enter() {
    _settling = true;
    _show();
    SchedulerBinding.instance.addPostFrameCallback((_) {
      _settling = false;
      if (mounted) _sync();
    });
  }

  void _show() {
    shown.value = true;
    _arm();
  }

  void _hide() {
    _idle?.cancel();
    shown.value = false;
  }

  /// 停下 Timing.pillHold 后收起；每次滚动重新计时。
  void _arm() {
    _idle?.cancel();
    _idle = Timer(Timing.pillHold, _hide);
  }

  void _onScroll() {
    if (!widget.scroll.hasClients) return;
    final o = widget.scroll.offset;
    final d = o - _last;
    _last = o;
    if (_settling || d == 0) return;
    if (o <= 0.5) {
      _up = _down = 0;
      _hide(); // 回到最新一条
      return;
    }
    if (d > 0) {
      _down = 0;
      _up += d;
      if (_up > Motion.pillReveal) shown.value = true; // 往上翻看历史
    } else {
      _up = 0;
      _down -= d;
      if (_down > Motion.pillHide) {
        _hide(); // 往下滑
        return;
      }
    }
    if (shown.value) _arm();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return RepaintBoundary(
      child: ValueListenableBuilder<bool>(
        valueListenable: shown,
        builder: (_, on, child) => DropIn(shown: on && widget.title.isNotEmpty, child: child!),
        child: Semantics(
          label: '对话：${widget.title}',
          excludeSemantics: true,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: TitlePill.maxWidth),
            child: GlassSurface(
              radius: Radii.full,
              blur: true, // 浮在滚动的文字上：真模糊才读得清
              padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x2),
              child: Text(widget.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.text.labelLarge?.copyWith(color: p.text, height: 1.2)),
            ),
          ),
        ),
      ),
    );
  }
}
