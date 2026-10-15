// 震动反馈守卫（v2.99 E4）：HapticFeedback 只在 ui/haptics.dart（统一入口、尊重系统设置、不用 vibrate）；
// 开关只用 kit.dart 的 AppSwitch（切换时轻触由它给，页面不再各自直接用 Switch）。
import 'dart:io';

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final files = Directory('lib').listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart')).toList();
  String rel(File f) => f.path.replaceAll('\\', '/');

  test('HapticFeedback 只在 ui/haptics.dart，且不用 vibrate()', () {
    final bad = [for (final f in files) if (!rel(f).endsWith('lib/ui/haptics.dart') && f.readAsStringSync().contains('HapticFeedback')) rel(f)];
    expect(bad, isEmpty, reason: '震动走 Haptics.tap() / Haptics.press()');
    final code = File('lib/ui/haptics.dart').readAsLinesSync().where((l) => !l.trimLeft().startsWith('//')).join('\n');
    expect(code, isNot(contains('vibrate(')));
  });

  test('页面不直接用 Switch，只用 AppSwitch', () {
    final re = RegExp(r'(?<![A-Za-z])Switch(\.adaptive)?\(');
    final bad = [for (final f in files) if (!rel(f).endsWith('lib/ui/kit.dart') && re.hasMatch(f.readAsStringSync())) rel(f)];
    expect(bad, isEmpty);
  });

  testWidgets('AppSwitch 切换时轻触一下，禁用时不震', (tester) async {
    final calls = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (c) async {
      if (c.method == 'HapticFeedback.vibrate') calls.add(c.arguments as String);
      return null;
    });
    var v = false;
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: StatefulBuilder(builder: (_, set) => Column(children: [
            AppSwitch(key: const Key('on'), value: v, onChanged: (x) => set(() => v = x)),
            const AppSwitch(key: Key('off'), value: false, onChanged: null),
          ]))),
    ));
    await tester.tap(find.byKey(const Key('on')));
    await tester.pumpAndSettle();
    expect(v, isTrue);
    expect(calls, ['HapticFeedbackType.selectionClick']);
    await tester.tap(find.byKey(const Key('off')));
    await tester.pumpAndSettle();
    expect(calls, hasLength(1));
  });
}
