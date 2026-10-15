// 偏好设置（v2.81，docs/home-redesign.md B）：原来摊在“我的”页上的 外观（浅/深/跟随系统）· 减少透明度 · 头像颜色 · 回复语言
// 收进这一页一组行。外观是一行“外观 跟随系统 ›”，点开动作单选（同回复语言的选法），不再在列表里放一条分段按钮。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/appearance.dart';
import '../../theme/look.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/sub_page.dart';
import 'avatar_color_sheet.dart';
import 'reply_language.dart';

class PreferencesScreen extends ConsumerWidget {
  const PreferencesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appearance = ref.watch(appearanceProvider).value ?? Appearance.system;
    final look = ref.watch(lookProvider).value ?? const Look();
    return SubPage(
      title: const Text('偏好设置'),
      body: PageBody(children: [
        const PageIntro(line: '界面的样子和我回你的语言，改了立刻生效。'),
        FadeSlideIn(
          delay: Motion.stagger(1),
          child: ListGroup(children: [
            // v3.0：四行都可被“我的”页设置搜索直达（id 与 me_index.dart 的定位 id 相同）
            Spotlight(
              id: 'appearance',
              row: true,
              child: ListRow(
                key: const Key('appearance'),
                icon: appearance.icon,
                title: '外观',
                value: appearance.label,
                onTap: () => _pickAppearance(context, ref, appearance),
              ),
            ),
            Spotlight(
              id: 'solid',
              row: true,
              child: ListRow(
                icon: Icons.blur_off_rounded,
                title: '减少透明度',
                trailing: AppSwitch(key: const Key('solid'), value: look.solid, onChanged: (v) => ref.read(lookProvider.notifier).setSolid(v)),
              ),
            ),
            Spotlight(
              id: 'avatar-color',
              row: true,
              child: ListRow(
                icon: Icons.palette_outlined,
                title: '头像颜色',
                trailing: Avatar(initial: '', onTap: null, size: Sp.x5, color: look.avatar, tooltip: '当前头像颜色'),
                onTap: () => showAvatarColorSheet(context),
              ),
            ),
            const Spotlight(id: 'reply-language', row: true, child: ReplyLanguageTile()),
          ]),
        ),
      ]),
    );
  }

  Future<void> _pickAppearance(BuildContext context, WidgetRef ref, Appearance now) async {
    final a = await showActionSheet<Appearance>(context, title: '外观', actions: [
      for (final a in Appearance.values)
        SheetAction(a == now ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded, a.label, value: a),
    ]);
    if (a != null) await ref.read(appearanceProvider.notifier).set(a);
  }
}
