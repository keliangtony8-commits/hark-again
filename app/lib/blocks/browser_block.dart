// 云浏览器实时画面：可见时按节奏刷新截图（models/browser_view.dart screenInterval：操作中快、打开中中、看着慢，
// 只是看着 2 分钟后暂停，点一下继续）；点“接管”后点画面 = 点网页，底部输入框 = 键盘。
// 每个请求都带卡上的会话名（v1.26 按网站分会话）；卡头写网站名。block.live = 页面还在打开：没画面时显示“正在打开”并继续刷，不当作浏览器没开。
// v1.29 接管交还：block.handoff pending = 助手在等你（验证码、滑块、扫码）→ 自动进入接管、卡头下出“需要你来”条，
// 弄完点“完成，交还”（onForm(id, {})），做不了点“做不了”（onForm(id, null)）；结束后那一行小字说明结果。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../models/block.dart';
import '../models/browser_view.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import 'block_actions.dart';
import 'block_frame.dart';

class BrowserBlockView extends ConsumerStatefulWidget {
  const BrowserBlockView(this.block, {super.key});
  final BrowserBlock block;

  @override
  ConsumerState<BrowserBlockView> createState() => _BrowserBlockViewState();
}

class _BrowserBlockViewState extends ConsumerState<BrowserBlockView> {
  static const _aspect = 1280 / 800;
  Timer? _timer;
  int _tick = 0;
  bool _control = false, _broken = false, _paused = false;
  String? _replied; // 已答复过的接管 id（等服务器把卡改成 done/cancelled 之前不再显示按钮）
  Duration _idle = Duration.zero; // 只是看着多久了（按排过的帧累计：后台、测试里都准，不读墙钟）
  final _keys = TextEditingController();

  BrowserHandoff? get _handoff => widget.block.handoff;
  bool get _waiting => _handoff?.pending == true && _replied != _handoff!.id;

  @override
  void initState() {
    super.initState();
    if (_waiting) _control = true;
    _schedule();
  }

  @override
  void didUpdateWidget(BrowserBlockView old) {
    super.didUpdateWidget(old);
    final h = _handoff;
    if (h != null && h.pending && old.block.handoff?.id != h.id) {
      _control = true; // 助手在等你：直接进入接管
      HapticFeedback.mediumImpact();
    }
    if (old.block.live != widget.block.live || old.block.handoff?.state != h?.state) {
      if (!widget.block.live) _broken = false; // 打开完成：再试一次拿画面
      if (h != null && !h.pending) _control = false;
      _wake();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _keys.dispose();
    super.dispose();
  }

  void _schedule() {
    _timer?.cancel();
    final every = screenInterval(control: _control || _waiting, live: widget.block.live);
    _timer = Timer(every, () => _onTick(every));
  }

  void _onTick(Duration waited) {
    if (!mounted) return;
    _idle += waited;
    final pause = screenShouldPause(idle: _idle, control: _control, live: widget.block.live, pending: _waiting);
    if (pause) return setState(() => _paused = true); // 不再排下一帧，点一下继续
    if (!_broken && TickerMode.valuesOf(context).enabled) setState(() => _tick++);
    _schedule();
  }

  /// 有动静（点了、切了接管、卡片状态变了）：重置“只是看着”的计时，暂停中就恢复。
  void _wake() {
    _idle = Duration.zero;
    if (_paused) setState(() => _paused = false);
    _schedule();
  }

  Api get _api => ref.read(apiProvider);
  String get _session => widget.block.session;

  /// 还在打开时拿不到画面是正常的：不进“没打开”状态。
  bool get _opening => widget.block.live;

  void _tap(TapUpDetails d, BoxConstraints c) {
    if (_paused) return _wake();
    _wake();
    if (!_control) return;
    _api.post('/api/browser/mouse',
        {'x': d.localPosition.dx / c.maxWidth, 'y': d.localPosition.dy / (c.maxWidth / _aspect), 'session': _session});
  }

  Future<void> _sendKeys() async {
    _wake();
    final text = _keys.text;
    _keys.clear();
    await _api.post('/api/browser/keyboard',
        text.isEmpty ? {'key': 'Enter', 'session': _session} : {'text': text, 'key': 'Enter', 'session': _session});
  }

  void _toggle() {
    setState(() => _control = !_control);
    _wake();
  }

  void _answer(bool done) {
    final h = _handoff;
    final onForm = BlockActions.of(context)?.onForm;
    if (h == null || onForm == null) return;
    if (!onForm(h.id, done ? const {} : null, false)) {
      showToast(context, '还没连上，连上后再点一次');
      return;
    }
    setState(() {
      _replied = h.id;
      _control = false;
    });
    _wake();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final h = _handoff;
    final control = _control || _waiting;
    final line = h == null || h.pending ? '' : handoffStateLine(h);
    return BlockFrame(
      tone: control ? FrameTone.live : FrameTone.calm,
      padding: EdgeInsets.zero,
      clip: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x1, Sp.x2, Sp.x1),
          child: Row(children: [
            Icon(Icons.public_rounded, size: 18, color: p.text2),
            const SizedBox(width: Sp.x2),
            Flexible(
              child: Text(widget.block.site ?? '云浏览器',
                  style: context.text.labelLarge, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
            const SizedBox(width: Sp.x2),
            FadeSwitcher(child: !_broken && !_paused ? PulseDot(key: const ValueKey('on'), color: p.danger, size: 7) : const SizedBox(key: ValueKey('off'))),
            const Spacer(),
            TextButton.icon(
              onPressed: _waiting ? null : _toggle,
              icon: Icon(control ? Icons.pan_tool_rounded : Icons.pan_tool_outlined, size: 16),
              label: Text(controlLabel(control)),
            ),
          ]),
        ),
        RiseSwitcher(
          child: _waiting
              ? _HandoffBar(key: ValueKey(h!.id), reason: h.reason, onAnswer: BlockActions.of(context)?.onForm == null ? null : _answer)
              : line.isNotEmpty
                  ? Padding(
                      key: ValueKey('line-${h!.id}-${h.state}'),
                      padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x2),
                      child: Text(line, style: context.text.bodySmall?.copyWith(color: p.text2)),
                    )
                  : null,
        ),
        LayoutBuilder(
          builder: (_, c) => GestureDetector(
            onTapUp: (d) => _tap(d, c),
            excludeFromSemantics: true,
            child: Semantics(
              label: browserScreenSemantics(control: control, paused: _paused, site: widget.block.site),
              image: true,
              child: AspectRatio(aspectRatio: _aspect, child: _screen(context)),
            ),
          ),
        ),
        AnimatedSize(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          child: control
              ? Padding(
                  padding: const EdgeInsets.all(Sp.x2),
                  child: Row(children: [
                    Expanded(
                      child: TextField(
                        controller: _keys,
                        decoration: const InputDecoration(hintText: '先点画面里的输入框，再在这里打字', isDense: true),
                        onSubmitted: (_) => _sendKeys(),
                      ),
                    ),
                    IconButton.filled(onPressed: _sendKeys, tooltip: '发送按键', icon: const Icon(Icons.keyboard_return_rounded)),
                  ]),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }

  Widget _screen(BuildContext context) => Stack(fit: StackFit.expand, children: [
        _base(context),
        FadeSwitcher(
          child: _paused
              ? Container(
                  key: const ValueKey('paused'),
                  color: context.palette.scrim,
                  alignment: Alignment.center,
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.play_arrow_rounded, size: 18, color: context.palette.onInk),
                    const SizedBox(width: Sp.x1),
                    Text('画面已暂停，点一下继续', style: context.text.bodySmall?.copyWith(color: context.palette.onInk)),
                  ]),
                )
              : const SizedBox.shrink(key: ValueKey('live')),
        ),
      ]);

  Widget _base(BuildContext context) {
    if (_broken) {
      return InkWell(
        onTap: () {
          setState(() => _broken = false);
          _wake();
        },
        child: Container(
          color: context.tileFill,
          alignment: Alignment.center,
          child: Text('浏览器没打开或已休眠，点此重试', style: context.text.bodySmall),
        ),
      );
    }
    return Image.network(
      '${_api.fileUrl('/api/browser/screen')}&session=${Uri.encodeQueryComponent(_session)}&t=$_tick',
      excludeFromSemantics: true,
      fit: BoxFit.cover,
      gaplessPlayback: true, // 刷新时不闪白
      errorBuilder: (_, _, _) {
        if (_opening) {
          return Container(
            color: context.tileFill,
            alignment: Alignment.center,
            child: Text('正在打开${widget.block.site == null ? '网页' : ' ${widget.block.site}'}…', style: context.text.bodySmall),
          );
        }
        WidgetsBinding.instance.addPostFrameCallback((_) => mounted ? setState(() => _broken = true) : null);
        return Container(color: context.tileFill);
      },
    );
  }
}

/// “需要你来”条：一句话说要做什么 + 做不了 / 完成，交还。onAnswer 为空（只读场景）只显示说明。
class _HandoffBar extends StatelessWidget {
  const _HandoffBar({super.key, required this.reason, required this.onAnswer});
  final String reason;
  final void Function(bool done)? onAnswer;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      container: true,
      liveRegion: true,
      label: '$handoffTitle：$reason',
      child: Container(
        margin: const EdgeInsets.fromLTRB(Sp.x2, 0, Sp.x2, Sp.x2),
        padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x3, Sp.x2, Sp.x2),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.md)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          ExcludeSemantics(
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Icon(Icons.front_hand_rounded, size: 18, color: p.text),
              ),
              const SizedBox(width: Sp.x2),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(handoffTitle, style: context.text.labelLarge?.copyWith(fontWeight: Weights.title)),
                  const SizedBox(height: 2),
                  Text(reason, style: context.text.bodySmall?.copyWith(color: p.text2)),
                ]),
              ),
            ]),
          ),
          if (onAnswer != null)
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(onPressed: () => onAnswer!(false), child: const Text(handoffCancelLabel)),
              const SizedBox(width: Sp.x1),
              PillButton(label: handoffDoneLabel, primary: true, dense: true, onTap: () => onAnswer!(true)),
            ]),
        ]),
      ),
    );
  }
}
