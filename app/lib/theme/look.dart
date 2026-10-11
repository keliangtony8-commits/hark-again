// 个性化外观偏好（设计 v2 P3）：头像颜色、减少透明度。和 appearance.dart（浅/深色）一样只存本机——
// 它们描述的是“这台设备上怎么看”，手机和电脑可以不同；也就不需要后端字段和迁移。
//   avatar：头像底色；null = 跟随强调色。只影响头像（glass.dart Avatar）。
//   solid：减少透明度（无障碍）。开了以后壁纸变纯色、所有玻璃变实色、不做任何背景模糊（低端机也省电）。
//          由 app.dart 用 GlassMode 注入，ui/glass.dart 的零件自己读，页面不用管。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

@immutable
class Look {
  const Look({this.avatar, this.solid = false});
  final Color? avatar;
  final bool solid;

  Look copyWith({Color? Function()? avatar, bool? solid}) => Look(avatar: avatar == null ? this.avatar : avatar(), solid: solid ?? this.solid);
}

class LookNotifier extends AsyncNotifier<Look> {
  static const _avatarKey = 'look.avatar';
  static const _solidKey = 'look.solid';

  @override
  Future<Look> build() async {
    final prefs = await SharedPreferences.getInstance();
    final argb = prefs.getInt(_avatarKey);
    return Look(avatar: argb == null ? null : Color(argb), solid: prefs.getBool(_solidKey) ?? false);
  }

  Look get _now => state.value ?? const Look();

  /// 先改界面再落盘（和外观偏好一致）：点色块的瞬间头像就变。
  Future<void> setAvatar(Color? c) async {
    state = AsyncData(_now.copyWith(avatar: () => c));
    final prefs = await SharedPreferences.getInstance();
    c == null ? await prefs.remove(_avatarKey) : await prefs.setInt(_avatarKey, c.toARGB32());
  }

  Future<void> setSolid(bool v) async {
    state = AsyncData(_now.copyWith(solid: v));
    await (await SharedPreferences.getInstance()).setBool(_solidKey, v);
  }
}

final lookProvider = AsyncNotifierProvider<LookNotifier, Look>(LookNotifier.new);
