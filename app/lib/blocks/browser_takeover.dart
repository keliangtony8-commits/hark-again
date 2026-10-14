// v2.82 浏览器接管页（docs/home-redesign.md §H）：接管 = 一个全屏页面，聊天卡只做预览 + 入口。
// 手势（坐标换算都在 models/browser_view.dart）：
//   点一下 = 点网页；单指拖动 / 鼠标滚轮 = 滚网页；双指 = 放大平移画面（只是看得清，不动网页）；
//   长按后拖动 = 按住鼠标拖（滑块验证码）：down → move… → up。拖动/滚动攒 Timing.takeoverInput 发一次。
// 底栏：后退、刷新、打字框（提交 = 把字打进网页；空着提交 = 回车）。助手在等你（handoff pending）时顶部出“需要你来”条，
// 完成/做不了走卡片传进来的 onAnswer（和卡上的条是同一个 HandoffBar），答完关页。
// 画面每 Timing.screenFast 刷一帧；页面开着时卡片自己不刷（BrowserBlockView 负责）。
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
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

/// 推出接管页（根导航，盖住底栏和抽屉）。[block] 随卡片更新（handoff 状态变了页里跟着变）。
/// [onAnswer] 为空 = 只读场景，没有完成/做不了按钮；返回 false = 没连上，按钮留着。
Future<void> openBrowserTakeover(BuildContext context,
    {required ValueListenable<BrowserBlock> block, bool Function(bool done)? onAnswer}) {
  HapticFeedback.mediumImpact();
  return Navigator.of(context, rootNavigator: true)
      .push(riseRoute<void>(context, (_) => BrowserTakeoverPage(block: block, onAnswer: onAnswer)));
}

class BrowserTakeoverPage extends ConsumerStatefulWidget {
  const BrowserTakeoverPage({super.key, required this.block, this.onAnswer});
  final ValueListenable<BrowserBlock> block;
  final bool Function(bool done)? onAnswer;

  @override
  ConsumerState<BrowserTakeoverPage> createState() => _BrowserTakeoverPageState();
}

class _BrowserTakeoverPageState extends ConsumerState<BrowserTakeoverPage> {
  Timer? _frames, _flush;
  int _tick = 0;
  bool _touched = false; // 做过一次手势 → 说明那句收起
  final _keys = TextEditingController();

  // 画面放大平移（左上角为原点）
  double _scale = 1, _startScale = 1;
  Offset _pan = Offset.zero, _focalScene = Offset.zero;
  bool _pinching = false;

  // 攒着没发的滚动 / 拖动
  double _scrollDy = 0, _scrollDx = 0;
  Offset? _scrollAt, _dragTo;

  BrowserBlock get _b => widget.block.value;
  Api get _api => ref.read(apiProvider);

  @override
  void initState() {
    super.initState();
    _frames = Timer.periodic(Timing.screenFast, (_) {
      if (mounted && TickerMode.valuesOf(context).enabled) setState(() => _tick++);
    });
  }

  @override
  void dispose() {
    _frames?.cancel();
    _flush?.cancel();
    _keys.dispose();
    super.dispose();
  }

  Future<void> _post(String path, Map<String, Object?> body) async {
    try {
      await _api.post(path, {...body, 'session': _b.session});
    } catch (_) {
      if (mounted) showToast(context, '没发出去，再试一次');
      return;
    }
    if (mounted) setState(() => _tick++); // 操作完马上拿一帧，不等下一拍
  }

  void _touch() {
    if (!_touched) setState(() => _touched = true);
  }

  // —— 点、滚、拖 ——

  void _tap(TapUpDetails d, Size box) {
    _touch();
    final at = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan);
    if (at != null) _post('/api/browser/mouse', {'x': at.dx, 'y': at.dy});
  }

  void _scaleStart(ScaleStartDetails d) {
    _touch();
    _pinching = d.pointerCount >= 2;
    _startScale = _scale;
    _focalScene = (d.localFocalPoint - _pan) / _scale;
  }

  void _scaleUpdate(ScaleUpdateDetails d, Size box) {
    if (d.pointerCount >= 2 || _pinching) {
      if (d.pointerCount < 2) return; // 双指松开一根：不突然变成滚网页
      _pinching = true;
      final s = (_startScale * d.scale).clamp(1.0, takeoverZoomMax);
      setState(() {
        _scale = s;
        _pan = takeoverClampPan(d.localFocalPoint - _focalScene * s, box, s);
      });
      return;
    }
    _scrollDy += takeoverScrollPixels(d.focalPointDelta.dy, box, _scale);
    _scrollDx += takeoverScrollPixels(d.focalPointDelta.dx, box, _scale); // contain 不变形：横竖同一个比例
    _scrollAt = takeoverPoint(d.localFocalPoint, box, scale: _scale, pan: _pan) ?? _scrollAt;
    _schedule();
  }

  void _scaleEnd(ScaleEndDetails _) {
    _pinching = false;
    _sendNow();
  }

  void _wheel(PointerSignalEvent e, Size box) {
    if (e is! PointerScrollEvent) return;
    _touch();
    _scrollDy += e.scrollDelta.dy;
    _scrollDx += e.scrollDelta.dx;
    _scrollAt = takeoverPoint(e.localPosition, box, scale: _scale, pan: _pan) ?? _scrollAt;
    _schedule();
  }

  void _dragStart(LongPressStartDetails d, Size box) {
    _touch();
    final at = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan);
    if (at == null) return;
    HapticFeedback.selectionClick();
    _dragTo = null;
    _post('/api/browser/mouse', {'x': at.dx, 'y': at.dy, 'kind': 'down'});
  }

  void _dragMove(LongPressMoveUpdateDetails d, Size box) {
    _dragTo = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan) ?? _dragTo;
    _schedule();
  }

  void _dragEnd(LongPressEndDetails d, Size box) {
    _flush?.cancel();
    final at = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan) ?? _dragTo;
    _dragTo = null;
    if (at != null) _post('/api/browser/mouse', {'x': at.dx, 'y': at.dy, 'kind': 'up'});
  }

  void _schedule() => _flush ??= Timer(Timing.takeoverInput, _sendNow);

  void _sendNow() {
    _flush?.cancel();
    _flush = null;
    if (_dragTo != null) {
      final to = _dragTo!;
      _api.post('/api/browser/mouse', {'x': to.dx, 'y': to.dy, 'kind': 'move', 'session': _b.session}).ignore();
    }
    if (_scrollDy.abs() >= 1 || _scrollDx.abs() >= 1) {
      final at = _scrollAt ?? const Offset(0.5, 0.5);
      _post('/api/browser/scroll', {'x': at.dx, 'y': at.dy, 'dx': _scrollDx.roundToDouble(), 'dy': _scrollDy.roundToDouble()});
      _scrollDx = _scrollDy = 0;
    }
  }

  // —— 底栏 ——

  Future<void> _sendKeys() async {
    final text = _keys.text;
    _keys.clear();
    await _post('/api/browser/keyboard', text.isEmpty ? {'key': 'Enter'} : {'text': text});
  }

  void _answer(bool done) {
    final onAnswer = widget.onAnswer;
    if (onAnswer == null) return;
    if (!onAnswer(done)) {
      showToast(context, '还没连上，连上后再点一次');
      return;
    }
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        child: ValueListenableBuilder<BrowserBlock>(
          valueListenable: widget.block,
          builder: (context, b, _) {
            final h = b.handoff;
            final line = h == null || h.pending ? '' : handoffStateLine(h);
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, Sp.x2),
                child: Row(children: [
                  GlassIconButton(icon: Icons.close_rounded, tooltip: '关闭', onTap: () => Navigator.of(context).maybePop()),
                  const SizedBox(width: Sp.x3),
                  Flexible(
                    child: Text(b.site ?? '云浏览器', style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  const SizedBox(width: Sp.x2),
                  PulseDot(color: p.danger, size: 7),
                ]),
              ),
              RiseSwitcher(
                child: h != null && h.pending
                    ? HandoffBar(key: ValueKey(h.id), reason: h.reason, onAnswer: widget.onAnswer == null ? null : _answer)
                    : line.isNotEmpty
                        ? Padding(
                            key: ValueKey('line-${h!.id}-${h.state}'),
                            padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x2),
                            child: Text(line, style: context.text.bodySmall?.copyWith(color: p.text2)),
                          )
                        : null,
              ),
              Expanded(child: _stage(context, b)),
              AnimatedOpacity(
                opacity: _touched ? 0 : 1,
                duration: context.motion(Motion.base),
                child: Padding(
                  padding: const EdgeInsets.only(top: Sp.x2),
                  child: Text(takeoverHint, textAlign: TextAlign.center, style: context.text.bodySmall?.copyWith(color: p.text2)),
                ),
              ),
              _bottomBar(context),
            ]);
          },
        ),
      ),
    );
  }

  Widget _stage(BuildContext context, BrowserBlock b) => LayoutBuilder(builder: (context, c) {
        final box = c.biggest;
        return Listener(
          onPointerSignal: (e) => _wheel(e, box),
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            excludeFromSemantics: true,
            onTapUp: (d) => _tap(d, box),
            onScaleStart: _scaleStart,
            onScaleUpdate: (d) => _scaleUpdate(d, box),
            onScaleEnd: _scaleEnd,
            onLongPressStart: (d) => _dragStart(d, box),
            onLongPressMoveUpdate: (d) => _dragMove(d, box),
            onLongPressEnd: (d) => _dragEnd(d, box),
            child: Semantics(
              label: browserScreenSemantics(takeover: true, paused: false, site: b.site),
              image: true,
              child: ClipRect(
                child: Transform(
                  transform: Matrix4.translationValues(_pan.dx, _pan.dy, 0)..multiply(Matrix4.diagonal3Values(_scale, _scale, 1)),
                  child: SizedBox.fromSize(
                    size: box,
                    child: Center(
                      child: AspectRatio(
                        aspectRatio: browserAspect,
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(Radii.inner),
                          child: Image.network(
                            '${_api.fileUrl('/api/browser/screen')}&session=${Uri.encodeQueryComponent(b.session)}&t=$_tick',
                            excludeFromSemantics: true,
                            fit: BoxFit.cover,
                            gaplessPlayback: true,
                            errorBuilder: (_, _, _) => Container(
                              color: context.tileFill,
                              alignment: Alignment.center,
                              child: Text(b.live ? '正在打开…' : '画面还没来，稍等', style: context.text.bodySmall),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
      });

  Widget _bottomBar(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, Sp.x3),
        child: GlassSurface(
          blur: true,
          radius: Radii.full,
          padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
          child: Row(children: [
            IconButton(tooltip: '后退', onPressed: () => _post('/api/browser/nav', {'action': 'back'}), icon: const Icon(Icons.arrow_back_rounded)),
            IconButton(tooltip: '刷新', onPressed: () => _post('/api/browser/nav', {'action': 'reload'}), icon: const Icon(Icons.refresh_rounded)),
            Expanded(
              child: TextField(
                controller: _keys,
                textInputAction: TextInputAction.send,
                decoration: const InputDecoration(
                  hintText: takeoverKeysHint,
                  isDense: true,
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  filled: false,
                ),
                onSubmitted: (_) => _sendKeys(),
              ),
            ),
            IconButton(tooltip: '发到网页', onPressed: _sendKeys, icon: const Icon(Icons.keyboard_return_rounded)),
          ]),
        ),
      );
}

/// “需要你来”条：一句话说要做什么 + 做不了 / 完成，交还。卡片和接管页共用这一个。onAnswer 为空（只读场景）只显示说明。
class HandoffBar extends StatelessWidget {
  const HandoffBar({super.key, required this.reason, required this.onAnswer});
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
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
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
