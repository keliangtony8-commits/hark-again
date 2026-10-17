// 共用动效组件。页面只组合这些，不自己写 AnimationController。
// 无障碍：系统开了“移除动画”（MediaQuery.disableAnimations）时，这里的每个组件都直接给出终态、
// 循环动画停住；页面里需要时长的地方用 context.motion(Motion.x)，同样会被归零。
import 'dart:async';
import 'dart:io' show Platform;
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show kIsWeb, visibleForTesting;
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'format.dart';
import 'glass_mode.dart';

extension MotionContext on BuildContext {
  /// 用户在系统里关掉了动画
  bool get reduceMotion => MediaQuery.maybeDisableAnimationsOf(this) ?? false;

  /// 动画时长：减少动态时为 0（布局变化仍然发生，只是不再过渡）
  Duration motion(Duration d) => reduceMotion ? Duration.zero : d;
}

/// 循环动画（闪光、跳点、脉冲）共用：减少动态时停在静止帧，恢复时继续转。
mixin _LoopMotion<T extends StatefulWidget> on State<T>, SingleTickerProviderStateMixin<T> {
  AnimationController get loop;
  void startLoop() => loop.repeat();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (context.reduceMotion) {
      loop
        ..stop()
        ..value = 0.5;
    } else if (!loop.isAnimating) {
      startLoop();
    }
  }

  @override
  void dispose() {
    loop.dispose();
    super.dispose();
  }
}

/// 网络图片下载好了再淡入（之前露出底下的占位底色）；缓存里同步拿到的直接显示。用作 Image.frameBuilder。
Widget fadeInFrame(BuildContext context, Widget child, int? frame, bool wasSynchronouslyLoaded) => wasSynchronouslyLoaded
    ? child
    : AnimatedOpacity(opacity: frame == null ? 0 : 1, duration: context.motion(Motion.base), curve: Motion.ease, child: child);

/// 出现时轻轻上浮淡入（新消息、列表项、卡片）。delay 用于列表错峰。
class FadeSlideIn extends StatelessWidget {
  const FadeSlideIn({super.key, required this.child, this.delay = Duration.zero, this.offset = Motion.rise});
  final Widget child;
  final Duration delay;
  final double offset;

  @override
  Widget build(BuildContext context) {
    if (context.reduceMotion) return child;
    final total = Motion.base + delay;
    final start = delay.inMilliseconds / total.inMilliseconds;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: total,
      curve: Interval(start, 1, curve: Motion.ease),
      child: child,
      builder: (_, v, c) => Opacity(
        opacity: v,
        child: Transform.translate(offset: Offset(0, (1 - v) * offset), child: c),
      ),
    );
  }
}

/// 欠阻尼弹簧曲线（§O）：0→1，冲过 1 一次再落回；t=1 时余振 < 0.5%。阻尼比来自 Motion.sendDamping。
class SpringCurve extends Curve {
  const SpringCurve([this.damping = Motion.sendDamping]);
  final double damping;

  @override
  double transformInternal(double t) {
    const settle = 5.5; // ζ·ωn：e^-5.5 ≈ 0.004，到 t=1 基本静止
    final wn = settle / damping, wd = wn * math.sqrt(1 - damping * damping);
    final env = math.exp(-damping * wn * t);
    return 1 - env * (math.cos(wd * t) + damping / math.sqrt(1 - damping * damping) * math.sin(wd * t));
  }
}

/// 刚由本机发出的那条用户气泡：从输入框方向上移 Motion.sendRise、弹簧过冲再落回，同时淡入（§O）。
/// play=false 时原样画出（同一结构）；只动 transform/opacity；读屏/减弱动效只淡入。
class SendRise extends StatelessWidget {
  const SendRise({super.key, required this.play, required this.child});
  final bool play;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    // 结构始终相同（play 从 true 变 false 时子树不重建、不丢状态）：play=false 时从 1 到 1，等于不动
    final reduce = context.reduceMotion;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: play ? 0 : 1, end: 1),
      duration: reduce ? Motion.base : Motion.send,
      curve: reduce ? Motion.ease : const SpringCurve(),
      child: child,
      builder: (_, v, c) => Opacity(
        opacity: v.clamp(0.0, 1.0),
        child: Transform.translate(offset: Offset(0, reduce ? 0 : (1 - v) * Motion.sendRise), child: c),
      ),
    );
  }
}

/// 停用/下线的内容变淡（还在、还能点，只是退到背景里）；开关切换时平滑过渡。
class Dimmed extends StatelessWidget {
  const Dimmed({super.key, required this.dimmed, required this.child});
  final bool dimmed;
  final Widget child;

  @override
  Widget build(BuildContext context) => AnimatedOpacity(
        opacity: dimmed ? Op.dimmed : 1,
        duration: context.motion(Motion.base),
        curve: Motion.ease,
        child: child,
      );
}

/// 按下时微缩、松开回弹：所有可点的卡片和按钮用它，手感统一。
/// 读屏里它是一个“按钮”：子树里的文字并进来当名字；纯图标按钮必须给 semanticLabel。
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.onLongPress, this.scale = 0.97, this.semanticLabel});
  final Widget child;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final double scale;
  final String? semanticLabel;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;
  void _set(bool v) => setState(() => _down = v);

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null || widget.onLongPress != null;
    final pressed = _down && !context.reduceMotion;
    return MergeSemantics(
      child: Semantics(
        button: true,
        enabled: enabled,
        label: widget.semanticLabel,
        onTap: widget.onTap,
        onLongPress: widget.onLongPress,
        child: _gesture(enabled, pressed),
      ),
    );
  }

  Widget _gesture(bool enabled, bool pressed) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      excludeFromSemantics: true,
      onTapDown: enabled ? (_) => _set(true) : null,
      onTapUp: enabled ? (_) => _set(false) : null,
      onTapCancel: enabled ? () => _set(false) : null,
      onTap: widget.onTap,
      onLongPress: widget.onLongPress,
      child: AnimatedScale(scale: pressed ? widget.scale : 1, duration: Motion.fast, curve: pressed ? Motion.ease : Motion.spring, child: widget.child),
    );
  }
}

/// 骨架屏闪光：加载时代替转圈，布局不跳。
class Shimmer extends StatefulWidget {
  const Shimmer({super.key, this.height = 56, this.radius = Radii.inner});
  final double height;
  final double radius;

  @override
  State<Shimmer> createState() => _ShimmerState();
}

class _ShimmerState extends State<Shimmer> with SingleTickerProviderStateMixin, _LoopMotion {
  late final _c = AnimationController(vsync: this, duration: Motion.shimmer);
  @override
  AnimationController get loop => _c;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, _) => Container(
        height: widget.height,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(widget.radius),
          gradient: LinearGradient(
            begin: Alignment(-1 + _c.value * 3, 0),
            end: Alignment(_c.value * 3, 0),
            colors: [context.tileFill, context.hairline, context.tileFill],
          ),
        ),
      ),
    );
  }
}

/// 三个跳动的点：模型在思考。
class TypingDots extends StatefulWidget {
  const TypingDots({super.key});

  @override
  State<TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<TypingDots> with SingleTickerProviderStateMixin, _LoopMotion {
  late final _c = AnimationController(vsync: this, duration: Motion.typing);
  @override
  AnimationController get loop => _c;

  @override
  Widget build(BuildContext context) {
    final color = context.palette.text3;
    return AnimatedBuilder(
      animation: _c,
      builder: (_, _) => Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(3, (i) {
          final t = ((_c.value - i * 0.15) % 1.0);
          final lift = t < 0.4 ? Curves.easeOut.transform(t / 0.4) : 1 - Curves.easeIn.transform(((t - 0.4) / 0.6).clamp(0, 1));
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2.5),
            child: Transform.translate(
              offset: Offset(0, -4 * lift),
              child: Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.5 + 0.5 * lift),
                  shape: BoxShape.circle,
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}

/// 闪烁的小圆点（录音中、实时画面）。
class PulseDot extends StatefulWidget {
  const PulseDot({super.key, required this.color, this.size = 8});
  final Color color;
  final double size;

  @override
  State<PulseDot> createState() => _PulseDotState();
}

class _PulseDotState extends State<PulseDot> with SingleTickerProviderStateMixin, _LoopMotion {
  late final _c = AnimationController(vsync: this, duration: Motion.pulse);
  @override
  AnimationController get loop => _c;
  @override
  void startLoop() => _c.repeat(reverse: true);

  @override
  Widget build(BuildContext context) => FadeTransition(
    opacity: Tween(begin: 0.3, end: 1.0).animate(_c),
    child: Container(
      width: widget.size,
      height: widget.size,
      decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle),
    ),
  );
}

/// 从顶部滑入/滑出的切换（端内横幅）。child 换成 null 就收起。
class SlideDownSwitcher extends StatelessWidget {
  const SlideDownSwitcher({super.key, this.child});
  final Widget? child;

  @override
  Widget build(BuildContext context) => AnimatedSwitcher(
    duration: context.motion(Motion.slow),
    reverseDuration: context.motion(Motion.base),
    switchInCurve: Motion.spring,
    switchOutCurve: Motion.ease,
    transitionBuilder: (c, a) => FadeTransition(
      opacity: a,
      child: SlideTransition(
        position: Tween(begin: const Offset(0, -0.6), end: Offset.zero).animate(a),
        child: c,
      ),
    ),
    child: child ?? const SizedBox.shrink(key: ValueKey('none')),
  );
}

/// 从下方升起/落下的切换（输入胶囊上方的建议条、聚焦时出现的“收起”钮）：淡入 + 上浮 + 占位尺寸一起长出来，
/// 所以旁边/下面的东西是被平滑推开的。child 换成 null 就收起。axis 决定尺寸沿哪个方向长（竖排用 vertical、横排用 horizontal）。
class RiseSwitcher extends StatelessWidget {
  const RiseSwitcher({super.key, this.child, this.axis = Axis.vertical});
  final Widget? child;
  final Axis axis;

  @override
  Widget build(BuildContext context) => AnimatedSwitcher(
    duration: context.motion(Motion.base),
    switchInCurve: Motion.ease,
    switchOutCurve: Motion.ease,
    transitionBuilder: (c, a) => SizeTransition(
      sizeFactor: a,
      axis: axis,
      alignment: axis == Axis.vertical ? Alignment.bottomCenter : Alignment.centerRight,
      child: FadeTransition(
        opacity: a,
        child: SlideTransition(position: Tween(begin: const Offset(0, 0.4), end: Offset.zero).animate(a), child: c),
      ),
    ),
    child: child ?? const SizedBox.shrink(key: ValueKey('none')),
  );
}

/// 小块内容换值（模型钮的标签）：旧的往上淡出、新的从下方淡入；给 child 一个随值变化的 key。
/// 尺寸跟着内容平滑变化，按钮不跳。
class SwapSwitcher extends StatelessWidget {
  const SwapSwitcher({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => AnimatedSize(
    duration: context.motion(Motion.base),
    curve: Motion.ease,
    child: AnimatedSwitcher(
      duration: context.motion(Motion.base),
      switchInCurve: Motion.ease,
      switchOutCurve: Motion.ease,
      layoutBuilder: (current, previous) => Stack(alignment: Alignment.center, children: [...previous, ?current]),
      transitionBuilder: (c, a) {
        final incoming = c.key == child.key;
        return FadeTransition(
          opacity: a,
          child: SlideTransition(
            position: Tween(begin: Offset(0, incoming ? 0.5 : -0.5), end: Offset.zero).animate(a),
            child: c,
          ),
        );
      },
      child: child,
    ),
  );
}

/// 占位词轮播（v3.5.1 新建面板模式的输入框）：每 Motion.hintCycle 换下一句，旧的上移淡出、新的从下方淡入
/// （只动 transform / opacity，左对齐、不改尺寸）。减少动态 = 停在第一句不轮播；被盖住的路由（TickerMode 关）不走表。
/// icons（可选，和 items 一一对应）：照 Hark 每句前带一个图标，和字一起换。网页同义：features/chat/Composer.tsx 的 hints。
class CycleText extends StatefulWidget {
  const CycleText({super.key, required this.items, this.icons, this.style});
  final List<String> items;
  final List<IconData>? icons;
  final TextStyle? style;

  @override
  State<CycleText> createState() => _CycleTextState();
}

class _CycleTextState extends State<CycleText> {
  Timer? _timer;
  int _i = 0;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  @override
  void didUpdateWidget(CycleText old) {
    super.didUpdateWidget(old);
    if (old.items != widget.items) _i = 0;
    _sync();
  }

  void _sync() {
    final run = widget.items.length > 1 && !context.reduceMotion && TickerMode.valuesOf(context).enabled;
    if (!run) {
      _timer?.cancel();
      _timer = null;
      if (context.reduceMotion) _i = 0;
    } else {
      _timer ??= Timer.periodic(Motion.hintCycle, (_) {
        if (mounted) setState(() => _i = (_i + 1) % widget.items.length);
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final text = widget.items.isEmpty ? '' : widget.items[_i % widget.items.length];
    final icons = widget.icons;
    final icon = icons == null || icons.isEmpty || widget.items.isEmpty ? null : icons[_i % widget.items.length % icons.length];
    return RepaintBoundary(
      child: AnimatedSwitcher(
        duration: context.motion(Motion.base),
        switchInCurve: Motion.ease,
        switchOutCurve: Motion.ease,
        layoutBuilder: (current, previous) => Stack(alignment: AlignmentDirectional.centerStart, children: [...previous, ?current]),
        transitionBuilder: (c, a) {
          final incoming = c.key == ValueKey(text);
          return FadeTransition(
            opacity: a,
            child: SlideTransition(position: Tween(begin: Offset(0, incoming ? 0.5 : -0.5), end: Offset.zero).animate(a), child: c),
          );
        },
        child: icon == null
            ? Text(text, key: ValueKey(text), style: widget.style, maxLines: 1, overflow: TextOverflow.ellipsis)
            : Row(key: ValueKey(text), mainAxisSize: MainAxisSize.min, children: [
                Icon(icon, size: Fs.lg, color: widget.style?.color),
                const SizedBox(width: Sp.x2),
                Flexible(child: Text(text, style: widget.style, maxLines: 1, overflow: TextOverflow.ellipsis)),
              ]),
      ),
    );
  }
}

/// 侧栏出现/收起：横向展开 + 淡入（平板双栏里的历史栏）。child 换成 null 就收起。
/// animate: false 时直接到位——窗口尺寸变化（转屏、展开折叠屏）引起的切换不做过渡，否则窄屏上会先挤压对话区。
class SidePaneSwitcher extends StatelessWidget {
  const SidePaneSwitcher({super.key, this.child, this.animate = true});
  final Widget? child;
  final bool animate;

  @override
  Widget build(BuildContext context) => !animate
      ? child ?? const SizedBox.shrink()
      : AnimatedSwitcher(
          duration: context.motion(Motion.slow),
          reverseDuration: context.motion(Motion.base),
          switchInCurve: Motion.ease,
          switchOutCurve: Motion.ease,
          transitionBuilder: (c, a) => FadeTransition(
            opacity: a,
            child: SizeTransition(sizeFactor: a, axis: Axis.horizontal, alignment: AlignmentDirectional.centerStart, child: c),
          ),
          child: child ?? const SizedBox.shrink(key: ValueKey('none')),
        );
}

/// 一次性高亮：play 变成新的正数就在 child 背后铺一层强调色，停一会儿再淡出（搜索命中跳到的消息）。
/// 底色向外多出一圈（不占布局，不挤动消息）。减少动态时：底色直接出现、到点直接消失。
class FlashHighlight extends StatefulWidget {
  const FlashHighlight({super.key, required this.child, this.play = 0, this.outset = Sp.x2, this.radius = Radii.inner});
  final Widget child;

  /// 底色向外多出多少、圆角多大：消息外扩一圈（默认 8 / 16）；v3.0 设置搜索定位时，分组里的一行给 0 / 0（贴着行、不压分隔线），
  /// 整块卡片给 8 / 卡片圆角 + 8（底色是卡片外一圈等宽的光环）。
  final double outset;
  final double radius;

  /// 0 = 不闪；每换一个新的正数闪一次。
  final int play;

  @override
  State<FlashHighlight> createState() => _FlashHighlightState();
}

class _FlashHighlightState extends State<FlashHighlight> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: Motion.flash, value: 1);
  Timer? _hold;

  @override
  void initState() {
    super.initState();
    if (widget.play > 0) WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  @override
  void didUpdateWidget(FlashHighlight old) {
    super.didUpdateWidget(old);
    if (widget.play != old.play && widget.play > 0) _start();
  }

  void _start() {
    if (!mounted) return;
    _hold?.cancel();
    if (context.reduceMotion) {
      _c.value = 0;
      _hold = Timer(Motion.flash, () => _c.value = 1);
    } else {
      _c.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _hold?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tint = context.palette.accentSoft;
    final fade = CurvedAnimation(parent: _c, curve: const Interval(0.4, 1, curve: Motion.ease));
    // passthrough：把父级约束原样交给 child，避免宽度被放松后
    // 依赖拉伸的布局（例如用户消息靠右的 Column）缩成一团靠左。
    return Stack(clipBehavior: Clip.none, fit: StackFit.passthrough, children: [
      Positioned.fill(
        left: -widget.outset,
        right: -widget.outset,
        top: -widget.outset,
        bottom: -widget.outset,
        child: IgnorePointer(
          child: AnimatedBuilder(
            animation: fade,
            builder: (_, _) => fade.value >= 1
                ? const SizedBox.shrink()
                : DecoratedBox(
                    decoration: BoxDecoration(
                      color: tint.withValues(alpha: tint.a * (1 - fade.value)),
                      borderRadius: BorderRadius.circular(widget.radius),
                    ),
                  ),
          ),
        ),
      ),
      widget.child,
    ]);
  }
}

/// 入场进度：第一次出现时 t 从 0 平滑走到 1，交给 builder 去画（用量图的柱子一起长出来）。
/// 只在首次挂载时播放；数据变了不重播（想重播就换 key）。减少动态时 t 直接是 1。
class GrowIn extends StatelessWidget {
  const GrowIn({super.key, required this.builder});
  final Widget Function(BuildContext context, double t) builder;

  @override
  Widget build(BuildContext context) {
    if (context.reduceMotion) return builder(context, 1);
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Motion.slow,
      curve: Motion.ease,
      builder: (c, t, _) => builder(c, t),
    );
  }
}

/// 进度条：从 0 长到 value（0~1，超出按满格画），value 变化时平滑过渡（用量页的预算条）。
class MeterBar extends StatelessWidget {
  const MeterBar({super.key, required this.value, required this.color, this.height = Sp.x2});
  final double value;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final track = context.tileFill; // 坐在玻璃卡上：减少透明度时 GlassFills 自动换实色
    return ClipRRect(
      borderRadius: BorderRadius.circular(Radii.full),
      child: SizedBox(
        height: height,
        child: TweenAnimationBuilder<double>(
          tween: Tween(begin: 0, end: value.clamp(0, 1).toDouble()),
          duration: context.motion(Motion.slow),
          curve: Motion.ease,
          builder: (_, v, _) => Stack(fit: StackFit.expand, children: [
            ColoredBox(color: track),
            FractionallySizedBox(alignment: AlignmentDirectional.centerStart, widthFactor: v, child: ColoredBox(color: color)),
          ]),
        ),
      ),
    );
  }
}

/// 图标右上角的小圆点（未读、失败…）：出现时轻弹放大，消失时缩没；减少动态时直接出现/消失。
/// [label] 给读屏（点在时才读）。
class DotBadge extends StatelessWidget {
  const DotBadge({super.key, required this.child, required this.visible, required this.color, this.label, this.size = Sp.x3, this.right = -Sp.x1 / 2, this.top = -Sp.x1 / 2});
  final Widget child;
  final bool visible;
  final Color color;
  final String? label;

  /// 点的直径和它离 child 右上角的距离（负数 = 探出去一点）。分段导航里点放在胶囊角上、不压字。
  final double size, right, top;

  @override
  Widget build(BuildContext context) => Semantics(
        label: visible ? label : null,
        child: Stack(clipBehavior: Clip.none, children: [
          child,
          Positioned(
            right: right,
            top: top,
            child: AnimatedScale(
              scale: visible ? 1 : 0,
              duration: context.motion(Motion.base),
              curve: Motion.spring,
              child: Container(
                width: size,
                height: size,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle, border: Border.all(color: context.palette.surface, width: size / 6)),
              ),
            ),
          ),
        ]),
      );
}

/// 分段控件里选中的那颗“滑块”：等分成 count 段，index 一变就滑过去（顶部分段导航）。
/// 只负责位置动画，滑块长什么样由 thumb 决定；放在 Stack 里、文字层之下。
class SlidingThumb extends StatelessWidget {
  const SlidingThumb({super.key, required this.index, required this.count, required this.thumb});
  final int index;
  final int count;
  final Widget thumb;

  @override
  Widget build(BuildContext context) => AnimatedAlign(
        alignment: Alignment(count <= 1 ? 0 : -1 + 2 * index / (count - 1), 0),
        duration: context.motion(Motion.slow),
        curve: Motion.ease,
        child: FractionallySizedBox(widthFactor: 1 / count, heightFactor: 1, child: thumb),
      );
}

/// 浮层的出现/隐藏：淡出时同时往上收一点、并且不再挡点击（进入子页面时藏起顶栏）。
class FloatAway extends StatelessWidget {
  const FloatAway({super.key, required this.visible, required this.child});
  final bool visible;
  final Widget child;

  @override
  Widget build(BuildContext context) => IgnorePointer(
        ignoring: !visible,
        child: AnimatedSlide(
          offset: visible ? Offset.zero : const Offset(0, -0.3),
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          child: AnimatedOpacity(
            opacity: visible ? 1 : 0,
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            child: ExcludeSemantics(excluding: !visible, child: child),
          ),
        ),
      );
}

/// 全屏页（v2.82 浏览器接管页）：推到根导航上，淡入 + 从 0.94 放大到位（和对话框同一种动作，只是铺满屏）。
/// 减少动态时直接出现。
Route<T> riseRoute<T>(BuildContext context, WidgetBuilder builder) => PageRouteBuilder<T>(
      transitionDuration: context.motion(Motion.slow),
      reverseTransitionDuration: context.motion(Motion.base),
      pageBuilder: (c, _, _) => builder(c),
      transitionsBuilder: (_, a, _, child) => PopTransition(animation: a, child: child),
    );

/// 对话框的出现/消失：淡入 + 从 0.94 轻轻放大到 1（收起时反过来）。由路由的 [animation] 驱动，
/// 时长交给路由（ui/sheets.dart 的 showAppDialog 用 context.motion(Motion.base)，减少动态时直接到位）。
class PopTransition extends StatelessWidget {
  const PopTransition({super.key, required this.animation, required this.child});
  final Animation<double> animation;
  final Widget child;

  static const _from = 0.94;

  @override
  Widget build(BuildContext context) {
    final a = CurvedAnimation(parent: animation, curve: Motion.ease, reverseCurve: Motion.ease.flipped);
    return FadeTransition(
      opacity: a,
      child: ScaleTransition(scale: Tween(begin: _from, end: 1.0).animate(a), child: child),
    );
  }
}

/// 图标换状态（复制 → 对勾、喇叭 → 停止）：旧的缩小淡出、新的从 0.6 带一点回弹放大淡入，原地不挪位。
/// 给 child 一个随状态变化的 key。减少动态时直接换。
class PopSwitcher extends StatelessWidget {
  const PopSwitcher({super.key, required this.child});
  final Widget child;
  static const _from = 0.6;

  @override
  Widget build(BuildContext context) => AnimatedSwitcher(
    duration: context.motion(Motion.base),
    switchInCurve: Motion.spring,
    switchOutCurve: Motion.ease,
    layoutBuilder: (current, previous) => Stack(alignment: Alignment.center, children: [...previous, ?current]),
    transitionBuilder: (c, a) => FadeTransition(
      opacity: a,
      child: ScaleTransition(scale: Tween(begin: _from, end: 1.0).animate(a), child: c),
    ),
    child: child,
  );
}

/// 箭头/展开指示的转向：open 时转 [turns] 圈（默认 1/4 = 向右的箭头转成向下），过渡走 Motion.base。
class TurnIcon extends StatelessWidget {
  const TurnIcon({super.key, required this.open, required this.child, this.turns = 0.25});
  final bool open;
  final Widget child;
  final double turns;

  @override
  Widget build(BuildContext context) => AnimatedRotation(
    turns: open ? turns : 0,
    duration: context.motion(Motion.base),
    curve: Motion.ease,
    child: child,
  );
}

/// 数字滚到新值（面板关键数字、用量大数）：第一次出现从 0 滚上来，值变了从旧值滚到新值，前后缀/小数位/千分位不变。
/// 不是“恰好一个数字”的值（'17:42'、'晴'）、或前后缀变了，直接换字不滚。减少动态时直接给终值。
/// 读屏念的是最终值（外层 ValueTile 自己合并语义），滚动中的中间值不打扰。
class CountUp extends StatefulWidget {
  const CountUp(this.value, {super.key, this.style, this.maxLines = 1, this.overflow = TextOverflow.ellipsis});
  final String value;
  final TextStyle? style;
  final int maxLines;
  final TextOverflow overflow;

  @override
  State<CountUp> createState() => _CountUpState();
}

class _CountUpState extends State<CountUp> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: Motion.count);
  late final _t = CurvedAnimation(parent: _c, curve: Motion.ease);
  NumberParts? _to;
  double _from = 0;

  @override
  void initState() {
    super.initState();
    _to = NumberParts.parse(widget.value);
    if (_to != null && _to!.value != 0) {
      _c.forward();
    } else {
      _c.value = 1;
    }
  }

  @override
  void didUpdateWidget(CountUp old) {
    super.didUpdateWidget(old);
    if (old.value == widget.value) return;
    final next = NumberParts.parse(widget.value);
    final prev = _to;
    _to = next;
    if (next == null || prev == null || prev.prefix != next.prefix || prev.suffix != next.suffix || prev.decimals != next.decimals) {
      _c.value = 1; // 换了“形状”：直接换字
      return;
    }
    _from = _current(prev); // 半路又变了也从眼前这个数接着滚
    _c.forward(from: 0);
  }

  double _current(NumberParts p) => _from + (p.value - _from) * _t.value;

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  Text _text(String s) => Text(s, style: widget.style, maxLines: widget.maxLines, overflow: widget.overflow);

  @override
  Widget build(BuildContext context) {
    final to = _to;
    if (to == null || context.reduceMotion) return _text(widget.value);
    return AnimatedBuilder(
      animation: _t,
      builder: (_, _) => _text(_c.isCompleted ? widget.value : to.format(_current(to))),
    );
  }
}

/// 加载态 ↔ 内容（骨架 → 卡片、空状态 ↔ 列表）：交叉淡化，高度跟着平滑变化，不硬切。
/// 给 child 一个随“态”变化的 key（例如 ValueKey('loading') / ValueKey('list')），同一态内的更新不触发过渡。
class FadeSwitcher extends StatelessWidget {
  const FadeSwitcher({super.key, this.alignment = Alignment.topCenter, required this.child});
  final Widget child;

  /// 新旧内容怎么叠：整块内容（列表/骨架/空态）居中即可；一行短字（卡片标题、状态字）要传 topStart，不然会跑到中间。
  final AlignmentGeometry alignment;

  @override
  Widget build(BuildContext context) => AnimatedSize(
    duration: context.motion(Motion.base),
    curve: Motion.ease,
    alignment: alignment,
    child: AnimatedSwitcher(
      duration: context.motion(Motion.base),
      switchInCurve: Motion.ease,
      switchOutCurve: Motion.ease,
      layoutBuilder: (current, previous) => Stack(alignment: alignment, children: [...previous, ?current]),
      child: child,
    ),
  );
}


/// §N 项目左上钮的图标：plus=false 是“≡”（三条横线），true 是“+”。
/// 切换时上下两条线平移到中线、分别旋转 ±90° 合成竖线，中线不动 → 十字（Motion.morph，easeInOut 对称）。
/// 只动 transform；减少动态时直接换到终态。画线在 [MenuPlusGlyph]（按进度画），这里只负责补间。
class MenuPlusIcon extends StatelessWidget {
  const MenuPlusIcon({super.key, required this.plus, this.size = 24, this.color});
  final bool plus;
  final double size;
  final Color? color;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(end: plus ? 1 : 0),
        duration: context.motion(Motion.morph),
        curve: Motion.morphCurve,
        builder: (_, t, _) => MenuPlusGlyph(t: t, size: size, color: color),
      );
}

/// ≡ → + 的某一帧：t = 0 是 ≡，1 是 +。补间（MenuPlusIcon）和跨页飞行（MenuPlusHero）共用这一份画法。
class MenuPlusGlyph extends StatelessWidget {
  const MenuPlusGlyph({super.key, required this.t, this.size = 24, this.color});
  final double t;
  final double size;
  final Color? color;

  static const _gap = 6.0, _length = 18.0, _thick = 2.0, _crossScale = 0.9; // 十字比三横略短一点，视觉重量一致

  @override
  Widget build(BuildContext context) {
    final c = color ?? IconTheme.of(context).color ?? context.palette.text;
    Widget line(double dy, double turn) => Transform(
          alignment: Alignment.center,
          transform: Matrix4.identity()
            ..translateByDouble(0, dy * (1 - t), 0, 1)
            ..rotateZ(turn * t * math.pi / 2)
            ..scaleByDouble(1 - (1 - _crossScale) * t, 1, 1, 1),
          child: Container(
            width: _length,
            height: _thick,
            decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(_thick / 2)),
          ),
        );
    return SizedBox.square(
      dimension: size,
      child: Stack(alignment: Alignment.center, children: [line(-_gap, 1), line(0, 0), line(_gap, -1)]),
    );
  }
}

/// v2.93 §Q 进出项目页的转场（app.dart 的 CustomTransitionPage 用它）：新页淡入 + 从下方 Motion.pageRise 浮上来，
/// 与左上钮的 morph 同一个 Motion.morph 时长和曲线，钮的 Hero 飞行就骑在这条路由动画上。底下那页由 [FadeUnderCover] 淡出，
/// 两页都是透明底（外壳的壁纸在下面），不交叉淡化会叠字。只动 opacity / transform；减少动态时直接到位。
Widget pageRiseTransition(BuildContext context, Animation<double> animation, Widget child) {
  if (MediaQuery.maybeDisableAnimationsOf(context) ?? false) return child;
  final t = CurvedAnimation(parent: animation, curve: Motion.morphCurve);
  return FadeTransition(
    opacity: t,
    child: AnimatedBuilder(
      animation: t,
      child: child,
      builder: (_, c) => Transform.translate(offset: Offset(0, (1 - t.value) * Motion.pageRise), child: c),
    ),
  );
}

/// 被新页盖住时淡出（读本页路由的 secondaryAnimation）：项目列表在进项目时让位，返回时淡回来。
class FadeUnderCover extends StatelessWidget {
  const FadeUnderCover({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final cover = ModalRoute.of(context)?.secondaryAnimation;
    if (cover == null || (MediaQuery.maybeDisableAnimationsOf(context) ?? false)) return child;
    return FadeTransition(opacity: ReverseAnimation(CurvedAnimation(parent: cover, curve: Motion.morphCurve)), child: child);
  }
}

/// v2.93 §Q “同一颗钮”跨页面：项目列表的 +（新建项目）和项目页的 ≡（对话列表）挂同一个 [tag]。
/// 切页时这颗钮不随页面滑动，飞行途中按路由进度从上一页的形状画到下一页的形状（push +→≡，pop / 预测式返回 ≡→+，跟手）。
/// [frame] 把图标装进按钮外框（玻璃圆钮），飞行中的那颗也用它画，所以外观一致。减少动态：过半直接换到终态。
class MenuPlusHero extends StatelessWidget {
  const MenuPlusHero({super.key, required this.tag, required this.plus, required this.frame});
  final Object tag;
  final bool plus;
  final Widget Function(Widget glyph) frame;

  @override
  Widget build(BuildContext context) => Hero(tag: tag, flightShuttleBuilder: _shuttle, child: frame(MenuPlusIcon(plus: plus)));

  static Widget _shuttle(BuildContext context, Animation<double> animation, HeroFlightDirection direction, BuildContext from, BuildContext to) {
    MenuPlusHero? face(BuildContext c) => c.findAncestorWidgetOfExactType<MenuPlusHero>();
    final a = face(from), b = face(to);
    if (a == null || b == null) return (to.widget as Hero).child;
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    final t0 = a.plus ? 1.0 : 0.0, t1 = b.plus ? 1.0 : 0.0;
    return b.frame(AnimatedBuilder(
      animation: animation,
      builder: (_, _) {
        // push 时 animation 0→1；pop 时它是要离开那一页的动画 1→0：都换算成“从 from 走到 to 的进度”
        final p = direction == HeroFlightDirection.push ? animation.value : 1 - animation.value;
        return MenuPlusGlyph(t: reduce ? (p < 0.5 ? t0 : t1) : t0 + (t1 - t0) * p);
      },
    ));
  }
}

/// §N 浮出 / 收起（项目对话的标题药丸）：出现 = 从上方 Motion.pillDrop 落下 + 淡入，Motion.spring 轻微回弹（过冲约 2–3%）；
/// 收起 = 反向、不回弹。shown 变了才动；收起后不挡点击、读屏不念。减少动态时直接到位。
class DropIn extends StatelessWidget {
  const DropIn({super.key, required this.shown, required this.child});
  final bool shown;
  final Widget child;

  @override
  Widget build(BuildContext context) => IgnorePointer(
        ignoring: !shown,
        child: ExcludeSemantics(
          excluding: !shown,
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: 0, end: shown ? 1 : 0), // begin 只管第一次：一挂上就要显示（进场）也从上方落下来
            duration: context.motion(shown ? Motion.slow : Motion.base),
            curve: shown ? Motion.spring : Motion.ease,
            child: child,
            builder: (_, v, c) => Opacity(
              opacity: v.clamp(0.0, 1.0),
              child: Transform.translate(offset: Offset(0, (v - 1) * Motion.pillDrop), child: c),
            ),
          ),
        ),
      );
}


/// v3.3 流光壁纸的唯一时钟（ui/sky.dart 的壁纸与 ShellPage 顶部渐隐条共用，像素对齐）。
/// 只有一个 Timer（不用 Ticker：Ticker 每个 vsync 都出一帧，起不到节流作用）：
/// - 有“动画”订阅者 → 每 Sky.frame（≈30 帧/秒）推进 time（柔光漂移），顺带每 Sky.recolor 重算钟点 hour（天色）；
/// - 只有“静止”订阅者（减少动态）→ 每 Sky.recolor 一次，只换天色、柔光不动；
/// - 没有订阅者 / App 不在前台 / 测试环境（FLUTTER_TEST）→ 一个 Timer 都没有。
class SkyClock with WidgetsBindingObserver {
  SkyClock._(this.frozen);
  static final SkyClock instance = SkyClock._(inTest);

  /// 测试用：不看环境变量的独立时钟（frozen = false 才会起 Timer）。
  @visibleForTesting
  factory SkyClock.forTest({bool frozen = false}) => SkyClock._(frozen);

  /// flutter test 下完全静止：大量测试用 pumpAndSettle，常驻计时器会让它永远等不完。
  static final bool inTest = !kIsWeb && Platform.environment.containsKey('FLUTTER_TEST');
  final bool frozen;

  final ValueNotifier<double> time = ValueNotifier(0);
  final ValueNotifier<double> hour = ValueNotifier(_nowHour());
  final Stopwatch _watch = Stopwatch();
  Timer? _timer;
  Duration? _period;
  DateTime _recolored = DateTime.now();
  int _animators = 0, _still = 0;
  bool _observing = false, _resumed = true;

  /// 当前 Timer 的间隔（null = 没在跑）。
  @visibleForTesting
  Duration? get period => _period;

  /// 当前订阅者个数（动画 + 静止）。
  @visibleForTesting
  int get subscribers => _animators + _still;

  static double _nowHour() {
    final n = DateTime.now();
    return n.hour + n.minute / 60 + n.second / 3600;
  }

  /// animate = false：减少动态，只要天色随钟点变、不要漂移。
  void acquire({bool animate = true}) {
    animate ? _animators++ : _still++;
    if (!_observing && !frozen) {
      WidgetsBinding.instance.addObserver(this);
      _observing = true;
    }
    _sync();
  }

  void release({bool animate = true}) {
    if (animate) {
      _animators = math.max(0, _animators - 1);
    } else {
      _still = math.max(0, _still - 1);
    }
    _sync();
  }

  void _sync() {
    final Duration? want = frozen || !_resumed
        ? null
        : _animators > 0
            ? Sky.frame
            : _still > 0
                ? Sky.recolor
                : null;
    if (want == _period) return;
    _timer?.cancel();
    _timer = null;
    _period = want;
    if (want == Sky.frame) {
      _watch.start();
    } else {
      _watch.stop();
    }
    if (want == null) return;
    _recolor(); // 回到前台 / 刚订阅：先对一次钟点
    _timer = Timer.periodic(want, (_) => _tick());
  }

  void _tick() {
    if (_period == Sky.frame) time.value = _watch.elapsedMilliseconds / 1000;
    if (DateTime.now().difference(_recolored) >= Sky.recolor || _period == Sky.recolor) _recolor();
  }

  void _recolor() {
    _recolored = DateTime.now();
    hour.value = _nowHour();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _resumed = state == AppLifecycleState.resumed;
    _sync();
  }
}
