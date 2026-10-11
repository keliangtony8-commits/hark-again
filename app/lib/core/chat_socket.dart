// 聊天 WebSocket：自动重连（指数退避）、连接状态流、4401 登出。
// 只管“线”本身：send() 写不出去就返回 false，不替上层排队——
// 待发送/重发是消息的状态，归 chat_controller 的发件箱管（界面才能把它画出来）。
import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'session.dart';

/// connecting：刚启动、还没连上过（不算离线，免得开屏闪“离线”）；
/// open：可以发；down：连过/试过但现在断了（重连中也保持 down，不来回闪）。
enum LinkStatus { connecting, open, down }

class ChatSocket {
  ChatSocket(this._ref) {
    _connect();
  }

  final Ref _ref;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _statusCtl = StreamController<LinkStatus>.broadcast();
  WebSocketChannel? _ch;
  Timer? _timer;
  bool _closed = false;
  int _retry = 0;
  LinkStatus _status = LinkStatus.connecting;

  Stream<Map<String, dynamic>> get events => _events.stream;

  /// 状态变化（只在真正变化时发）。
  Stream<LinkStatus> get status => _statusCtl.stream;
  LinkStatus get current => _status;

  void _set(LinkStatus s) {
    if (s == _status || _closed) return;
    _status = s;
    _statusCtl.add(s);
  }

  void _connect() {
    _timer = null;
    final s = _ref.read(sessionProvider).value;
    if (s == null || !s.signedIn || _closed) return;
    final base = s.server.replaceFirst(RegExp(r'^http'), 'ws');
    _ch?.sink.close(); // 手动重试时丢掉还在握手的旧连接
    final ch = WebSocketChannel.connect(Uri.parse('$base/ws?token=${Uri.encodeComponent(s.token!)}'));
    _ch = ch;
    ch.ready.then((_) {
      if (_ch != ch) return;
      _retry = 0;
      _set(LinkStatus.open);
    }).catchError((_) {});
    ch.stream.listen(
      (m) => _events.add(jsonDecode(m as String) as Map<String, dynamic>),
      onDone: () {
        if (_ch != ch) return;
        _set(LinkStatus.down);
        if (ch.closeCode == 4401) {
          _ref.read(sessionProvider.notifier).signOut();
        } else {
          _scheduleReconnect();
        }
      },
      onError: (_) {
        if (_ch == ch) _set(LinkStatus.down);
      },
    );
  }

  void _scheduleReconnect() {
    if (_closed || _timer != null) return;
    final wait = Duration(milliseconds: (1000 * (1 << _retry.clamp(0, 4))).clamp(1000, 10000));
    _retry++;
    _timer = Timer(wait, _connect);
  }

  /// 用户点“重试”：不等退避，立刻再连一次（已连上则什么都不做）。
  void reconnectNow() {
    if (_closed || _status == LinkStatus.open) return;
    _timer?.cancel();
    _retry = 0;
    _connect();
  }

  /// 写进线里就返回 true；没连上返回 false（由调用方决定排队还是报错）。
  bool send(Map<String, dynamic> payload) {
    if (_status != LinkStatus.open || _ch == null) return false;
    _ch!.sink.add(jsonEncode(payload));
    return true;
  }

  void close() {
    _closed = true;
    _timer?.cancel();
    _ch?.sink.close();
    _events.close();
    _statusCtl.close();
  }
}

final chatSocketProvider = Provider<ChatSocket>((ref) {
  ref.watch(sessionProvider.select((s) => s.value?.token)); // 换账号就重建连接
  final socket = ChatSocket(ref);
  ref.onDispose(socket.close);
  return socket;
});
