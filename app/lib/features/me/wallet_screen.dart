// 钱包（v2.74，对标 Hark 设置里的 Wallets）：存付款卡，结账时我在云浏览器里替你填（先在订单卡上问你一次）。
// 版式与保险箱同一套：页头摘要 + 说明 → 空时起步卡 → 卡列表（行错峰进场）。加卡弹层上方一张随输入变化的卡面。
// 卡号和安全码只上传一次，之后手机上、回复里都只有尾号（后端 app/wallet.py）。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/wallet.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/sub_page.dart';

class WalletScreen extends ConsumerWidget {
  const WalletScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cards = ref.watch(walletProvider);
    return SubPage(
      title: const Text('钱包'),
      actions: [IconButton(icon: const Icon(Icons.add_rounded), tooltip: '添加付款卡', onPressed: () => addCard(context, ref))],
      body: AsyncBody<PaymentCardItem>(
        value: cards,
        onRetry: () => ref.invalidate(walletProvider),
        builder: (list) => PullRefresh(
          onRefresh: () => ref.read(walletProvider.notifier).reload(),
          child: PageBody(children: [
            PageIntro(
                summary: walletSummary(list),
                line: '结账时我在云浏览器里替你填卡，付款前一定先在订单卡上问你。卡号加密存在你自己的服务器上，之后只显示尾号。'),
            if (list.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: Sp.x4),
                child: StarterCard(
                  title: '钱包是空的',
                  text: '加一张常用的卡，网上买东西、订酒店时就不用每次自己掏卡输号。',
                  starters: [PillButton(label: '添加付款卡', icon: Icons.credit_card_rounded, onTap: () => addCard(context, ref))],
                ),
              )
            else ...[
              SectionTitle('付款卡', count: list.length),
              ListGroup(children: [for (final (i, c) in list.indexed) _CardRow(c, delay: Motion.stagger(i, from: 1))]),
            ],
          ]),
        ),
      ),
    );
  }
}

/// 加一张卡：弹层填好 → 上传 → 列表重拉（服务器按添加先后排）。
Future<void> addCard(BuildContext context, WidgetRef ref) async {
  final v = await showAppSheet<Map<String, dynamic>>(context, builder: (_) => const AddCardSheet());
  if (v == null || !context.mounted) return;
  try {
    final notifier = ref.read(walletProvider.notifier);
    final saved = await notifier.create(v);
    await notifier.reload();
    if (context.mounted) showToast(context, '已加密保存「${saved.label}」');
  } on ApiError catch (e) {
    if (context.mounted) showToast(context, e.message);
  }
}

class _CardRow extends ConsumerWidget {
  const _CardRow(this.c, {this.delay = Duration.zero});
  final PaymentCardItem c;
  final Duration delay;

  Future<bool> _confirm(BuildContext context) =>
      confirmDanger(context, title: '删除「${c.label}」？', text: '之后结账我就不能替你填这张卡了。');

  @override
  Widget build(BuildContext context, WidgetRef ref) => SwipeToDelete(
        id: c.id,
        confirm: () => _confirm(context),
        onDelete: () => ref.read(walletProvider.notifier).remove(c.id),
        child: FadeSlideIn(
          delay: delay,
          child: RowTile(
            icon: Icons.credit_card_rounded,
            title: c.label,
            problem: c.expired ? '已过期' : null,
            subtitle: c.line,
            onTap: () => showActionSheet<void>(context, title: '${c.label} · ${c.line}', actions: [
              SheetAction(Icons.edit_outlined, '改名', onTap: () => _rename(context, ref)),
              SheetAction(Icons.delete_outline_rounded, '删除', danger: true, onTap: () async {
                if (await _confirm(context)) await ref.read(walletProvider.notifier).remove(c.id);
              }),
            ]),
          ),
        ),
      );

  Future<void> _rename(BuildContext context, WidgetRef ref) async {
    final v = await showFormSheet(context, title: '给这张卡起个名字', fields: [FieldSpec('label', '名字', initial: c.label, hint: '比如：招行信用卡')]);
    if (v == null || !context.mounted) return;
    try {
      await ref.read(walletProvider.notifier).patch(c.id, {'label': v['label']});
    } on ApiError catch (e) {
      if (context.mounted) showToast(context, e.message);
    }
  }
}

/// 加卡弹层：卡面（随输入实时变）+ 卡号 / 有效期 / 安全码 + 选填的持卡人、邮编、名字。
/// 点保存时才逐项校验（和后端同一套规则），错的那一格下面一句话；全对才关弹层交出 body。
class AddCardSheet extends StatefulWidget {
  const AddCardSheet({super.key});

  @override
  State<AddCardSheet> createState() => _AddCardSheetState();
}

class _AddCardSheetState extends State<AddCardSheet> {
  final _number = TextEditingController(), _exp = TextEditingController(), _cvc = TextEditingController();
  final _holder = TextEditingController(), _postal = TextEditingController(), _label = TextEditingController();
  bool _tried = false;

  @override
  void initState() {
    super.initState();
    for (final c in [_number, _exp, _cvc, _holder, _label]) {
      c.addListener(() => setState(() {}));
    }
  }

  @override
  void dispose() {
    for (final c in [_number, _exp, _cvc, _holder, _postal, _label]) {
      c.dispose();
    }
    super.dispose();
  }

  String get _brand => cardBrand(_number.text);
  String? get _numberErr => cardNumberError(_number.text);
  String? get _expErr => expiryError(_exp.text);
  String? get _cvcErr => cvcError(_cvc.text, _brand);
  bool get _filled => _number.text.isNotEmpty && _exp.text.isNotEmpty && _cvc.text.isNotEmpty;

  void _save() {
    setState(() => _tried = true);
    if (_numberErr != null || _expErr != null || _cvcErr != null) return;
    final e = parseExpiry(_exp.text)!;
    Navigator.pop(context, {
      'number': cardDigits(_number.text),
      'exp_month': e.$1,
      'exp_year': e.$2,
      'cvc': _cvc.text.trim(),
      'holder': _holder.text.trim(),
      'postal_code': _postal.text.trim(),
      'label': _label.text.trim(),
    });
  }

  Widget _field(TextEditingController c, String label,
          {String? hint, String? error, bool obscure = false, TextInputType? keyboard, List<TextInputFormatter>? formatters, bool autofocus = false}) =>
      Padding(
        padding: const EdgeInsets.only(top: Sp.x3),
        child: TextField(
          controller: c,
          autofocus: autofocus,
          obscureText: obscure,
          keyboardType: keyboard,
          inputFormatters: formatters,
          enableSuggestions: !obscure,
          autocorrect: false,
          decoration: InputDecoration(labelText: label, hintText: hint, errorText: _tried ? error : null),
        ),
      );

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, MediaQuery.viewInsetsOf(context).bottom + Sp.x5),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('添加付款卡', style: context.text.titleLarge),
            const SizedBox(height: Sp.x1),
            Text('只上传这一次，之后只显示尾号；付款前我一定先问你', style: context.text.bodySmall),
            const SizedBox(height: Sp.x4),
            Center(
              child: CardFace(
                label: _label.text.trim(),
                brand: _brand,
                number: _number.text,
                holder: _holder.text.trim(),
                exp: _exp.text,
              ),
            ),
            _field(_number, '卡号', hint: '4111 1111 1111 1111', error: _numberErr, autofocus: true, keyboard: TextInputType.number,
                formatters: [CardNumberFormatter()]),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: _field(_exp, '有效期', hint: 'MM/YY', error: _expErr, keyboard: TextInputType.number, formatters: [ExpiryFormatter()])),
              const SizedBox(width: Sp.x3),
              Expanded(
                  child: _field(_cvc, '安全码', hint: _brand == 'amex' ? '4 位' : '背面 3 位', error: _cvcErr, obscure: true,
                      keyboard: TextInputType.number, formatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)])),
            ]),
            _field(_holder, '持卡人（选填）', hint: '卡面上的名字', keyboard: TextInputType.name),
            _field(_postal, '账单邮编（选填）', hint: '有的海外网站要', keyboard: TextInputType.number),
            _field(_label, '名字（选填）', hint: '比如：招行信用卡'),
            const SizedBox(height: Sp.x4),
            FilledButton(onPressed: _filled ? _save : null, child: const Text('加密保存')),
          ]),
        ),
      );
}

/// 卡面：墨色底、卡组织在右上（换卡组织时换字动效）、卡号按位补点、底部持卡人和有效期。只用于展示，不可点。
class CardFace extends StatelessWidget {
  const CardFace({super.key, required this.label, required this.brand, required this.number, required this.holder, required this.exp});
  final String label, brand, number, holder, exp;

  /// 卡号位：输入了的显示数字，没输入的用 • 补到 16 位（运通 15 位），按卡组织分组。
  static String masked(String number, String brand) {
    final d = cardDigits(number);
    final total = brand == 'amex' ? 15 : (d.length > 16 ? d.length : 16);
    var seen = 0;
    final out = StringBuffer();
    for (final ch in groupCardNumber(d.padRight(total, '0')).split('')) {
      if (ch == ' ') {
        out.write(' ');
      } else {
        out.write(seen < d.length ? ch : '•');
        seen++;
      }
    }
    return out.toString();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final soft = context.text.labelSmall?.copyWith(color: p.onInk.withValues(alpha: 0.7));
    return Semantics(
      label: '卡面预览',
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Layout.cardFaceMax),
        child: AspectRatio(
          aspectRatio: Layout.cardFace,
          child: AnimatedContainer(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            padding: const EdgeInsets.all(Layout.cardPad),
            decoration: BoxDecoration(color: p.ink, borderRadius: BorderRadius.circular(Radii.lg)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Expanded(
                    child: Text(label.isEmpty ? '新卡' : label,
                        maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.titleSmall?.copyWith(color: p.onInk))),
                SwapSwitcher(child: Text(brandNames[brand] ?? '银行卡', key: ValueKey(brand), style: soft)),
              ]),
              const Spacer(),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(masked(number, brand), style: context.text.titleLarge?.copyWith(color: p.onInk, letterSpacing: 1.5)),
              ),
              const SizedBox(height: Sp.x3),
              Row(children: [
                Expanded(child: Text(holder.isEmpty ? '持卡人' : holder.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: soft)),
                Text(exp.isEmpty ? 'MM/YY' : exp, style: soft),
              ]),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 卡号输入：只留数字、最多 19 位、按卡组织分组；光标放到末尾（卡号几乎总是顺着输）。
class CardNumberFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    var d = cardDigits(newValue.text);
    if (d.length > 19) d = d.substring(0, 19);
    final t = groupCardNumber(d);
    return TextEditingValue(text: t, selection: TextSelection.collapsed(offset: t.length));
  }
}

/// 有效期输入：只留数字、最多 4 位，满 3 位自动插 “/”（0928 → 09/28）；首位 2–9 自动补 0（9 → 09/）。
class ExpiryFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    var d = cardDigits(newValue.text);
    if (d.length == 1 && int.parse(d) > 1) d = '0$d';
    if (d.length > 4) d = d.substring(0, 4);
    final deleting = newValue.text.length < oldValue.text.length;
    final t = d.length > 2 || (d.length == 2 && !deleting) ? '${d.substring(0, 2)}/${d.substring(2)}' : d;
    return TextEditingValue(text: t, selection: TextSelection.collapsed(offset: t.length));
  }
}
