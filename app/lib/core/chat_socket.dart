// 聊天 WebSocket：自动重连（指数退避 + 抖动，无限次）、心跳、连接状态流、4401 登出。
// 只管“线”本身：send() 写不出去就返回 false，不替上层排队——
// 待发送/重发是消息的状态，归 chat_controller 的发件箱管（界面才能把它画出来）；
// 断线后回答在服务器上继续写，重连后的续传（turn.resume + seq 去重）也归 chat_controller。
// 重连节奏取自 Codex remote_control/websocket.rs 的 next_reconnect_delay（Apache-2.0，modified）：
// 退避翻倍到封顶、乘 [0.5, 1] 抖动避免一群客户端同时扑上来、连上保持满 Timing.socketStable 才清零；
// 心跳：服务器回过一次 pong（说明支持）后，Timing.socketDead 内什么都没收到就当线死了，主动断开重连。
import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../theme/tokens.dart';
import 'session.dart';

/// connecting：刚启动、还没连上过（不算离线，免得开屏闪“离线”）；
/// open：可以发；down：连过/试过但现在断了（重连中也保持 down，不来回闪）。
enum LinkStatus { connecting, open, down }

/// 第 [attempt] 次重连前等多久（attempt 从 0 起）。[jitter] ∈ [0, 1]，测试可固定。
Duration reconnectDelay(int attempt, {double? jitter}) {
  final base = Timing.socketBackoffMin * (1 << attempt.clamp(0, 10));
  final capped = base > Timing.socketBackoffMax ? Timing.socketBackoffMax : base;
  final j = jitter ?? Random().nextDouble();
  return capped * (0.5 + 0.5 * j.clamp(0.0, 1.0));
}

class ChatSocket {
  ChatSocket(this._ref) {
    _connect();
  }

  final Ref _ref;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _statusCtl = StreamController<LinkStatus>.broadcast();
  WebSocketChannel? _ch;
  Timer? _timer;
  Timer? _ping;
  bool _closed = false;
  int _retry = 0;
  bool _heartbeat = false; // 服务器回过 pong：支持心跳，才按“多久没收到”判断死线（老服务器不回，不能误判）
  DateTime _lastRx = DateTime.now();
  DateTime? _openedAt;
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
      _openedAt = _lastRx = DateTime.now();
      _set(LinkStatus.open);
      _ping?.cancel();
      _ping = Timer.periodic(Timing.socketPing, (_) => _beat(ch));
    }).catchError((_) {});
    ch.stream.listen(
      (m) {
        if (_ch != ch) return;
        _lastRx = DateTime.now();
        final e = jsonDecode(m as String) as Map<String, dynamic>;
        if (e['type'] == 'pong') {
          _heartbeat = true;
          return;
        }
        _events.add(e);
      },
      onDone: () {
        if (_ch != ch) return;
        _lost();
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

  void _beat(WebSocketChannel ch) {
    if (_ch != ch || _status != LinkStatus.open) return;
    if (_heartbeat && DateTime.now().difference(_lastRx) > Timing.socketDead) {
      // 线已经死了（手机切网、NAT 超时），系统还没报：主动丢掉它重连
      _ch = null;
      ch.sink.close();
      _lost();
      _scheduleReconnect();
      return;
    }
    ch.sink.add(jsonEncode({'type': 'ping'}));
  }

  void _lost() {
    _ping?.cancel();
    _ping = null;
    final opened = _openedAt;
    if (opened != null && DateTime.now().difference(opened) >= Timing.socketStable) _retry = 0;
    _openedAt = null;
    _set(LinkStatus.down);
  }

  void _scheduleReconnect() {
    if (_closed || _timer != null) return;
    final wait = reconnectDelay(_retry);
    _retry++;
    _timer = Timer(wait, _connect);
  }

  /// 用户点“重试”/ App 回到前台：不等退避，立刻再连一次（已连上则什么都不做）。
  void reconnectNow() {
    if (_closed || _status == LinkStatus.open) return;
    _timer?.cancel();
    _timer = null;
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
    _ping?.cancel();
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
