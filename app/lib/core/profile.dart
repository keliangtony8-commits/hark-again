// v2.92 §P 个人资料：称呼、给助手取的名字、头像、首次问候（GET/PATCH /api/profile，规则在后端 app/identity.py）。
// 取代 accountNameProvider（GET /api/auth/me 已删）：“我的”页页头、顶栏头像都读这一个 provider。
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api.dart';
import 'session.dart';

class Profile {
  const Profile({required this.username, this.displayName, this.assistantName, this.assistantDefault = 'Toyuis', this.avatar, this.greet = false});
  final String username;
  final String? displayName; // 用户希望被怎么称呼；null = 没说，界面用登录名
  final String? assistantName; // 给助手取的名字；null = 叫 assistantDefault
  final String assistantDefault;
  final String? avatar; // 头像路径（/api/profile/avatar/<版本>）；null = 纯色圆 + 首字母
  final bool greet; // 还没首次问候

  factory Profile.fromJson(Map<String, dynamic> j) {
    String? s(Object? v) => v is String && v.trim().isNotEmpty ? v.trim() : null;
    return Profile(
      username: s(j['username']) ?? '',
      displayName: s(j['display_name']),
      assistantName: s(j['assistant_name']),
      assistantDefault: s(j['assistant_default']) ?? 'Toyuis',
      avatar: s(j['avatar']),
      greet: j['greet'] == true,
    );
  }

  /// 页头大字、头像首字母用的名字：称呼优先，没有用登录名。
  String get name => displayName ?? username;
  String get assistant => assistantName ?? assistantDefault;

  /// 头像首字母：名字的第一个字（英文大写）；名字为空 → “我”。
  String get initial {
    final n = name.trim();
    if (n.isEmpty) return '我';
    return String.fromCharCode(n.runes.first).toUpperCase();
  }
}

class ProfileNotifier extends AsyncNotifier<Profile?> {
  Api get _api => ref.read(apiProvider);

  /// 没登录 → null；请求失败（断网、老服务器）→ null，界面退回“我的”/“我”。
  @override
  Future<Profile?> build() async {
    final s = await ref.watch(sessionProvider.future);
    if (!s.signedIn) return null;
    try {
      final j = await _api.get('/api/profile');
      return j is Map<String, dynamic> ? Profile.fromJson(j) : null;
    } catch (_) {
      return null;
    }
  }

  Profile _take(Object? j) {
    final p = Profile.fromJson(j as Map<String, dynamic>);
    state = AsyncData(p);
    return p;
  }

  /// 改称呼 / 助手名：只送 [fields] 里的键（空串 = 清除）。错误（如太长）以 ApiError 抛给调用方显示。
  Future<Profile> rename(Map<String, String> fields) async => _take(await _api.patch('/api/profile', fields));

  Future<Profile> setAvatar(File f) async => _take(await _api.upload('/api/profile/avatar', f));

  Future<Profile> clearAvatar() async => _take(await _api.delete('/api/profile/avatar'));

  /// 主聊天空白时调一次：返回问候对话的 id（问候过 → null）。之后本地标成已问候，免得再调。
  Future<String?> greet() async {
    final cur = state.value;
    if (cur == null || !cur.greet) return null;
    state = AsyncData(Profile(username: cur.username, displayName: cur.displayName, assistantName: cur.assistantName,
        assistantDefault: cur.assistantDefault, avatar: cur.avatar));
    try {
      final j = await _api.post('/api/profile/greet');
      final id = j is Map ? j['conversation_id'] : null;
      return id is String && id.isNotEmpty ? id : null;
    } catch (_) {
      return null;
    }
  }
}

final profileProvider = AsyncNotifierProvider<ProfileNotifier, Profile?>(ProfileNotifier.new);
