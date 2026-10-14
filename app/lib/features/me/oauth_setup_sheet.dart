// v2.90.2 连接器页“服务器还差一步”的引导弹层：只给部署者看，告诉他在服务器上配一次 OAuth 应用。
// 内容全部来自 GET /api/connectors 每项的 setup（去哪注册、回调地址、.env 变量名），这里不自己拼；
// 完整步骤在仓库 docs/oauth-setup.md。网页版 frontend/src/features/me/OAuthSetupSheet.tsx 同一份文案。
import 'package:flutter/material.dart';

import '../../core/links.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/diff_view.dart' show monoFont;
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 重建读 .env 的两个容器（与 docs/oauth-setup.md 第 4 步一致）。
const oauthRestartCommand = 'docker compose up -d --force-recreate backend worker';

Future<void> showOAuthSetupSheet(BuildContext context, List<Connector> missing) =>
    showAppScrollSheet<void>(context, builder: (ctx) => OAuthSetupSheet(missing: missing));

class OAuthSetupSheet extends StatelessWidget {
  const OAuthSetupSheet({super.key, required this.missing});
  final List<Connector> missing;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final names = missing.map((c) => c.name).join(' / ');
    final callback = missing.map((c) => c.setup!.callback).firstWhere((u) => u.isNotEmpty, orElse: () => '');
    final env = [for (final c in missing) ...c.setup!.env].join('\n');
    var i = 0;
    Duration next() => Motion.stagger(i++);
    Widget step(String n, String title) => Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x4, Sp.x1, Sp.x2),
          child: Text('$n · $title', style: context.text.labelSmall),
        );
    Widget code(String text, String tooltip) => AppCard(
          padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x1, Sp.x2),
          child: Row(children: [
            Expanded(
              child: SelectableText(text,
                  style: TextStyle(fontFamily: monoFont, fontSize: Fs.xs, height: Fs.lineHeight, color: p.text)),
            ),
            CopyAction(text: text, tooltip: tooltip),
          ]),
        );
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x5, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('服务器配置', style: context.text.labelSmall),
          const SizedBox(height: Sp.x1),
          Text('配置 $names 授权', style: context.text.titleLarge),
          const SizedBox(height: Sp.x2),
          Text('一键授权由服务器上的 OAuth 应用完成。按以下三步配置一次，之后在连接器页点一下即可连接。',
              style: context.text.bodyMedium?.copyWith(color: p.text2)),
        ]),
      ),
      SheetList(padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x5), children: [
        step('1', '创建 OAuth 应用'),
        FadeSlideIn(
          delay: next(),
          child: ListGroup(children: [
            for (final c in missing)
              RowTile(
                icon: Icons.open_in_new_rounded,
                title: '在 ${c.name} 开发者后台创建',
                subtitle: Uri.tryParse(c.setup!.console)?.host ?? c.setup!.console,
                onTap: c.setup!.console.isEmpty ? null : () => openUrl(c.setup!.console),
              ),
          ]),
        ),
        step('2', '回调地址（两处填写同一个）'),
        FadeSlideIn(delay: next(), child: code(callback, '复制回调地址')),
        step('3', '填写服务器 .env 并重启'),
        FadeSlideIn(delay: next(), child: code(env, '复制变量名')),
        const SizedBox(height: Sp.x2),
        FadeSlideIn(delay: next(), child: code(oauthRestartCommand, '复制重启命令')),
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x4, Sp.x1, 0),
          child: Text(
            '${missing.any((c) => c.id == 'google') ? 'Google 还需开启 Gmail、日历、云端硬盘接口，并把你的账号加入测试用户。' : ''}'
            '完整步骤见仓库中的 docs/oauth-setup.md。',
            style: context.text.bodySmall?.copyWith(color: p.text3),
          ),
        ),
      ]),
    ]);
  }
}
