// 连接卡（v2.36）的纯逻辑：卡上那一行和按钮按连接器列表的实时状态定（不信卡里的快照——用户可能早就连好了）。
// 网页版 frontend/src/blocks/connectCard.ts 同规则。
import 'block.dart';
import 'resources.dart';

enum ConnectTone { action, done, warning, off }

typedef ConnectCardState = ({String line, String? button, ConnectTone tone});

/// [live] = 连接器列表里这一项；null = 列表还没到（或这个服务器已经没有这个连接器），按卡里的快照说。
ConnectCardState connectCardState(ConnectBlock b, Connector? live) {
  if (live == null) {
    return (line: b.desc, button: b.reconnect ? '重新连接' : '连接 ${b.name}', tone: ConnectTone.action);
  }
  // 服务器后来删了这个应用的配置（setup 非空）：照实说状态，不给点了会失败的按钮
  final can = live.authorizable;
  return switch (live.status) {
    'connected' => (line: _who('已连接', live.account), button: b.reconnect && can ? '换个账户' : null, tone: ConnectTone.done),
    'expired' => (line: _who('授权失效', live.account), button: can ? '重新连接' : null, tone: ConnectTone.warning),
    'unconfigured' => (line: '服务器还没配置这个应用', button: null, tone: ConnectTone.off),
    _ => (line: live.desc.isNotEmpty ? live.desc : b.desc, button: '连接 ${b.name}', tone: ConnectTone.action),
  };
}

String _who(String head, String? account) => account == null || account.isEmpty ? head : '$head · $account';
