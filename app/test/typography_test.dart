// v3.2 守卫：全 App 一种字（打包的 MiSans，中英数字同一套），没有宋体、没有全局等宽数字和小标签字距；界面行高紧、只有正文宽。
import 'dart:io';

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final b in Brightness.values) {
    test('主题字样全是 MiSans + 黑体兜底（$b）', () {
      final t = buildTheme(b).textTheme;
      final styles = [t.displayMedium, t.displaySmall, t.headlineMedium, t.titleLarge, t.titleMedium, t.bodyLarge, t.bodyMedium, t.labelSmall];
      for (final s in styles) {
        expect(s!.fontFamily, Fonts.sans);
        expect(s.fontFamilyFallback, Fonts.sansFallback);
        expect(s.fontFamilyFallback!.any((f) => f.toLowerCase().contains('serif') || f.contains('Song')), isFalse);
        expect(s.fontFeatures ?? const [], isEmpty, reason: '数字比例宽：等宽只加在钟点列/计时/用量那几处');
        expect(s.letterSpacing ?? 0, lessThanOrEqualTo(0), reason: '小标签不再加字距（对照 Hark）');
      }
      expect(t.displayMedium!.fontWeight, Weights.strong); // 主标题 600，不再是偏细衬线
      expect(t.bodyMedium!.height, Fs.lineHeight);
      expect(Fs.lineHeight, lessThan(Fs.prose));
    });
  }

  test('打包的 MiSans 三种字重 + 许可注明都在，pubspec 声明了，旧 Inter 已删', () {
    for (final w in ['Regular', 'Medium', 'Semibold']) {
      expect(File('assets/fonts/MiSans-$w.ttf').existsSync(), isTrue);
    }
    expect(File('assets/fonts/MiSans-LICENSE.txt').existsSync(), isTrue);
    expect(File('assets/fonts/Inter-Regular.ttf').existsSync(), isFalse);
    final pub = File('pubspec.yaml').readAsStringSync();
    expect(pub, contains('family: MiSans'));
    expect(pub, isNot(contains('family: Inter')));
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
