// 新建面板：面板由助手按你的描述去搭（选数据源、定刷新节奏），所以这里只问“想看什么”，然后交给聊天。
// 入口：主页顶栏左侧的 +（设计 v2）；P3 的“创建一个新面板”胶囊也用它。
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../ui/sheets.dart';
import '../chat/open_conversation.dart';

String newPanelPrompt(String what) => '帮我在主页做一个面板：$what';

Future<void> createPanel(BuildContext context, WidgetRef ref) async {
  final v = await showFormSheet(
    context,
    title: '新面板',
    subtitle: '说说想在主页一眼看到什么，我来找数据、定刷新频率。',
    submit: '开始做',
    fields: const [FieldSpec('what', '想看什么', hint: '比如：每天早上的天气和课表', lines: 2)],
  );
  if (v == null || !context.mounted) return;
  askInNewChat(context, ref, newPanelPrompt(v['what']!));
}
