// 弹层与对话框：表单、操作菜单、危险确认。所有“填几个字段 / 选一个操作 / 确认一下”都走这里，
// 页面不再各自拼路由 / showDialog，版式、材质、动效和键盘避让全 App 一致。
//   showAppSheet        全屏弹层（菜单、表单、选择器、小卡片）：内容整页滚
//   showAppScrollSheet  全屏长列表弹层（工具列表、项目文件、选项目）：标题等固定、[SheetList] 在里面滚
//   showAppDialog       居中对话框（短确认、一句话提示）：磨砂遮罩 + GlassDialog + PopTransition
//   showAppViewer       全屏查看器（v2.99 图片一摞点开）：实底盖满、淡入，内容自己排版
// 弹层画在 [SheetPage] 上，对话框套 GlassDialog；showModalBottomSheet / showDialog / showMenu /
// PopupMenuButton 只允许出现在本文件（test/sheet_test.dart 的架构守卫）。
//
// v3.5.1 弹层全屏（用户 2026-10-16“别留那个半屏的”“丑爆了”，HANDOFF 第二节 24；= Web 43366c7 手机 .sheet）：
// 不再是从底部升起的玻璃半屏卡（GlassSheet + showModalBottomSheet + 把手，已删），而是铺满整屏、直接落在流光壁纸上的一页，
// 样子 = 子页（左上圆玻璃返回钮 + 居中裸字标题，复用 GlassAppBar）：内容整页滚、按钮行（表单的提交钮）钉在屏幕底，
// 滚过标题行 / 按钮行的内容由壁纸渐隐条（BackdropFade）盖住；只淡入、不上移；路由不透明，淡入完成后下面的页面不再绘制（= Web .shell 隐藏）。
// 成本：没有 BackdropFilter（返回钮也不模糊——底下只有壁纸），也没有离屏层；一张 Backdrop 壁纸 + 两三条渐隐条（同一个 SkyLayer 着色器）。
// 平板 / 宽屏也全屏（弹层以前没有自适应断点），内容按 Layout.contentMax 居中（= Web --content-w），和子页一样。
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass.dart';
import 'motion.dart';
import 'sub_page.dart' show GlassAppBar;

// 弹层一律开在根导航器上（v2.78）：盖住外壳的浮动顶栏和底部输入胶囊。
// PageRoute + opaque：淡入过程中下面的页面还看得见（跟着淡出让位），淡入完成后 Navigator 不再绘制下面的路由；
// fullscreenDialog：下面的页面不做 Material 的退场动画（只有这一层淡入，= Web 只淡入不上移）。
Future<T?> _pushSheet<T>(BuildContext context, WidgetBuilder page) {
  final solid = GlassMode.solidOf(context);
  final d = context.motion(Motion.base);
  return Navigator.of(context, rootNavigator: true).push<T>(PageRouteBuilder<T>(
    opaque: true,
    fullscreenDialog: true,
    transitionDuration: d,
    reverseTransitionDuration: d,
    // 新路由在根 Navigator 的 overlay 里，拿不到页面上的 GlassMode：在这里重新注入
    pageBuilder: (_, _, _) => GlassMode(solid: solid, child: Builder(builder: page)),
    transitionsBuilder: (_, animation, _, child) => FadeTransition(opacity: CurvedAnimation(parent: animation, curve: Motion.ease), child: child),
  ));
}

/// 全屏弹层：内容整页滚（[builder] 返回的内容随自身高度排版，不要用 Flexible / Expanded 撑高）。[title] = 顶上居中的标题。
Future<T?> showAppSheet<T>(BuildContext context, {String? title, required WidgetBuilder builder}) =>
    _pushSheet<T>(context, (ctx) => SheetPage(title: title, child: Builder(builder: builder)));

/// 全屏长列表弹层（工具列表、项目文件、选项目）：[builder] 返回 Column(mainAxisSize: min)：固定部分（说明、筛选）+ 一个 [SheetList]
/// （或 Flexible 包住的空态 / 骨架），列表占满剩下的高度在里面滚。
Future<T?> showAppScrollSheet<T>(BuildContext context, {String? title, required WidgetBuilder builder}) =>
    _pushSheet<T>(context, (ctx) => SheetPage(title: title, scroll: false, child: Builder(builder: builder)));

/// 全屏弹层的一页（v3.5.1，规则见文件头）：壁纸 + 标题行（返回钮 · 居中标题）+ 内容区 + 可选钉底的 [footer]。
/// [scroll] = 内容整页滚；false = 内容拿到“剩下的高度”自己排（[SheetList] 在里面滚）。页面不直接用它——走 showAppSheet / showAppScrollSheet / showFormSheet。
class SheetPage extends StatelessWidget {
  const SheetPage({super.key, this.title, required this.child, this.footer, this.scroll = true});
  final String? title;
  final Widget child;
  final Widget? footer;
  final bool scroll;

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    final top = mq.padding.top;
    // 标题行中线以上全是壁纸，到标题行下沿再往下 Sp.x5 内容全显（= Web .sky-fade-sheet 的 fade-a / fade-b，= 子页 BackdropFade.clearOf）
    final clear = top + Layout.topBarTop + Layout.topBar / 2;
    final solid = top + Layout.topBarTop + Layout.topBar + Sp.x5;
    final keyboard = mq.viewInsets.bottom;
    // 底部：键盘弹起时贴键盘，否则让出手势条；再留 Sp.x5（= Web padding-bottom sp-5 + safe-area）
    final foot = (keyboard > 0 ? 0.0 : mq.padding.bottom) + Sp.x5;
    const ramp = Layout.topFadeRamp;
    // 内容里不再有安全区 / 键盘让位（这里统一给）：调用处的 SafeArea、viewInsets 留白自动归零，不重复
    Widget content = MediaQuery(
      data: mq.removePadding(removeTop: true, removeBottom: true).removeViewInsets(removeBottom: true),
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: Layout.contentMax), child: child),
      ),
    );
    final bottomPad = footer == null ? foot : ramp;
    content = scroll
        ? SingleChildScrollView(padding: EdgeInsets.only(top: solid - clear, bottom: bottomPad), child: content)
        : Padding(padding: EdgeInsets.only(top: solid - clear), child: _SheetInset(bottom: bottomPad, child: content));
    final region = Stack(children: [
      Positioned.fill(child: content),
      // 上沿：从标题行中线（这一区的顶）淡到 solid；下沿：最后 [bottomPad] 淡成壁纸（有按钮行时淡在按钮行上面）
      Positioned(top: 0, left: 0, right: 0, height: solid - clear, child: BackdropFade.local(clear: 0, solid: solid - clear)),
      Positioned(left: 0, right: 0, bottom: 0, height: bottomPad, child: BackdropFade.local(solid: 0, clear: footer == null ? bottomPad - (foot - Sp.x5) : bottomPad)),
    ]);
    return Backdrop(
      child: Material(
        type: MaterialType.transparency, // ListTile 的水波纹、TextField 要一层 Material
        child: Stack(children: [
          Positioned.fill(
            top: clear,
            bottom: keyboard,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Expanded(child: region),
              if (footer != null)
                Align(
                  alignment: Alignment.topCenter,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: Layout.contentMax),
                    child: Padding(padding: EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, foot), child: SizedBox(width: double.infinity, child: footer)),
                  ),
                ),
            ]),
          ),
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            height: top + Layout.shellTop,
            child: GlassAppBar(
              title: title == null ? const SizedBox.shrink() : Text(title!),
              leading: GlassIconButton(icon: Icons.arrow_back_ios_new_rounded, tooltip: '关闭', blur: false, onTap: () => Navigator.of(context).maybePop()),
            ),
          ),
        ]),
      ),
    );
  }
}

/// [showAppScrollSheet] 内容区底部要让出的高度（下沿渐隐条 + 手势条），[SheetList] 加进自己的底部留白：列表滚到底时最后一行停在渐隐上面。
class _SheetInset extends InheritedWidget {
  const _SheetInset({required this.bottom, required super.child});
  final double bottom;

  static double of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<_SheetInset>()?.bottom ?? 0;

  @override
  bool updateShouldNotify(_SheetInset old) => old.bottom != bottom;
}

/// [showAppScrollSheet] 里的列表：内容少就收拢，内容多就占满剩下的高度并滚动。
/// 上沿一条壁纸渐隐（滚上去的行淡进壁纸，不在固定的标题 / 说明下面切硬边），底部留白让到弹层的下沿渐隐之上。
class SheetList extends StatelessWidget {
  const SheetList({super.key, this.padding = const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x4), required this.children});
  final EdgeInsetsGeometry padding;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    const ramp = Layout.topFadeRamp;
    return Flexible(
      child: Stack(children: [
        ListView(
          shrinkWrap: true,
          padding: padding.add(EdgeInsets.only(top: ramp, bottom: _SheetInset.of(context))),
          children: children,
        ),
        const Positioned(top: 0, left: 0, right: 0, height: ramp, child: BackdropFade.local(clear: 0, solid: ramp)),
      ]),
    );
  }
}

/// 表单里的一个输入框。
class FieldSpec {
  const FieldSpec(this.key, this.label, {this.hint, this.initial = '', this.lines = 1, this.obscure = false, this.required = true, this.keyboard});
  final String key, label;
  final String? hint;
  final String initial;
  final int lines;
  final bool obscure, required;
  final TextInputType? keyboard;
}

/// 弹出表单；返回 {key: 去掉首尾空白的值}，取消返回 null。必填项为空时按钮不可点。
/// [extra] 放在输入框下面的附加控件（如选项 Chip），它自己管理状态。
Future<Map<String, String>?> showFormSheet(
  BuildContext context, {
  required String title,
  String? subtitle,
  required List<FieldSpec> fields,
  String submit = '保存',
  Widget? extra,
}) {
  // 自己画 SheetPage：提交钮要钉在屏幕底（footer），它的可点状态跟着输入框变
  return _pushSheet<Map<String, String>>(
    context,
    (_) => _FormSheet(title: title, subtitle: subtitle, fields: fields, submit: submit, extra: extra),
  );
}

class _FormSheet extends StatefulWidget {
  const _FormSheet({required this.title, this.subtitle, required this.fields, required this.submit, this.extra});
  final String title, submit;
  final String? subtitle;
  final List<FieldSpec> fields;
  final Widget? extra;

  @override
  State<_FormSheet> createState() => _FormSheetState();
}

class _FormSheetState extends State<_FormSheet> {
  late final _c = {for (final f in widget.fields) f.key: TextEditingController(text: f.initial)};

  bool get _valid => widget.fields.every((f) => !f.required || _c[f.key]!.text.trim().isNotEmpty);

  @override
  void initState() {
    super.initState();
    for (final c in _c.values) {
      c.addListener(() => setState(() {}));
    }
  }

  @override
  void dispose() {
    for (final c in _c.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _done() => Navigator.pop(context, {for (final e in _c.entries) e.key: e.value.text.trim()});

  @override
  Widget build(BuildContext context) {
    // 字段整页滚，提交钮钉在屏幕底（v2.93 起钉底；v3.5.1 全屏）：键盘弹起、字段多时按钮也始终看得见，不用先往下滚
    return SheetPage(
      title: widget.title,
      footer: FilledButton(onPressed: _valid ? _done : null, child: Text(widget.submit)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x5),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (widget.subtitle != null) Text(widget.subtitle!, style: context.text.bodySmall),
          for (final (i, f) in widget.fields.indexed) ...[
            if (i > 0 || widget.subtitle != null) const SizedBox(height: Sp.x3),
            TextField(
              controller: _c[f.key],
              autofocus: i == 0,
              obscureText: f.obscure,
              keyboardType: f.keyboard,
              minLines: f.lines,
              maxLines: f.obscure ? 1 : (f.lines == 1 ? 1 : f.lines * 2),
              decoration: InputDecoration(labelText: f.label, hintText: f.hint),
            ),
          ],
          if (widget.extra != null) ...[const SizedBox(height: Sp.x3), widget.extra!],
        ]),
      ),
    );
  }
}

/// 操作菜单里的一项：要么点了就执行 [onTap]，要么把 [value] 作为菜单的返回值（用来做选择）。
class SheetAction<T> {
  const SheetAction(this.icon, this.label, {this.onTap, this.value, this.danger = false, this.subtitle});
  final IconData icon;
  final String label;
  final String? subtitle; // 一行说明（如思考强度“想得少，回得快”）
  final VoidCallback? onTap;
  final T? value;
  final bool danger;
}

Future<T?> showActionSheet<T>(BuildContext context, {String? title, required List<SheetAction<T>> actions}) async {
  final p = context.palette;
  final chosen = await showAppSheet<SheetAction<T>>(
    context,
    title: title,
    builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final a in actions)
        ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: Sp.x5), // 图标和标题对齐同一条线
          leading: Icon(a.icon, color: a.danger ? p.danger : null),
          title: Text(a.label, style: a.danger ? TextStyle(color: p.danger) : null),
          subtitle: a.subtitle == null ? null : Text(a.subtitle!, style: ctx.text.bodySmall?.copyWith(color: p.text2)),
          onTap: () => Navigator.pop(ctx, a),
        ),
    ]),
  );
  chosen?.onTap?.call(); // 先关菜单再执行，避免在已关闭的弹层上弹对话框
  return chosen?.value;
}

/// 居中对话框。[builder] 只画内容（标题、正文、按钮），玻璃框、最宽宽度、边距和键盘避让由这里统一给。
/// 背后是和输入胶囊聚焦时同一种“磨砂遮罩”（scrim 着色 + Glass.scrimBlur 模糊，跟着路由动画渐入）；
/// 点遮罩或返回键 = 取消（返回 null）。减少透明度：不模糊、实色；减少动态：直接出现。
Future<T?> showAppDialog<T>(BuildContext context, {required WidgetBuilder builder, bool dismissible = true}) {
  final p = context.palette;
  final solid = GlassMode.solidOf(context);
  return showGeneralDialog<T>(
    context: context,
    barrierDismissible: dismissible,
    barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
    barrierColor: solid ? p.bg.withValues(alpha: Op.dimmed) : p.scrim,
    transitionDuration: context.motion(Motion.base),
    // 新路由在 Navigator 的 overlay 里，拿不到页面上的 GlassMode：在这里重新注入
    pageBuilder: (ctx, _, _) => GlassMode(
      solid: solid,
      child: SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(Layout.gutter, Sp.x5, Layout.gutter, Sp.x5 + MediaQuery.viewInsetsOf(ctx).bottom),
          child: Center(child: GlassDialog(child: Builder(builder: builder))),
        ),
      ),
    ),
    transitionBuilder: (ctx, animation, _, child) {
      final dialog = PopTransition(animation: animation, child: child);
      if (solid) return dialog;
      // 遮罩下面的页面一起变模糊：模糊层不接点击，点击仍落到遮罩上（= 取消）
      return Stack(children: [
        Positioned.fill(
          child: IgnorePointer(
            child: FadeTransition( // v2.88：模糊半径固定，只淡入（不每帧重算 sigma）
              opacity: animation,
              child: RepaintBoundary(
                child: BackdropFilter(
                  filter: ImageFilter.blur(sigmaX: Glass.scrimBlur, sigmaY: Glass.scrimBlur),
                  child: const SizedBox.expand(),
                ),
              ),
            ),
          ),
        ),
        dialog,
      ]);
    },
  );
}

/// 全屏查看器（v2.99 E4 图片一摞点开左右翻）：页面底色实底盖满整屏、只淡入（减少动态直接出现），返回键 / 内容里的关闭 = 退出。
/// [builder] 自己排版（翻页、页码、说明、按钮），这里只给路由、底色和安全区。
Future<T?> showAppViewer<T>(BuildContext context, {required WidgetBuilder builder}) {
  final solid = GlassMode.solidOf(context);
  return showGeneralDialog<T>(
    context: context,
    barrierDismissible: false,
    barrierColor: context.palette.bg,
    transitionDuration: context.motion(Motion.base),
    pageBuilder: (ctx, _, _) => GlassMode(solid: solid, child: SafeArea(child: Builder(builder: builder))),
    transitionBuilder: (ctx, animation, _, child) => FadeTransition(opacity: CurvedAnimation(parent: animation, curve: Motion.ease), child: child),
  );
}

/// 删除之类不可撤销的操作先确认一次：玻璃对话框，底部两颗等宽胶囊（取消 = tile，动作 = 实心危险色）。
Future<bool> confirmDanger(BuildContext context, {required String title, String? text, String action = '删除'}) async {
  final ok = await showAppDialog<bool>(
    context,
    builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(title, style: ctx.text.titleLarge),
      if (text != null) ...[
        const SizedBox(height: Sp.x2),
        Text(text, style: ctx.text.bodyMedium?.copyWith(color: ctx.palette.text2)),
      ],
      const SizedBox(height: Sp.x5),
      Row(children: [
        Expanded(child: PillButton(label: '取消', onTap: () => Navigator.pop(ctx, false))),
        const SizedBox(width: Sp.x3),
        Expanded(child: PillButton(label: action, danger: true, onTap: () => Navigator.pop(ctx, true))),
      ]),
    ]),
  );
  return ok ?? false;
}
