// 项目的名称和图标：新建与编辑共用这一个入口（项目列表的 +、卡片菜单“编辑”、项目聊天顶栏的设置）。
// 规则和档案不在这里改，它们有自己的页面（project_brief_screen.dart），这里只管“它叫什么、长什么样”。
// 返回要发给服务端的 body：新建 = 全量；编辑 = 只含改过的字段（空 map = 什么也没改，调用方不发请求）。
import 'package:flutter/material.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 可选图标（网页版 ProjectForm.tsx 的 EMOJIS 同一组、同一顺序）。
const projectEmojis = ['📁', '📚', '💼', '✈️', '🏠', '💡', '🧪', '🎯', '💻', '🎓'];

Future<Map<String, dynamic>?> showProjectForm(BuildContext context, {Project? project}) async {
  final emoji = ValueNotifier(project?.emoji ?? projectEmojis.first);
  try {
    final v = await showFormSheet(
      context,
      title: project == null ? '新项目' : '编辑项目',
      submit: project == null ? '创建' : '保存',
      fields: [FieldSpec('name', '名称', hint: '比如：期末复习', initial: project?.name ?? '')],
      extra: EmojiPicker(value: emoji),
    );
    if (v == null) return null;
    final body = {'name': v['name'], 'emoji': emoji.value};
    if (project == null) return body;
    return {
      if (body['name'] != project.name) 'name': body['name'],
      if (body['emoji'] != project.emoji) 'emoji': body['emoji'],
    };
  } finally {
    emoji.dispose();
  }
}

/// 一行图标格子：选中的那格换成玻璃底 + 一圈墨色细边，图标轻轻放大（按压同款弹性）。
class EmojiPicker extends StatelessWidget {
  const EmojiPicker({super.key, required this.value});
  final ValueNotifier<String> value;

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<String>(
        valueListenable: value,
        builder: (context, chosen, _) {
          final p = context.palette;
          final current = projectEmojis.contains(chosen) ? chosen : null;
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('图标', style: context.text.labelSmall),
            const SizedBox(height: Sp.x2),
            Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
              for (final e in [if (current == null) chosen, ...projectEmojis])
                Pressable(
                  onTap: () => value.value = e,
                  scale: 0.9,
                  semanticLabel: e == chosen ? '图标 $e，已选' : '图标 $e',
                  child: AnimatedContainer(
                    duration: context.motion(Motion.fast),
                    curve: Motion.ease,
                    width: A11y.minTap,
                    height: A11y.minTap,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: e == chosen ? context.cardFill : context.tileFill,
                      border: Border.all(color: e == chosen ? p.ink : Colors.transparent, width: 1.5),
                      borderRadius: BorderRadius.circular(Radii.md),
                    ),
                    child: AnimatedScale(
                      scale: e == chosen ? 1.12 : 1,
                      duration: context.motion(Motion.base),
                      curve: Motion.spring,
                      child: Text(e, style: context.text.titleLarge),
                    ),
                  ),
                ),
            ]),
          ]);
        },
      );
}
