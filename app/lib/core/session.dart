// 登录态：服务器地址 + token。token 存系统安全存储（Keystore/Keychain），地址存普通偏好。
// 整个 App 只有这里读写它们；401 时调 signOut()，路由自动回到登录页，并清空离线缓存。
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'cache.dart';
import 'swr.dart';
import '../models/version.dart';

class Session {
  const Session({required this.server, this.token});
  final String server;
  final String? token;
  bool get signedIn => token != null && server.isNotEmpty;
}

class SessionNotifier extends AsyncNotifier<Session> {
  static const _serverKey = 'server';
  static const _tokenKey = 'token';
  final _secure = const FlutterSecureStorage();

  @override
  Future<Session> build() async {
    final prefs = await SharedPreferences.getInstance();
    return Session(server: prefs.getString(_serverKey) ?? '', token: await _secure.read(key: _tokenKey));
  }

  Future<void> signIn(String server, String token) async {
    final clean = server.trim().replaceAll(RegExp(r'/+$'), '');
    await (await SharedPreferences.getInstance()).setString(_serverKey, clean);
    await _secure.write(key: _tokenKey, value: token);
    state = AsyncData(Session(server: clean, token: token));
  }

  /// 本机主动退出登录：先告诉服务器作废这个 token（v2.61 登录设备，失败不拦），再清本地。
  Future<void> logout() async {
    try {
      await ref.read(apiProvider).post('/api/auth/logout').timeout(const Duration(seconds: 5));
    } catch (_) {}
    await signOut();
  }

  /// 服务器换发了新 token（老 token 设备“退出其他所有设备” / 打开两步验证时）：只换 token，不动缓存。
  Future<void> replaceToken(String token) async {
    final s = state.value;
    if (s == null || token.isEmpty) return;
    await _secure.write(key: _tokenKey, value: token);
    state = AsyncData(Session(server: s.server, token: token));
  }

  Future<void> signOut() async {
    await _secure.delete(key: _tokenKey);
    await ref.read(cacheStoreProvider).clear(); // 离线缓存跟着账号走
    state = AsyncData(Session(server: state.value?.server ?? ''));
  }
}

final sessionProvider = AsyncNotifierProvider<SessionNotifier, Session>(SessionNotifier.new);

/// 服务器版本（GET /api/version，公开接口）：关于页显示两端版本、低于 min_client 时提示更新。取不到 = null。
/// SWR（core/swr.dart）：再进关于页首帧就有版本，后台重取。
final serverVersionProvider =
    swrGet<ServerVersion?>('/api/version', ServerVersion.fromJson, requiresSession: true, orNull: true);
