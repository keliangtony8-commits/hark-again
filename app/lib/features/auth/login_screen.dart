// 登录：填自己服务器的地址 + 账号密码。地址会记住，下次只需密码。
// 设计 v2：和所有页面同一张壁纸（Backdrop），标题在壁纸上，表单收进一张玻璃卡（GlassSurface），
// 不另起一套登录专用的颜色/阴影。
// v2.58 两步验证：服务器回 428 → 密码框下面展开“验证码”框（FadeSwitcher 长出来、自动聚焦），再点登录带上码；
// 填恢复码也行。改了地址/用户名就收起（换了服务器，未必开着）。
import 'package:flutter/material.dart';
import 'package:assistant/ui/brand_mark.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../models/two_factor.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _server = TextEditingController();
  final _user = TextEditingController();
  final _pass = TextEditingController();
  final _code = TextEditingController();
  final _codeFocus = FocusNode();
  bool _needCode = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _server.text = ref.read(sessionProvider).value?.server ?? '';
  }

  @override
  void dispose() {
    for (final c in [_server, _user, _pass, _code]) {
      c.dispose();
    }
    _codeFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    var server = _server.text.trim().replaceAll(RegExp(r'/+$'), '');
    if (server.isNotEmpty && !server.startsWith('http')) server = 'https://$server';
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final token = await Api.login(server, _user.text.trim(), _pass.text, code: _needCode ? cleanCode(_code.text) : null);
      await ref.read(sessionProvider.notifier).signIn(server, token);
    } catch (e) {
      if (e is ApiError && e.status == 428) {
        setState(() {
          _needCode = true;
          _error = null;
        });
        WidgetsBinding.instance.addPostFrameCallback((_) => _codeFocus.requestFocus());
      } else {
        setState(() => _error = e is ApiError ? e.message : '连不上这个服务器，检查一下地址');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ready = _server.text.trim().isNotEmpty && _user.text.trim().isNotEmpty && _pass.text.isNotEmpty && (!_needCode || cleanCode(_code.text).length >= 6);
    return Backdrop(
      child: Scaffold(
        backgroundColor: Colors.transparent, // 透出壁纸
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(Layout.gutter),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 400),
                child: FadeSlideIn(
                  offset: 16,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: const BrandMark(size: 64),
                    ),
                    const SizedBox(height: Sp.x5),
                    Text('你好', style: context.text.displaySmall),
                    const SizedBox(height: Sp.x1),
                    Text('连接你自己的服务器，开始使用', style: context.text.bodyLarge?.copyWith(color: p.text2)),
                    const SizedBox(height: Sp.x6),
                    GlassSurface(
                      padding: const EdgeInsets.all(Sp.x5 - Sp.x1),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        _field(_server, '服务器地址', 'https://your.domain', keyboard: TextInputType.url),
                        _field(_user, '用户名', ''),
                        _field(_pass, '密码', '', obscure: true, onSubmit: ready ? _submit : null),
                        FadeSwitcher(
                          alignment: AlignmentDirectional.topStart,
                          child: !_needCode
                              ? const SizedBox(key: ValueKey('no-code'), width: double.infinity)
                              : Column(key: const ValueKey('code'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                                  Padding(
                                    padding: const EdgeInsets.only(bottom: Sp.x2),
                                    child: Text('这个账号开了两步验证，填验证器里的 6 位码；手机不在身边就填一个恢复码。',
                                        style: context.text.bodySmall?.copyWith(color: p.text2)),
                                  ),
                                  _field(_code, '验证码', '6 位数字或恢复码',
                                      key: const Key('login-code'), focus: _codeFocus, keyboard: TextInputType.visiblePassword, onSubmit: ready ? _submit : null),
                                ]),
                        ),
                        AnimatedSwitcher(
                          duration: Motion.base,
                          child: _error == null
                              ? const SizedBox(height: Sp.x2)
                              : Padding(
                                  key: ValueKey(_error),
                                  padding: const EdgeInsets.only(bottom: Sp.x3),
                                  child: Text(_error!, style: TextStyle(color: p.danger, fontSize: Fs.sm)),
                                ),
                        ),
                        FilledButton(
                          onPressed: ready && !_busy ? _submit : null,
                          child: AnimatedSwitcher(
                            duration: Motion.fast,
                            child: _busy
                                ? SizedBox(key: const ValueKey('busy'), width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.2, color: p.onAccent))
                                : const Text('登录', key: ValueKey('label')),
                          ),
                        ),
                      ]),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _field(TextEditingController c, String label, String hint,
          {Key? key, FocusNode? focus, bool obscure = false, TextInputType? keyboard, VoidCallback? onSubmit}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: Sp.x3),
        child: TextField(
          key: key,
          focusNode: focus,
          controller: c,
          obscureText: obscure,
          keyboardType: keyboard,
          autocorrect: false,
          onChanged: (_) => setState(() {
            if (c == _server || c == _user) _needCode = false; // 换了服务器/账号：未必开着两步验证
          }),
          onSubmitted: onSubmit == null ? null : (_) => onSubmit(),
          decoration: InputDecoration(labelText: label, hintText: hint.isEmpty ? null : hint),
        ),
      );
}
