// 表单卡：任务进行中向你要登录信息、验证码、命令环境变量，或助手缺的信息（对标 Hark 任务里“在它自己的表单上问你”）。
// - env 卡（request_env）：一个遮住的输入框，值直接存进保险箱，助手只知道变量名；太短时框下提示“至少 N 个字符”。
// - 等填写（pending）：输入框 + 取消 / 提交；登录卡放进 AutofillGroup，安卓/iOS 的密码管理器能直接填。
//   info 卡（ask_user）：标题下一行说为什么问；有候选的输入框下面是可点选的小块（点了填进框里，仍可改）；选填可空着。
// - 提交后：输入框收起、清空，只剩一行状态（已填写 / 已取消 / 已过期）；login / code 的值从不进卡片和本地缓存，
//   info 卡由服务器把 answers 写回卡片，这里展示成一问一答。
// - 断线没发出去（onForm 返回 false）：保留输入，用户连上再点。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/field_border.dart';
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
        'submitted' => (b.purpose == 'env' ? '已存好' : '已填写', p.text2),
        'cancelled' => ('已取消', p.text3),
        'expired' => ('已过期', p.text3),
        _ => ('等你填写', p.warning),
      };

  static IconData iconOf(FormBlock b) => switch (b.purpose) {
        'login' => Icons.lock_outline_rounded,
        'code' => Icons.sms_outlined,
        'env' || 'token' => Icons.key_rounded,
        _ => Icons.edit_note_rounded,
      };

  /// 输入框下的那行“你填的去哪了”。
  static String privacyNote(String purpose) => switch (purpose) {
        'info' => '你填的内容会交给助手，用来接着办这件事',
        'env' => '只存进保险箱，助手只知道名字；在 我的 → 保险箱 里可以换值或删除',
        'token' => '只用来连接这台 MCP 服务器，加密保存，助手看不到；在 连接器 页可以删掉',
        _ => '只交给浏览器填写，助手看不到',
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

  bool get _complete => widget.block.completeWith({for (final e in _ctl.entries) e.key: e.value.text});

  void _reply(bool submit) {
    final onForm = BlockActions.of(context)?.onForm;
    if (onForm == null || _sent) return;
    if (submit && !_complete) return;
    final values = submit ? {for (final e in _ctl.entries) e.key: e.value.text} : null;
    if (!onForm(widget.block.id, values, submit && _remember)) return;
    if (submit) TextInput.finishAutofillContext(shouldSave: widget.block.purpose == 'login'); // 只有登录让系统密码管理器保存
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
              if (b.note != null && b.note!.isNotEmpty)
                Text(b.note!, style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 2, overflow: TextOverflow.ellipsis),
            ]),
          ),
          SwapSwitcher(
            child: Text(label, key: ValueKey(b.state), style: context.text.labelSmall?.copyWith(color: color, fontWeight: Weights.title)),
          ),
        ]),
        RiseSwitcher(child: open ? _body(context, b) : (b.answers.isEmpty ? null : _Answers(b.answers))),
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
              Expanded(child: Text(b.purpose == 'info' ? '记进记忆，下次不用再问' : '记住到保险箱，下次自动登录', style: context.text.bodySmall)),
              Switch(value: _remember, onChanged: (v) => setState(() => _remember = v)),
            ]),
          ),
        ),
      Padding(
        padding: const EdgeInsets.only(top: Sp.x2),
        child: Row(children: [
          Icon(b.purpose == 'info' ? Icons.forum_outlined : Icons.visibility_off_outlined, size: Fs.sm, color: p.text3),
          const SizedBox(width: Sp.x1),
          Expanded(
            child: Text(FormBlockView.privacyNote(b.purpose),
                style: context.text.bodySmall?.copyWith(color: p.text3)),
          ),
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
    final input = _input(f, isLast: isLast);
    if (f.options.isEmpty) return input;
    final ctl = _ctl[f.name]!;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      input,
      const SizedBox(height: Sp.x2),
      ListenableBuilder(
        listenable: ctl,
        builder: (context, _) => Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
          for (final o in f.options)
            ChoiceChip(
              label: Text(o),
              selected: ctl.text.trim() == o,
              showCheckmark: false,
              visualDensity: VisualDensity.compact,
              onSelected: (_) => ctl.value = TextEditingValue(text: o, selection: TextSelection.collapsed(offset: o.length)),
            ),
        ]),
      ),
    ]);
  }

  Widget _input(FormInput f, {required bool isLast}) {
    if (f.minLength <= 0) return _textField(f, isLast: isLast);
    return ListenableBuilder(
      listenable: _ctl[f.name]!,
      builder: (context, _) => _textField(f, isLast: isLast, short: f.tooShort(_ctl[f.name]!.text)),
    );
  }

  Widget _textField(FormInput f, {required bool isLast, bool short = false}) {
    final secret = f.kind == 'password';
    final multiline = f.kind == 'multiline';
    final shown = _revealed.contains(f.name);
    return TextField(
      controller: _ctl[f.name],
      minLines: 1, // 多行也从一行起，边写边长到 4 行（v0.92 表单变矮）
      maxLines: multiline ? 4 : 1,
      obscureText: secret && !shown,
      enableSuggestions: !secret,
      autocorrect: false,
      keyboardType: switch (f.kind) {
        'code' => TextInputType.number,
        'email' => TextInputType.emailAddress,
        'phone' => TextInputType.phone,
        'multiline' => TextInputType.multiline,
        _ => TextInputType.text,
      },
      autofillHints: widget.block.asksKey ? null : switch (f.kind) { // 环境变量 / 令牌不是网站密码：别让密码管理器存
        'password' => const [AutofillHints.password],
        'code' => const [AutofillHints.oneTimeCode],
        'email' => const [AutofillHints.email],
        'phone' => const [AutofillHints.telephoneNumber],
        _ => widget.block.purpose == 'login' ? const [AutofillHints.username] : null,
      },
      textInputAction: multiline ? TextInputAction.newline : (isLast ? TextInputAction.done : TextInputAction.next),
      onSubmitted: isLast && !multiline ? (_) => _reply(true) : null,
      decoration: compactField(
        label: f.optional ? '${f.label}（选填）' : f.label,
        helper: short ? '至少 ${f.minLength} 个字符' : null,
        suffix: secret
            ? IconButton(
                tooltip: shown ? '隐藏密码' : '显示密码',
                visualDensity: VisualDensity.compact,
                icon: Icon(shown ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: QuietAction.iconSize),
                onPressed: () => setState(() => shown ? _revealed.remove(f.name) : _revealed.add(f.name)),
              )
            : null,
      ),
    );
  }
}

/// info 卡提交后的一问一答：小标签 + 可选中复制的答案，逐行轻轻浮入。
class _Answers extends StatelessWidget {
  const _Answers(this.answers);
  final List<FormAnswer> answers;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      key: const ValueKey('answers'),
      padding: const EdgeInsets.only(top: Sp.x3),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final (i, a) in answers.indexed)
          FadeSlideIn(
            delay: Motion.stagger(i),
            child: Padding(
              padding: EdgeInsets.only(top: i == 0 ? 0 : Sp.x2),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(a.label, style: context.text.labelSmall?.copyWith(color: p.text3)),
                SelectableText(a.value, style: context.text.bodyMedium),
              ]),
            ),
          ),
      ]),
    );
  }
}
