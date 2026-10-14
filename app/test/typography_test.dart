// v2.83 §G 守卫：全 App 一种无衬线字（Inter + 系统中文），没有宋体；界面行高紧、只有正文宽。
import 'dart:io';

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final b in Brightness.values) {
    test('主题字样全是 Inter + 中文黑体兜底（$b）', () {
      final t = buildTheme(b).textTheme;
      final styles = [t.displayMedium, t.displaySmall, t.headlineMedium, t.titleLarge, t.titleMedium, t.bodyLarge, t.bodyMedium, t.labelSmall];
      for (final s in styles) {
        expect(s!.fontFamily, Fonts.sans);
        expect(s.fontFamilyFallback, Fonts.sansFallback);
        expect(s.fontFamilyFallback!.any((f) => f.toLowerCase().contains('serif') || f.contains('Song')), isFalse);
      }
      expect(t.displayMedium!.fontWeight, Weights.strong); // 主标题 600，不再是偏细衬线
      expect(t.bodyMedium!.height, Fs.lineHeight);
      expect(Fs.lineHeight, lessThan(Fs.prose));
    });
  }

  test('打包的 Inter 三种字重都在，pubspec 声明了', () {
    for (final w in ['Regular', 'Medium', 'SemiBold']) {
      expect(File('assets/fonts/Inter-$w.ttf').existsSync(), isTrue);
    }
    expect(File('pubspec.yaml').readAsStringSync(), contains('family: Inter'));
  });

  test('源码里没有衬线字族', () {
    final hits = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'))
        .where((f) => RegExp(r"\.serif\b|Fonts\.serif|'serif'").hasMatch(f.readAsStringSync()))
        .map((f) => f.path)
        .toList();
    expect(hits, isEmpty);
  });
}
