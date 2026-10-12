// REST 客户端：唯一发 HTTP 的地方。统一加 token、统一解析错误（{detail}）、401 统一登出。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'session.dart';

class ApiError implements Exception {
  ApiError(this.message, [this.status]);
  final String message;
  final int? status;

  /// 根本没连上（断网、超时、DNS）：这时界面退回离线缓存，而不是报错。
  bool get isNetwork => status == null;
  @override
  String toString() => message;
}

class Api {
  Api(this._ref);
  final Ref _ref;

  Session get _s => _ref.read(sessionProvider).value ?? const Session(server: '');

  Uri uri(String path, [Map<String, String>? query]) => Uri.parse('${_s.server}$path').replace(queryParameters: query);

  /// 图片/下载这类带不了请求头的地址：?token=
  String fileUrl(String path) => uri(path, {'token': _s.token ?? ''}).toString();

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_s.token != null) 'Authorization': 'Bearer ${_s.token}',
      };

  Future<dynamic> get(String path) => _send(() => http.get(uri(path), headers: _headers));
  Future<dynamic> post(String path, [Object? body]) =>
      _send(() => http.post(uri(path), headers: _headers, body: jsonEncode(body ?? {})));
  Future<dynamic> patch(String path, Object body) =>
      _send(() => http.patch(uri(path), headers: _headers, body: jsonEncode(body)));
  Future<dynamic> put(String path, Object body) =>
      _send(() => http.put(uri(path), headers: _headers, body: jsonEncode(body)));
  Future<dynamic> delete(String path) => _send(() => http.delete(uri(path), headers: _headers));

  /// 返回二进制的 POST（朗读的 mp3）：错误照常按 {detail} 抛 ApiError。
  Future<Uint8List> postBytes(String path, Object body) async {
    final http.Response res;
    try {
      res = await http.post(uri(path), headers: _headers, body: jsonEncode(body)).timeout(const Duration(seconds: 60));
    } on SocketException {
      throw ApiError('连不上服务器');
    } on TimeoutException {
      throw ApiError('连接超时');
    } on http.ClientException {
      throw ApiError('连不上服务器');
    }
    if (res.statusCode == 401) {
      await _ref.read(sessionProvider.notifier).signOut();
      throw ApiError('登录已过期', 401);
    }
    if (res.statusCode >= 400) {
      throw ApiError(_detail(_decode(res)) ?? '请求失败（${res.statusCode}）', res.statusCode);
    }
    return res.bodyBytes;
  }

  Future<dynamic> upload(String path, File file) => _send(() async {
        final req = http.MultipartRequest('POST', uri(path))
          ..headers['Authorization'] = 'Bearer ${_s.token ?? ''}'
          ..files.add(await http.MultipartFile.fromPath('file', file.path));
        return http.Response.fromStream(await req.send());
      });

  /// 登录不经过 session（还没有 token），所以单独一个方法。
  static Future<String> login(String server, String username, String password) async {
    final res = await http
        .post(Uri.parse('$server/api/auth/login'),
            headers: {'Content-Type': 'application/json'}, body: jsonEncode({'username': username, 'password': password}))
        .timeout(const Duration(seconds: 15));
    final data = _decode(res);
    if (res.statusCode >= 400) throw ApiError(_detail(data) ?? '登录失败', res.statusCode);
    return data['token'] as String;
  }

  Future<dynamic> _send(Future<http.Response> Function() call) async {
    final http.Response res;
    try {
      res = await call().timeout(const Duration(seconds: 30));
    } on SocketException {
      throw ApiError('连不上服务器');
    } on TimeoutException {
      throw ApiError('连接超时');
    } on http.ClientException {
      throw ApiError('连不上服务器');
    }
    if (res.statusCode == 401) {
      await _ref.read(sessionProvider.notifier).signOut();
      throw ApiError('登录已过期', 401);
    }
    final data = _decode(res);
    if (res.statusCode >= 400) throw ApiError(_detail(data) ?? '请求失败（${res.statusCode}）', res.statusCode);
    return data;
  }

  static dynamic _decode(http.Response r) {
    if (r.body.isEmpty) return null;
    try {
      return jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      return null;
    }
  }

  // detail 是字符串，或 {message, …}（如撤销冲突 {reason, message, conflicts}）
  static String? _detail(dynamic d) => d is Map
      ? (d['detail'] is String ? d['detail'] as String : (d['detail'] is Map && d['detail']['message'] is String ? d['detail']['message'] as String : null))
      : null;
}

final apiProvider = Provider<Api>(Api.new);
