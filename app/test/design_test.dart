// 设计 v2.1「克制」的守卫：字重不超过 600、墨色/正文对比度达标、页面不写死橙色气泡/按钮。
import 'dart:io';

import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

double _contrast(Color a, Color b) {
  final la = a.computeLuminance(), lb = b.computeLuminance();
  final hi = la > lb ? la : lb, lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}

Iterable<File> _dart(String dir) =>
    Directory(dir).listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'));

void main() {
  for (final (name, p) in [('浅色', Palette.light), ('深色', Palette.dark)]) {
    test('$name：墨色/正文/强调色对比度', () {
      expect(_contrast(p.ink, p.onInk), greaterThanOrEqualTo(4.5), reason: 'ink/onInk');
      expect(_contrast(p.text, p.bg), greaterThanOrEqualTo(4.5), reason: 'text/bg');
      expect(_contrast(p.text2, p.bg), greaterThanOrEqualTo(4.5), reason: 'text2/bg');
      expect(_contrast(p.text3, p.bg), greaterThanOrEqualTo(3), reason: 'text3/bg');
      expect(_contrast(p.accent, p.onAccent), greaterThanOrEqualTo(4.5), reason: 'accent/onAccent');
      expect(_contrast(p.text, p.avatar), greaterThanOrEqualTo(4.5), reason: '默认头像首字');
    });
  }

  test('字重降一档：页面里不出现 w700 及以上（只有 theme 定义字重）', () {
    final bad = <String>[];
    for (final f in _dart('lib')) {
      if (f.path.contains('lib/theme/')) continue;
      if (RegExp(r'FontWeight\.w[789]00|FontWeight\.bold').hasMatch(f.readAsStringSync())) bad.add(f.path);
    }
    expect(bad, isEmpty);
  });

  test('页面级动作在标题栏：不用 Material 悬浮钮（它不吃设计令牌）', () {
    final bad = [for (final f in _dart('lib')) if (f.readAsStringSync().contains('FloatingActionButton(')) f.path];
    expect(bad, isEmpty);
  });

  // 强调色（橙）只留给四种“信号”：未读点、进度/运行中、链接/搜索命中、页面里唯一的关键状态。
  // 其余一律墨色或 text2。新增用法必须在这里登记角色，不能随手 p.accent——这就是“每屏 ≤2 处”的落地方式。
  test('强调色克制：accent 只出现在登记过的信号位', () {
    const allowed = <String, int>{
      'lib/ui/markdown.dart': 2, // 链接
      'lib/ui/kit.dart': 1, // 搜索命中高亮
      'lib/ui/motion.dart': 1, // 跳转定位的闪烁底（accentSoft）
      'lib/ui/glass.dart': 2, // 壁纸右下 5% 光晕
      'lib/shell/top_bar.dart': 1, // 导航未读点
      'lib/features/home/report_actions.dart': 1, // 收件箱未读点（InboxRow）
      'lib/features/auth/login_screen.dart': 2, // 品牌标
      'lib/blocks/block_frame.dart': 1, // 卡片外框 live 语气 = 浏览器接管中（唯一关键状态）
      'lib/features/chat/attachment_tray.dart': 1, // 上传进度
      'lib/features/chat/message_view.dart': 1, // 生成中进度
      'lib/features/me/task_detail.dart': 1, // 运行中脉冲
      'lib/blocks/job_block.dart': 1, // 后台任务运行中脉冲
      'lib/features/projects/project_files_sheet.dart': 1, // 处理中脉冲
      'lib/features/me/usage_screen.dart': 1, // 预算进度条（未超）
    };
    final re = RegExp(r'\.accent(Soft)?\b');
    final bad = <String>[];
    for (final f in _dart('lib')) {
      final path = f.path.replaceAll(r'\', '/');
      if (path.contains('lib/theme/')) continue;
      final n = re.allMatches(f.readAsStringSync()).length;
      final key = allowed.keys.firstWhere((k) => path.endsWith(k), orElse: () => '');
      if (n > (allowed[key] ?? 0)) bad.add('$path: $n');
    }
    expect(bad, isEmpty, reason: '强调色新用法要先在 allowed 里登记角色');
  });
}
