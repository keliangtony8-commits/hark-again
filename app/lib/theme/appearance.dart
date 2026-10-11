// 外观偏好：跟随系统 / 浅色 / 深色。只存本机（SharedPreferences），不上服务器——
// 手机和电脑各自跟随自己的系统更自然。App 只有 app.dart 读它，“我的 → 外观”写它。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum Appearance {
  system('跟随系统', Icons.brightness_auto_outlined, ThemeMode.system),
  light('浅色', Icons.light_mode_outlined, ThemeMode.light),
  dark('深色', Icons.dark_mode_outlined, ThemeMode.dark);

  const Appearance(this.label, this.icon, this.mode);
  final String label;
  final IconData icon;
  final ThemeMode mode;

  static Appearance parse(String? s) => values.firstWhere((a) => a.name == s, orElse: () => system);
}

class AppearanceNotifier extends AsyncNotifier<Appearance> {
  static const _key = 'appearance';

  @override
  Future<Appearance> build() async => Appearance.parse((await SharedPreferences.getInstance()).getString(_key));

  Future<void> set(Appearance a) async {
    state = AsyncData(a); // 先切界面（主题自带过渡），再落盘
    await (await SharedPreferences.getInstance()).setString(_key, a.name);
  }
}

final appearanceProvider = AsyncNotifierProvider<AppearanceNotifier, Appearance>(AppearanceNotifier.new);
