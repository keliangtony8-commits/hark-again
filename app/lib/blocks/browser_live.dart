// 浏览器实时画面的连接（v2.89 §M，取代 v2.82 截图轮询 + 点按 HTTP）：一条 WS /api/browser/live，
// 下行 JPEG 帧（服务器只在画面变了时推），上行接管输入（0–1 坐标，消息格式见 docs/protocol.md）。
// 卡片（browser_block.dart）拥有它，接管页（browser_takeover.dart）复用同一个——同一条线，不再开第二条。
// hold()/release() 计数：有人在看才连；App 退到后台就断开，回来重连（服务器先补最后一帧，不黑屏）。
// 状态规则在 models/browser_view.dart（liveStateAfterClose / liveRetryDelay）；网页版 lib/browserLive.ts 同一套。
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../core/api.dart';
import '../models/browser_view.dart';

/// 一条实时画面连接的最小接口（测试换成假的）。
abstract class LiveSocket {
  Future<void> get ready;
  Stream<dynamic> get stream;
  int? get closeCode;
  void send(String message);
  void close();
}

class _ChannelSocket implements LiveSocket {
  _ChannelSocket(Uri uri) : _ch = WebSocketChannel.connect(uri);
  final WebSocketChannel _ch;
  @override
  Future<void> get ready => _ch.ready;
  @override
  Stream<dynamic> get stream => _ch.stream;
  @override
  int? get closeCode => _ch.closeCode;
  @override
  void send(String message) => _ch.sink.add(message);
  @override
  void close() => _ch.sink.close();
}

typedef LiveConnect = LiveSocket Function(Uri uri);

/// 怎么连（测试 override 成假连接）。
final liveConnectProvider = Provider<LiveConnect>((ref) => _ChannelSocket.new);

/// 卡片会话的实时画面地址：http(s) → ws(s)，带 token、会话名；[reopen] = 浏览器关着就用存好的登录重开。
Uri liveUri(Api api, String session, {bool reopen = false}) {
  final u = Uri.parse(api.fileUrl('/api/browser/live'));
  return u.replace(
    scheme: u.scheme == 'https' ? 'wss' : 'ws',
    queryParameters: {...u.queryParameters, 'session': session, if (reopen) 'open': '1'},
  );
}

class BrowserLive extends ChangeNotifier {
  BrowserLive({required this.uri, required this.connect, bool openingAtStart = false}) : _opening = openingAtStart {
    _life = AppLifecycleListener(onHide: _pause, onShow: _resume);
  }

  final Uri Function(bool reopen) uri;
  final LiveConnect connect;
  late final AppLifecycleListener _life;
  LiveSocket? _sock;
  Timer? _retry;
  int _attempt = 0, _holds = 0, _px = 0;
  bool _opening, _hidden = false, _reopen = false, _dropped = false;

  LiveState state = LiveState.connecting;
  Uint8List? frame;

  bool get hasFrame => frame != null;
  bool get isOpening => _opening;

  /// 卡片的 block.live 变了（还在打开时“浏览器没开”不算关闭）。
  set opening(bool v) {
    if (v == _opening) return;
    _opening = v;
    if (!v && state == LiveState.reconnecting && _sock == null) _dial(); // 打开完成：马上再连，不等退避
  }

  void hold() {
    if (_holds++ == 0) _dial();
  }

  void release() {
    if (_holds == 0) return;
    if (--_holds > 0) return;
    _hang();
    if (_dropped) dispose();
  }

  /// 卡片不要它了（卡片拆掉）：接管页还拿着就等它放手再释放。
  void drop() {
    _dropped = true;
    if (_holds == 0) dispose();
  }

  /// closed / down 时的“重新打开”：带 open=1 连，服务器用存好的登录回到最后网址。
  void reopen() {
    _reopen = true;
    _attempt = 0;
    _hang();
    _set(LiveState.connecting);
    _dial();
  }

  /// 画面的物理像素宽：服务器按它缩小帧（手机省流量）。同一个值不重发。
  void view(double px) {
    final v = px.round();
    if (v <= 0 || v == _px) return;
    _px = v;
    send({'t': 'view', 'px': v});
  }

  /// 接管输入；没连上就丢掉（画面会说明一切）。返回是否发出。
  bool send(Map<String, Object?> m) {
    final s = _sock;
    if (s == null || state != LiveState.live) return false;
    s.send(jsonEncode(m));
    return true;
  }

  void _set(LiveState s) {
    if (state == s) return;
    state = s;
    notifyListeners();
  }

  void _dial() {
    _retry?.cancel();
    _retry = null;
    if (_holds == 0 || _hidden || _sock != null) return;
    final sock = connect(uri(_reopen));
    _reopen = false;
    _sock = sock;
    sock.ready.then((_) {
      if (_sock != sock) return;
      _attempt = 0;
      _set(LiveState.live);
      if (_px > 0) sock.send(jsonEncode({'t': 'view', 'px': _px}));
    }, onError: (_) {});
    sock.stream.listen((m) {
      if (_sock != sock || m is! List<int>) return;
      final prev = frame;
      frame = m is Uint8List ? m : Uint8List.fromList(m);
      if (prev != null) MemoryImage(prev).evict(); // 一帧一张图：旧帧别留在图片缓存里
      state = LiveState.live;
      notifyListeners();
    }, onDone: () => _closed(sock), onError: (_) => _closed(sock), cancelOnError: true);
  }

  void _closed(LiveSocket sock) {
    if (_sock != sock) return;
    _sock = null;
    final next = liveStateAfterClose(sock.closeCode, opening: _opening);
    _set(next);
    if (next != LiveState.reconnecting || _holds == 0 || _hidden) return;
    _retry = Timer(liveRetryDelay(_attempt++), _dial);
  }

  void _hang() {
    _retry?.cancel();
    _retry = null;
    final s = _sock;
    _sock = null;
    s?.close();
  }

  void _pause() {
    _hidden = true;
    _hang();
  }

  void _resume() {
    if (!_hidden) return;
    _hidden = false;
    if (state == LiveState.closed || state == LiveState.down) return; // 等用户点“重新打开”
    _set(LiveState.reconnecting);
    _dial();
  }

  @override
  void dispose() {
    _hang();
    _life.dispose();
    final f = frame;
    if (f != null) MemoryImage(f).evict();
    super.dispose();
  }
}
