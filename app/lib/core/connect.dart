// 发起一个账户连接（OAuth）：问服务器要授权地址 → 系统浏览器打开；授权完服务器深链回 /me/connectors。
// 连接器页的“连接 / 重新授权”和聊天里的连接卡（v2.36）都只调这里。
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../ui/kit.dart';
import 'api.dart';
import 'links.dart';

Future<void> startConnect(BuildContext context, WidgetRef ref, String provider) async {
  try {
    final j = await ref.read(apiProvider).get('/api/connectors/$provider/start?client=app') as Map<String, dynamic>;
    await openUrl(j['url'] as String);
  } on ApiError catch (e) {
    if (context.mounted) showToast(context, e.message);
  }
}
