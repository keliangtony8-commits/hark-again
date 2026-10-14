// 弹层与对话框：表单、操作菜单、危险确认。所有“填几个字段 / 选一个操作 / 确认一下”都走这里，
// 页面不再各自拼 showModalBottomSheet / showDialog，版式、玻璃材质、动效和键盘避让全 App 一致。
//   showAppSheet        随内容高度的底部弹层（菜单、表单、选择器、小卡片）
//   showAppScrollSheet  长列表弹层：随内容高度、封顶后内部滚动（工具列表、项目文件、选项目）
//   showAppDialog       居中对话框（短确认、一句话提示）：磨砂遮罩 + GlassDialog + PopTransition
// 弹层套 ui/glass.dart 的 GlassSheet，对话框套 GlassDialog；showModalBottomSheet / showDialog / showMenu /
// PopupMenuButton 只允许出现在本文件（test/sheet_test.dart 的架构守卫）。
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import 'glass.dart';
import 'motion.dart';

// 弹层一律开在根导航器上（v2.78）：盖住外壳的浮动顶栏和底部输入胶囊，遮罩也盖住它们——以前开在 Tab 自己的导航器里，
// 顶栏浮在遮罩上面“叠在一起”。
Future<T?> showAppSheet<T>(BuildContext context, {required WidgetBuilder builder}) => showModalBottomSheet<T>(
      context: context,
      useRootNavigator: true,
      isScrollControlled: true, // 让表单能随键盘长高；高度仍随内容
      builder: (ctx) => GlassSheet(child: builder(ctx)),
    );

/// 长列表弹层（工具列表、项目文件、选项目）：高度随内容，最高到屏幕的 [max]，再长就在里面滚。
/// 以前固定开到 60–70% 屏高，三个项目的选择器下面空一大片；现在短列表就是短弹层，数据到了高度平滑长出来。
/// [builder] 返回 Column(mainAxisSize: min)：标题等固定部分 + 一个 [SheetList]（或 Flexible 包住的空态/骨架）。
Future<T?> showAppScrollSheet<T>(
  BuildContext context, {
  required WidgetBuilder builder,
  double max = 0.85,
}) =>
    showModalBottomSheet<T>(
      context: context,
      useRootNavigator: true,
      isScrollControlled: true,
      builder: (ctx) => ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * max),
        child: GlassSheet(
          child: AnimatedSize(
            duration: ctx.motion(Motion.base),
            curve: Motion.ease,
            alignment: Alignment.topCenter,
            child: builder(ctx),
          ),
        ),
      ),
    );

/// [showAppScrollSheet] 里的列表：内容少就收拢，内容多就占满剩下的高度并滚动。
class SheetList extends StatelessWidget {
  const SheetList({super.key, this.padding = const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x4), required this.children});
  final EdgeInsetsGeometry padding;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Flexible(child: ListView(shrinkWrap: true, padding: padding, children: children));
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
  return showAppSheet<Map<String, String>>(
    context,
    builder: (_) => _FormSheet(title: title, subtitle: subtitle, fields: fields, submit: submit, extra: extra),
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
    return Padding(
      padding: EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, MediaQuery.viewInsetsOf(context).bottom + Sp.x5),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(widget.title, style: context.text.titleLarge),
          if (widget.subtitle != null) ...[const SizedBox(height: Sp.x1), Text(widget.subtitle!, style: context.text.bodySmall)],
          for (final (i, f) in widget.fields.indexed) ...[
            const SizedBox(height: Sp.x3),
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
          const SizedBox(height: Sp.x4),
          FilledButton(onPressed: _valid ? _done : null, child: Text(widget.submit)),
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
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (title != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x2),
            child: Text(title, style: ctx.text.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
          ),
        for (final a in actions)
          ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: Sp.x5), // 图标和标题对齐同一条线
            leading: Icon(a.icon, color: a.danger ? p.danger : null),
            title: Text(a.label, style: a.danger ? TextStyle(color: p.danger) : null),
            subtitle: a.subtitle == null ? null : Text(a.subtitle!, style: ctx.text.bodySmall?.copyWith(color: p.text2)),
            onTap: () => Navigator.pop(ctx, a),
          ),
      ]),
    ),
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
            child: AnimatedBuilder(
              animation: animation,
              builder: (_, _) => BackdropFilter(
                filter: ImageFilter.blur(sigmaX: Glass.scrimBlur * animation.value, sigmaY: Glass.scrimBlur * animation.value),
                child: const SizedBox.expand(),
              ),
            ),
          ),
        ),
        dialog,
      ]);
    },
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
