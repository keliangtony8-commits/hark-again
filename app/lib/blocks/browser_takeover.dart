// v2.82 浏览器接管页（docs/home-redesign.md §H）：接管 = 一个全屏页面，聊天卡只做预览 + 入口。
// 手势（坐标换算都在 models/browser_view.dart）：
//   点一下 = 点网页（带真实按住时长 hold：手指按下→抬起的时间，服务端照这个时长按住，browser/live.py）；
//   单指拖动 / 鼠标滚轮 = 滚网页；双指 = 放大平移画面（只是看得清，不动网页）；
//   长按后拖动 = 按住鼠标拖（滑块验证码）：down → move… → up。外接鼠标没按住时移动 = 悬停（move）。
//   拖动/悬停/滚动攒 Timing.takeoverInput 发一次。
// 底栏：后退、刷新、打字框（提交 = 把字打进网页；空着提交 = 回车）。助手在等你（handoff pending）时顶部出“需要你来”条，
// 完成/做不了走卡片传进来的 onAnswer（和卡上的条是同一个 HandoffBar），答完关页。
// v2.89 §M：画面和输入走卡片的同一条实时连接（BrowserLive，推流，不再轮询截图、不再一次操作一个 HTTP）；
// 页面开着时 hold 住连接，并按“画面宽 × 放大倍数”报宽度（放大看得清）。
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/block.dart';
import '../models/browser_view.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import 'browser_block.dart' show LiveScreen;
import 'browser_live.dart';
import '../ui/haptics.dart';

/// 推出接管页（根导航，盖住底栏和抽屉）。[block] 随卡片更新（handoff 状态变了页里跟着变）。
/// [onAnswer] 为空 = 只读场景，没有完成/做不了按钮；返回 false = 没连上，按钮留着。
Future<void> openBrowserTakeover(BuildContext context,
    {required ValueListenable<BrowserBlock> block, required BrowserLive live, bool Function(bool done)? onAnswer}) {
  Haptics.press();
  return Navigator.of(context, rootNavigator: true)
      .push(riseRoute<void>(context, (_) => BrowserTakeoverPage(block: block, live: live, onAnswer: onAnswer)));
}

class BrowserTakeoverPage extends ConsumerStatefulWidget {
  const BrowserTakeoverPage({super.key, required this.block, required this.live, this.onAnswer});
  final ValueListenable<BrowserBlock> block;
  final BrowserLive live;
  final bool Function(bool done)? onAnswer;

  @override
  ConsumerState<BrowserTakeoverPage> createState() => _BrowserTakeoverPageState();
}

class _BrowserTakeoverPageState extends ConsumerState<BrowserTakeoverPage> {
  Timer? _flush;
  bool _touched = false; // 做过一次手势 → 说明那句收起
  final _keys = TextEditingController();

  // 画面放大平移（左上角为原点）
  double _scale = 1, _startScale = 1;
  Offset _pan = Offset.zero, _focalScene = Offset.zero;
  bool _pinching = false;

  // 攒着没发的滚动 / 拖动或悬停的指针位置
  double _scrollDy = 0, _scrollDx = 0;
  Offset? _scrollAt, _moveTo;
  Duration? _downAt, _upAt; // 原始指针按下 / 抬起的时刻（Listener 先于手势竞技场收到，tap 回调时两头都已记下）

  BrowserLive get _live => widget.live;

  @override
  void initState() {
    super.initState();
    _live.hold();
  }

  @override
  void dispose() {
    _flush?.cancel();
    _keys.dispose();
    _live.release();
    super.dispose();
  }

  /// 发一条接管输入（格式见 docs/protocol.md）；没连上 → 提示一次，画面上也写着“正在重连…”。
  void _send(Map<String, Object?> m) {
    if (!_live.send(m) && mounted) showToast(context, '画面未连接，请稍后重试');
  }

  void _touch() {
    if (!_touched) setState(() => _touched = true);
  }

  // —— 点、滚、拖 ——

  void _tap(TapUpDetails d, Size box) {
    _touch();
    final at = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan);
    if (at == null) return;
    _moveTo = null; // 还没发的悬停不能晚于这次点
    final hold = takeoverHoldMs(_downAt, _upAt);
    _send({'t': 'mouse', 'kind': 'click', 'x': at.dx, 'y': at.dy, 'hold': ?hold});
  }

  void _hover(PointerHoverEvent e, Size box) {
    if (e.kind != PointerDeviceKind.mouse) return; // 只有鼠标会悬停；触控笔悬停不当鼠标移动
    _moveTo = takeoverPoint(e.localPosition, box, scale: _scale, pan: _pan) ?? _moveTo;
    if (_moveTo != null) _schedule();
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
    Haptics.tap();
    _moveTo = null;
    _send({'t': 'mouse', 'kind': 'down', 'x': at.dx, 'y': at.dy});
  }

  void _dragMove(LongPressMoveUpdateDetails d, Size box) {
    _moveTo = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan) ?? _moveTo;
    _schedule();
  }

  void _dragEnd(LongPressEndDetails d, Size box) {
    _flush?.cancel();
    final at = takeoverPoint(d.localPosition, box, scale: _scale, pan: _pan) ?? _moveTo;
    _moveTo = null;
    if (at != null) _send({'t': 'mouse', 'kind': 'up', 'x': at.dx, 'y': at.dy});
  }

  void _schedule() => _flush ??= Timer(Timing.takeoverInput, _sendNow);

  void _sendNow() {
    _flush?.cancel();
    _flush = null;
    if (_moveTo != null) {
      final to = _moveTo!;
      _live.send({'t': 'mouse', 'kind': 'move', 'x': to.dx, 'y': to.dy});
    }
    if (_scrollDy.abs() >= 1 || _scrollDx.abs() >= 1) {
      final at = _scrollAt ?? const Offset(0.5, 0.5);
      _send({'t': 'wheel', 'x': at.dx, 'y': at.dy, 'dx': _scrollDx.roundToDouble(), 'dy': _scrollDy.roundToDouble()});
      _scrollDx = _scrollDy = 0;
    }
  }

  // —— 底栏 ——

  void _sendKeys() {
    final text = _keys.text;
    _keys.clear();
    _send(text.isEmpty ? {'t': 'key', 'key': 'Enter'} : {'t': 'text', 'text': text});
  }

  void _answer(bool done) {
    final onAnswer = widget.onAnswer;
    if (onAnswer == null) return;
    if (!onAnswer(done)) {
      showToast(context, '尚未连接，连接后请重试');
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
      // 关闭钮和底部操作条共享一次取背景（两者不重叠、底下只有页底色；关闭钮先画、它不淡入，规则见 ui/glass.dart 文件头）
      body: SafeArea(
        child: BlurGroup(
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
      ),
    );
  }

  Widget _stage(BuildContext context, BrowserBlock b) => LayoutBuilder(builder: (context, c) {
        final box = c.biggest;
        _live.view(takeoverFit(box).width * _scale * MediaQuery.devicePixelRatioOf(context)); // 放大了要更清楚的帧
        return Listener(
          onPointerSignal: (e) => _wheel(e, box),
          onPointerDown: (e) => _downAt = e.timeStamp,
          onPointerUp: (e) => _upAt = e.timeStamp,
          onPointerHover: (e) => _hover(e, box),
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
              label: browserScreenSemantics(takeover: true, site: b.site),
              image: true,
              child: ClipRect(
                child: Transform(
                  transform: Matrix4.translationValues(_pan.dx, _pan.dy, 0)..multiply(Matrix4.diagonal3Values(_scale, _scale, 1)),
                  child: SizedBox.fromSize(
                    size: box,
                    child: Center(
                      child: AspectRatio(
                        aspectRatio: browserAspect,
                        child: LiveScreen(live: _live, site: b.site, radius: Radii.inner),
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
            IconButton(tooltip: '后退', onPressed: () => _send({'t': 'nav', 'action': 'back'}), icon: const Icon(Icons.arrow_back_rounded)),
            IconButton(tooltip: '刷新', onPressed: () => _send({'t': 'nav', 'action': 'reload'}), icon: const Icon(Icons.refresh_rounded)),
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
