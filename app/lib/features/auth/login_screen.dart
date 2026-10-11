// 登录：填自己服务器的地址 + 账号密码。地址会记住，下次只需密码。
// 设计 v2：和所有页面同一张壁纸（Backdrop），标题在壁纸上，表单收进一张玻璃卡（GlassSurface），
// 不另起一套登录专用的颜色/阴影。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';
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
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _server.text = ref.read(sessionProvider).value?.server ?? '';
  }

  @override
  void dispose() {
    for (final c in [_server, _user, _pass]) {
      c.dispose();
    }
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
      final token = await Api.login(server, _user.text.trim(), _pass.text);
      await ref.read(sessionProvider.notifier).signIn(server, token);
    } catch (e) {
      setState(() => _error = e is ApiError ? e.message : '连不上这个服务器，检查一下地址');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ready = _server.text.trim().isNotEmpty && _user.text.trim().isNotEmpty && _pass.text.isNotEmpty;
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
                      child: Container(
                        width: 64,
                        height: 64,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(Radii.lg),
                          gradient: LinearGradient(colors: [p.accent, p.accent.withValues(alpha: 0.7)], begin: Alignment.topLeft, end: Alignment.bottomRight),
                        ),
                        child: Icon(Icons.auto_awesome_rounded, color: p.onAccent, size: 32),
                      ),
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

  Widget _field(TextEditingController c, String label, String hint, {bool obscure = false, TextInputType? keyboard, VoidCallback? onSubmit}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: Sp.x3),
        child: TextField(
          controller: c,
          obscureText: obscure,
          keyboardType: keyboard,
          autocorrect: false,
          onChanged: (_) => setState(() {}),
          onSubmitted: onSubmit == null ? null : (_) => onSubmit(),
          decoration: InputDecoration(labelText: label, hintText: hint.isEmpty ? null : hint),
        ),
      );
}
