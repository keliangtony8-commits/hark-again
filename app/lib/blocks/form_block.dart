// 表单卡：浏览器任务进行中向你要登录信息或验证码（对标 Hark 浏览器任务里“在它自己的表单上问你”）。
// - 等填写（pending）：输入框 + 取消 / 提交；登录卡放进 AutofillGroup，安卓/iOS 的密码管理器能直接填。
// - 提交后：输入框收起、清空，只剩一行状态（已填写 / 已取消 / 已过期）；值从不进卡片和本地缓存。
// - 断线没发出去（onForm 返回 false）：保留输入，用户连上再点。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import 'block_actions.dart';
import 'block_frame.dart';

class FormBlockView extends StatefulWidget {
  const FormBlockView(this.block, {super.key});
  final FormBlock block;

  /// 状态小字和颜色：等填写用提醒色（与审批卡、订单卡一致），其余退到 text2/text3。
  static (String, Color) stateLabel(FormBlock b, Palette p) => switch (b.state) {
        'submitted' => ('已填写', p.text2),
        'cancelled' => ('已取消', p.text3),
        'expired' => ('已过期', p.text3),
        _ => ('等你填写', p.warning),
      };

  static IconData iconOf(FormBlock b) => switch (b.purpose) {
        'login' => Icons.lock_outline_rounded,
        'code' => Icons.sms_outlined,
        _ => Icons.edit_note_rounded,
      };

  @override
  State<FormBlockView> createState() => _FormBlockViewState();
}

class _FormBlockViewState extends State<FormBlockView> {
  late final Map<String, TextEditingController> _ctl = {
    for (final f in widget.block.fields) f.name: TextEditingController(text: f.value ?? ''),
  };
  final Set<String> _revealed = {}; // 点了“显示密码”的输入框
  bool _remember = false;
  bool _sent = false; // 已发出、等服务器把卡片改成 submitted：按钮置灰防连点

  @override
  void dispose() {
    for (final c in _ctl.values) {
      c.dispose();
    }
    super.dispose();
  }

  bool get _complete => _ctl.values.every((c) => c.text.trim().isNotEmpty);

  void _reply(bool submit) {
    final onForm = BlockActions.of(context)?.onForm;
    if (onForm == null || _sent) return;
    if (submit && !_complete) return;
    final values = submit ? {for (final e in _ctl.entries) e.key: e.value.text} : null;
    if (!onForm(widget.block.id, values, submit && _remember)) return;
    if (submit) TextInput.finishAutofillContext(); // 让系统密码管理器有机会保存
    setState(() => _sent = true);
    for (final c in _ctl.values) {
      c.clear(); // 发出后本地也不留
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = widget.block;
    final canReply = BlockActions.of(context)?.onForm != null;
    final (label, color) = FormBlockView.stateLabel(b, p);
    final open = b.pending && canReply && !_sent;
    return BlockFrame(
      tone: b.pending ? FrameTone.waiting : FrameTone.calm,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          PopSwitcher(
            child: Icon(b.state == 'submitted' ? Icons.check_circle_outline_rounded : FormBlockView.iconOf(b),
                key: ValueKey(b.state == 'submitted'), size: QuietAction.iconSize, color: p.text2),
          ),
          const SizedBox(width: Sp.x2),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(b.title, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
              if (b.site != null && b.site!.isNotEmpty)
                Text(b.site!, style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
            ]),
          ),
          SwapSwitcher(
            child: Text(label, key: ValueKey(b.state), style: context.text.labelSmall?.copyWith(color: color, fontWeight: Weights.title)),
          ),
        ]),
        RiseSwitcher(child: open ? _body(context, b) : null),
      ]),
    );
  }

  Widget _body(BuildContext context, FormBlock b) {
    final p = context.palette;
    final last = b.fields.isEmpty ? '' : b.fields.last.name;
    final fields = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final (i, f) in b.fields.indexed)
        Padding(
          padding: EdgeInsets.only(top: i == 0 ? Sp.x4 : Sp.x2),
          child: _field(f, isLast: f.name == last),
        ),
    ]);
    return Column(key: const ValueKey('form'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      b.purpose == 'login' ? AutofillGroup(child: fields) : fields,
      if (b.remember)
        Padding(
          padding: const EdgeInsets.only(top: Sp.x2),
          child: MergeSemantics(
            child: Row(children: [
              Expanded(child: Text('记住到保险箱，下次自动登录', style: context.text.bodySmall)),
              Switch(value: _remember, onChanged: (v) => setState(() => _remember = v)),
            ]),
          ),
        ),
      Padding(
        padding: const EdgeInsets.only(top: Sp.x2),
        child: Row(children: [
          Icon(Icons.visibility_off_outlined, size: Fs.sm, color: p.text3),
          const SizedBox(width: Sp.x1),
          Expanded(child: Text('只交给浏览器填写，助手看不到', style: context.text.bodySmall?.copyWith(color: p.text3))),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.only(top: Sp.x3),
        child: ListenableBuilder(
          listenable: Listenable.merge(_ctl.values.toList()),
          builder: (context, _) => Row(children: [
            Expanded(child: PillButton(label: '取消', onTap: () => _reply(false))),
            const SizedBox(width: Sp.x2),
            Expanded(flex: 2, child: PillButton(label: b.action, primary: true, onTap: _complete ? () => _reply(true) : null)),
          ]),
        ),
      ),
    ]);
  }

  Widget _field(FormInput f, {required bool isLast}) {
    final secret = f.kind == 'password';
    final shown = _revealed.contains(f.name);
    return TextField(
      controller: _ctl[f.name],
      obscureText: secret && !shown,
      enableSuggestions: !secret,
      autocorrect: false,
      keyboardType: switch (f.kind) {
        'code' => TextInputType.number,
        'email' => TextInputType.emailAddress,
        _ => TextInputType.text,
      },
      autofillHints: switch (f.kind) {
        'password' => const [AutofillHints.password],
        'code' => const [AutofillHints.oneTimeCode],
        'email' => const [AutofillHints.email],
        _ => widget.block.purpose == 'login' ? const [AutofillHints.username] : null,
      },
      textInputAction: isLast ? TextInputAction.done : TextInputAction.next,
      onSubmitted: isLast ? (_) => _reply(true) : null,
      decoration: InputDecoration(
        labelText: f.label,
        suffixIcon: secret
            ? IconButton(
                tooltip: shown ? '隐藏密码' : '显示密码',
                icon: Icon(shown ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: QuietAction.iconSize),
                onPressed: () => setState(() => shown ? _revealed.remove(f.name) : _revealed.add(f.name)),
              )
            : null,
      ),
    );
  }
}
