// 一级页面（主页/聊天/项目）的外框：让出浮动顶栏的高度、在顶栏左侧画本页的上下文按钮。
// 让位的方式是把顶栏高度加进 MediaQuery.padding.top：页面里的 PageBody / 列表照常读安全区，
// 内容可以从顶栏下面滚过去（被玻璃模糊），而不是被一块实心色挡住。
// header：紧贴顶栏下面的一行（主聊天的标题），高度固定为 headerHeight，同样计入让位。
// 滚上去的内容在让位线上方渐隐：顶栏是悬浮胶囊、两边是空的，不渐隐的话消息会和头像、标题叠在一起
//   （v0.80 修：聊天标题“额度”和滚上去的消息叠字）。有 header 时整行 header 下面才开始显，到让位线下 Layout.topFadeRamp 才全显
//   （缓入，v0.92：墨色气泡不再切出硬边）。v3.3：原来是整页 ShaderMask(dstIn)（整个滚动区一层离屏）→ 改为顶部一条
//   BackdropFade（同一张壁纸盖在内容上，α 与原遮罩互补），视觉不变、没有离屏层。
// 绘制顺序（毛玻璃分组的前提，见 glass.dart 文件头）：内容（自己一组：输入胶囊等）→ 顶部渐隐条 → 左侧按钮 → header。
//   左侧按钮和 header 属于 AppShell 那一组（和顶栏共享取背景）：它们在渐隐条之后画，取到的背景已经渐隐过；
//   左侧按钮先画（它稳定、不淡入，由它取背景），header 药丸有进场淡入，排在后面只读结果。
//   本页在路由转场中（项目页淡入上浮）、上面压着别的路由、或页面自己的盖层露出（主聊天历史抽屉，[covered]）时，左侧按钮 / header 临时自成一组：
//   这时它们在离屏层里、或之后还有东西盖在顶栏底下，不能替顶栏取背景；顶栏变成独自一个，照常单独模糊。
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import '../ui/glass.dart';

class ShellPage extends StatelessWidget {
  const ShellPage({super.key, required this.child, this.lead, this.header, this.headerHeight = 0, this.covered});
  final Widget child;
  final Widget? lead;
  final Widget? header;
  final double headerHeight;

  /// 页面自己的盖层（主聊天的历史抽屉）正露在左侧按钮 / header 之上时为 true（见文件头“绘制顺序”）。
  final ValueListenable<bool>? covered;

  /// 一级页面内容顶部要让出的总高度（状态栏 + 顶栏 + header）。
  static double insetOf(BuildContext context, {double header = 0}) =>
      MediaQuery.paddingOf(context).top + Layout.shellTop + (header > 0 ? header + Sp.x2 : 0);

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    final top = mq.padding.top;
    final headerSpace = header == null ? 0.0 : headerHeight + Sp.x2;
    final inset = top + Layout.shellTop + headerSpace;
    final solid = BackdropFade.solidOf(inset);
    return Stack(children: [
      // 内容自成一组（输入胶囊 / 回到最新 / 错误条）：它们只模糊内容本身
      BlurGroup(
        child: MediaQuery(
          data: mq.copyWith(padding: mq.padding.copyWith(top: inset)),
          child: child,
        ),
      ),
      Positioned(top: 0, left: 0, right: 0, height: solid, child: BackdropFade(clear: BackdropFade.clearOf(top, header == null ? 0 : headerHeight), solid: solid)),
      Positioned.fill(
        child: _ChromeGroup(
          covered: covered,
          child: Stack(children: [
            if (lead != null) Positioned(top: top + Layout.topBarTop, left: mq.padding.left + Layout.gutter, child: lead!),
            if (header != null)
              Positioned(
                top: top + Layout.shellHeaderTop,
                left: mq.padding.left + Layout.gutter,
                right: mq.padding.right + Layout.gutter,
                height: headerHeight,
                child: header!,
              ),
          ]),
        ),
      ),
    ]);
  }
}

/// 左侧按钮 / header 的毛玻璃组：平时沿用外层（AppShell）的组；路由转场中或 [covered] 时换成自己的一组（见文件头）。
/// 只换组的 key、不改子树结构（药丸不会因此重播进场动画）；只在转场开始 / 结束、盖层出现 / 消失时重建这一小块。
class _ChromeGroup extends StatefulWidget {
  const _ChromeGroup({required this.child, this.covered});
  final Widget child;
  final ValueListenable<bool>? covered;

  @override
  State<_ChromeGroup> createState() => _ChromeGroupState();
}

class _ChromeGroupState extends State<_ChromeGroup> {
  final _own = BackdropKey();
  Animation<double>? _in, _out;
  bool _moving = false;

  bool get _detached => _moving || (widget.covered?.value ?? false);

  @override
  void initState() {
    super.initState();
    widget.covered?.addListener(_changed);
  }

  @override
  void didUpdateWidget(_ChromeGroup old) {
    super.didUpdateWidget(old);
    if (old.covered != widget.covered) {
      old.covered?.removeListener(_changed);
      widget.covered?.addListener(_changed);
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route?.animation != _in || route?.secondaryAnimation != _out) {
      _in?.removeStatusListener(_status);
      _out?.removeStatusListener(_status);
      _in = route?.animation?..addStatusListener(_status);
      _out = route?.secondaryAnimation?..addStatusListener(_status);
    }
    _covered = !(route?.isCurrent ?? true); // 上面压着别的路由（正推进来）：它画在按钮之后、也在顶栏底下
    _moving = _isMoving();
  }

  bool _covered = false;
  bool _isMoving() => _covered || !((_in?.isCompleted ?? true) && (_out?.isDismissed ?? true));

  void _status(AnimationStatus _) {
    final m = _isMoving();
    if (m != _moving && mounted) setState(() => _moving = m);
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _in?.removeStatusListener(_status);
    _out?.removeStatusListener(_status);
    widget.covered?.removeListener(_changed);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final outer = BackdropGroup.of(context)?.backdropKey;
    return BackdropGroup(backdropKey: _detached || outer == null ? _own : outer, child: widget.child);
  }
}
