// 安全（v2.58，对标 Hark 设置 → 安全 → 两步验证）：这台服务器能替你跑命令、开浏览器、动保险箱，只靠密码太薄。
// 版式和保险箱同一套：页头摘要 + 一句说明 → 一组行。打开分两步（扫码/本机添加 → 回填 6 位码），成功后一次性
// 展示恢复码（服务器同时退出其他设备，关掉后提示退了几台）；关闭 / 重新生成恢复码都要密码 + 一个码。
// 下面一节“登录设备”（v2.61）在 login_sessions_section.dart。规则在后端 app/two_factor.py，文字规则在 models/two_factor.dart。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/links.dart';
import '../../core/session.dart';
import '../../models/login_session.dart';
import '../../models/two_factor.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/sub_page.dart';
import 'login_sessions_section.dart';

/// 没登录（或测试里没有会话）不发请求、给 null：和 profileProvider 一样先看会话（抛错会被 Riverpod 自动重试）。
final twoFactorProvider = FutureProvider.autoDispose<TwoFactorStatus?>((ref) async {
  final s = await ref.watch(sessionProvider.future);
  if (!s.signedIn) return null;
  final j = await ref.read(apiProvider).get('/api/auth/2fa');
  return TwoFactorStatus.fromJson(Map<String, dynamic>.from(j as Map));
});

class SecurityScreen extends ConsumerWidget {
  const SecurityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(twoFactorProvider);
    return SubPage(
      title: const Text('安全'),
      body: PageBody(children: [
        FadeSwitcher(
          child: switch (state) {
            AsyncData(:final value?) => _Body(key: ValueKey('on-${value.enabled}'), status: value),
            AsyncData() || AsyncError() => EmptyHint(key: const ValueKey('err'), icon: Icons.cloud_off_rounded, title: '读不到安全设置', text: '检查网络后重试',
                action: TextButton(onPressed: () => ref.invalidate(twoFactorProvider), child: const Text('重试'))),
            _ => const SkeletonList(key: ValueKey('loading'), rows: 2),
          },
        ),
        LoginSessionsSection(delay: Motion.stagger(2)),
      ]),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({super.key, required this.status});
  final TwoFactorStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = status;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PageIntro(
        summary: twoFactorSummary(s),
        line: s.enabled
            ? '登录时除了密码，还要验证器 App 里的 6 位码；手机丢了用恢复码。'
            : '打开后，登录要多填验证器 App（Google Authenticator、Microsoft Authenticator 等）里的 6 位码。密码泄露了，别人也进不来。',
      ),
      const SizedBox(height: Sp.x4),
      FadeSlideIn(
        delay: Motion.stagger(1),
        child: GlassGroup(children: [
          if (!s.enabled)
            RowTile(
              key: const Key('tf-enable'),
              icon: Icons.shield_outlined,
              title: '打开两步验证',
              subtitle: s.pending ? '上次没设置完，重新扫一次码' : '大约一分钟，需要一个验证器 App',
              onTap: () => enableTwoFactor(context, ref),
            )
          else ...[
            RowTile(
              icon: Icons.verified_user_outlined,
              title: '两步验证',
              subtitle: s.enabledAt == null ? '已开' : '${formatDate(s.enabledAt!)} 打开',
            ),
            RowTile(
              key: const Key('tf-recovery'),
              icon: Icons.key_outlined,
              title: '恢复码',
              problem: s.recoveryLeft <= recoveryLow ? (s.recoveryLeft == 0 ? '用完了' : '快用完了') : null,
              subtitle: recoveryLine(s.recoveryLeft),
              onTap: () => regenerateCodes(context, ref),
            ),
            RowTile(
              key: const Key('tf-disable'),
              icon: Icons.remove_moderator_outlined,
              title: '关闭两步验证',
              subtitle: '需要密码和一个验证码',
              onTap: () => disableTwoFactor(context, ref),
            ),
          ],
        ]),
      ),
    ]);
  }
}

/// 打开：拿秘钥 → 扫码/本机添加 + 回填 → 一次性展示恢复码。
Future<void> enableTwoFactor(BuildContext context, WidgetRef ref) async {
  final api = ref.read(apiProvider);
  final TwoFactorSetup setup;
  try {
    setup = TwoFactorSetup.fromJson(Map<String, dynamic>.from(await api.post('/api/auth/2fa/setup') as Map));
  } catch (e) {
    if (context.mounted) showToast(context, e is ApiError ? e.message : '没打开：$e');
    return;
  }
  if (!context.mounted) return;
  final done = await showAppScrollSheet<Map>(context, builder: (_) => SetupSheet(setup: setup, api: api));
  ref.invalidate(twoFactorProvider);
  if (done == null || !context.mounted) return;
  // v2.61 打开 = 服务器顺手退出其他所有设备；本机是老 token 时换发了新 token
  await ref.read(sessionProvider.notifier).replaceToken('${done['token'] ?? ''}');
  ref.invalidate(loginSessionsProvider);
  if (!context.mounted) return;
  await showRecoveryCodes(context, [for (final c in done['recovery_codes'] as List) '$c'],
      account: setup.account, title: '两步验证已打开', note: enabledSignedOutToast((done['signed_out'] as num?)?.toInt() ?? 0));
}

Future<void> regenerateCodes(BuildContext context, WidgetRef ref) async {
  final v = await _confirm(context, title: '重新生成恢复码', subtitle: '旧的恢复码会全部作废', submit: '生成');
  if (v == null || !context.mounted) return;
  try {
    final j = await ref.read(apiProvider).post('/api/auth/2fa/recovery', v) as Map;
    ref.invalidate(twoFactorProvider);
    if (context.mounted) await showRecoveryCodes(context, [for (final c in j['recovery_codes'] as List) '$c'], title: '新的恢复码');
  } catch (e) {
    if (context.mounted) showToast(context, e is ApiError ? e.message : '没生成：$e');
  }
}

Future<void> disableTwoFactor(BuildContext context, WidgetRef ref) async {
  final v = await _confirm(context, title: '关闭两步验证', subtitle: '关掉后登录只要密码', submit: '关闭');
  if (v == null || !context.mounted) return;
  try {
    await ref.read(apiProvider).post('/api/auth/2fa/disable', v);
    ref.invalidate(twoFactorProvider);
    if (context.mounted) showToast(context, '两步验证已关闭');
  } catch (e) {
    if (context.mounted) showToast(context, e is ApiError ? e.message : '没关掉：$e');
  }
}

Future<Map<String, String>?> _confirm(BuildContext context, {required String title, required String subtitle, required String submit}) =>
    showFormSheet(context, title: title, subtitle: subtitle, submit: submit, fields: const [
      FieldSpec('password', '当前密码', obscure: true),
      FieldSpec('code', '验证码或恢复码', hint: '6 位数字，或 xxxx-xxxx', keyboard: TextInputType.visiblePassword),
    ]);

/// 设置弹层：二维码（另一台设备扫）/ 在这台手机上添加（otpauth 链接直接拉起验证器）/ 手动输入秘钥 → 回填 6 位码。
class SetupSheet extends StatefulWidget {
  const SetupSheet({super.key, required this.setup, required this.api});
  final TwoFactorSetup setup;
  final Api api;

  @override
  State<SetupSheet> createState() => _SetupSheetState();
}

class _SetupSheetState extends State<SetupSheet> {
  final _code = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _code.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final j = await widget.api.post('/api/auth/2fa/enable', {'code': cleanCode(_code.text)}) as Map;
      if (mounted) Navigator.pop(context, j);
    } catch (e) {
      if (mounted) setState(() => _error = e is ApiError ? e.message : '没打开：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = widget.setup;
    final ready = looksLikeTotp(_code.text) && !_busy;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      SheetList(padding: EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x5 + MediaQuery.viewInsetsOf(context).bottom), children: [
        Text('打开两步验证', style: context.text.titleLarge),
        const SizedBox(height: Sp.x1),
        Text('① 用验证器 App 扫码，或直接在这台手机上添加', style: context.text.bodySmall),
        const SizedBox(height: Sp.x4),
        if (s.drawable) FadeSlideIn(child: Center(child: QrMatrix(rows: s.qr))),
        const SizedBox(height: Sp.x3),
        Wrap(alignment: WrapAlignment.center, spacing: Sp.x2, runSpacing: Sp.x2, children: [
          OutlinedButton.icon(
            key: const Key('tf-open-app'),
            onPressed: () => openUrl(s.uri),
            icon: const Icon(Icons.phone_android_rounded, size: 18),
            label: const Text('在这台手机上添加'),
          ),
        ]),
        const SizedBox(height: Sp.x3),
        Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('或手动输入秘钥', style: context.text.labelSmall?.copyWith(color: p.text3)),
              SelectableText(s.secret, style: TextStyle(fontFamily: 'monospace', fontSize: Fs.sm, color: p.text)),
            ]),
          ),
          CopyAction(text: s.secret.replaceAll(' ', ''), tooltip: '复制秘钥'),
        ]),
        const SizedBox(height: Sp.x4),
        Text('② 填验证器里显示的 6 位码', style: context.text.bodySmall),
        const SizedBox(height: Sp.x2),
        TextField(
          key: const Key('tf-code'),
          controller: _code,
          keyboardType: TextInputType.number,
          autofillHints: const [AutofillHints.oneTimeCode],
          maxLength: 7,
          onSubmitted: (_) => ready ? _submit() : null,
          decoration: const InputDecoration(labelText: '6 位验证码', counterText: ''),
        ),
        FadeSwitcher(
          alignment: AlignmentDirectional.topStart,
          child: _error == null
              ? const SizedBox(key: ValueKey('ok'), height: Sp.x3)
              : Padding(
                  key: ValueKey(_error),
                  padding: const EdgeInsets.symmetric(vertical: Sp.x2),
                  child: Text(_error!, style: TextStyle(color: p.danger, fontSize: Fs.sm)),
                ),
        ),
        FilledButton(
          key: const Key('tf-confirm'),
          onPressed: ready ? _submit : null,
          child: FadeSwitcher(
            alignment: Alignment.center,
            child: _busy
                ? SizedBox(key: const ValueKey('busy'), width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.2, color: p.onAccent))
                : const Text('确认并打开', key: ValueKey('label')),
          ),
        ),
      ]),
    ]);
  }
}

/// 一次性展示恢复码：两列等宽字体、复制全部；关掉就再也看不到（服务器只存哈希）。
/// [note]：顺带发生的事（打开时退出了别的设备），写在说明下面。
Future<void> showRecoveryCodes(BuildContext context, List<String> codes, {String account = '', required String title, String? note}) =>
    showAppScrollSheet<void>(context, builder: (ctx) => _CodesSheet(codes: codes, account: account, title: title, note: note));

class _CodesSheet extends StatelessWidget {
  const _CodesSheet({required this.codes, required this.account, required this.title, this.note});
  final List<String> codes;
  final String account, title;
  final String? note;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      SheetList(padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x5), children: [
      Row(children: [
        Expanded(child: Text(title, style: context.text.titleLarge)),
        CopyAction(text: recoveryCodesText(codes, account: account), tooltip: '复制全部'),
      ]),
      const SizedBox(height: Sp.x1),
      Text('把这些恢复码存到安全的地方（密码管理器、纸上）。手机丢了时，每个能代替验证码登录一次。关掉这页后不会再显示。',
          style: context.text.bodySmall),
      if (note != null) ...[
        const SizedBox(height: Sp.x2),
        Row(children: [
          Icon(Icons.devices_rounded, size: 16, color: p.text3),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text(note!, style: context.text.bodySmall?.copyWith(color: p.text2))),
        ]),
      ],
      const SizedBox(height: Sp.x4),
      Container(
        padding: const EdgeInsets.all(Sp.x4),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
        child: Wrap(spacing: Sp.x5, runSpacing: Sp.x2, children: [
          for (final (i, c) in codes.indexed)
            FadeSlideIn(
              delay: Motion.stagger(i),
              child: SelectableText(c,
                  style: TextStyle(fontFamily: 'monospace', fontSize: Fs.md, color: p.text, fontFeatures: const [FontFeature.tabularFigures()])),
            ),
        ]),
      ),
      const SizedBox(height: Sp.x4),
      FilledButton(onPressed: () => Navigator.pop(context), child: const Text('我已存好')),
      ]),
    ]);
  }
}

/// 二维码：服务器给模块矩阵，这里画方块。永远黑码白底（QrColors），四周留白 QrColors.quiet 个模块。
class QrMatrix extends StatelessWidget {
  const QrMatrix({super.key, required this.rows});
  final List<String> rows;

  @override
  Widget build(BuildContext context) => Semantics(
        label: '两步验证二维码',
        image: true,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(Radii.inner),
          child: CustomPaint(size: const Size.square(QrColors.size), painter: _QrPainter(rows)),
        ),
      );
}

class _QrPainter extends CustomPainter {
  _QrPainter(this.rows);
  final List<String> rows;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = QrColors.light);
    final n = rows.length + QrColors.quiet * 2;
    final cell = size.width / n;
    final ink = Paint()
      ..color = QrColors.dark
      ..isAntiAlias = false;
    for (var y = 0; y < rows.length; y++) {
      for (var x = 0; x < rows[y].length; x++) {
        if (rows[y].codeUnitAt(x) == 0x31) {
          // 每格多画 0.5 像素，避免相邻方块之间露出细白缝
          canvas.drawRect(Rect.fromLTWH((x + QrColors.quiet) * cell, (y + QrColors.quiet) * cell, cell + 0.5, cell + 0.5), ink);
        }
      }
    }
  }

  @override
  bool shouldRepaint(_QrPainter old) => old.rows != rows;
}
