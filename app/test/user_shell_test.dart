// 用户自己跑的命令（v1.77，输入框 !命令）：纯规则（认不认命令、状态词、用时、尾巴）+ 卡片 + 输入框提示。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/job.dart';
import 'package:assistant/models/shell.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _frame(Widget child) => ProviderScope(
      child: MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: SingleChildScrollView(child: child))),
    );

ShellBlock _b(Map<String, dynamic> j) => Block.fromJson({'type': 'shell', 'command': 'npm test', ...j}) as ShellBlock;

void main() {
  test('认命令：! / ！ 开头、后面有东西', () {
    expect(shellCommandOf('!ls -la'), 'ls -la');
    expect(shellCommandOf('  ！ pwd '), 'pwd');
    expect(shellCommandOf('!'), isNull);
    expect(shellCommandOf('！   '), isNull);
    expect(shellCommandOf('看看 !ls'), isNull);
    expect(shellCommandOf(''), isNull);
  });

  test('块解析 + 状态词 + 语气 + 用时', () {
    final b = _b({'state': 'failed', 'output': 'x', 'exit_code': 3, 'seconds': 1.234, 'note': '注意'});
    expect([b.state, b.exitCode, b.seconds, b.note, b.running], ['failed', 3, 1.234, '注意', false]);
    expect(shellStateLabel(b), '失败 · 退出码 3');
    expect(shellStateLabel(_b({'state': 'refused'})), '已拦下，没有执行');
    expect(shellStateLabel(_b({})), '运行中');
    expect(_b({}).running, isTrue);
    expect([for (final s in ['running', 'done', 'failed', 'timeout', 'stopped', 'refused', 'error']) shellTone(s)],
        [JobTone.running, JobTone.ok, JobTone.problem, JobTone.problem, JobTone.quiet, JobTone.problem, JobTone.problem]);
    expect(shellDuration(null), '');
    expect(shellDuration(0.44), '0.4 秒');
    expect(shellDuration(75), '1 分 15 秒');
    expect(shellHasMore('1\n2\n3\n', 3), isFalse);
    expect(shellHasMore('1\n2\n3\n4', 3), isTrue);
    expect(shellSemantics(b), '你运行的命令 npm test，失败 · 退出码 3，用时 1.2 秒：注意');
    expect(standsAlone(b), isTrue);
    expect(copyText([b]), '```bash\n\$ npm test\nx\n```');
  });

  testWidgets('运行中：等待输出、没有复制；结束：输出尾巴、说明、完整输出', (tester) async {
    await tester.pumpWidget(_frame(BlockView(_b({}))));
    await tester.pump();
    expect(find.text('\$ npm test'), findsOneWidget);
    expect(find.text('等待输出…'), findsOneWidget);
    expect(find.text('运行中'), findsOneWidget);
    expect(find.byTooltip('复制命令和输出'), findsNothing);

    final out = [for (var i = 1; i <= 9; i++) 'line $i'].join('\n');
    await tester.pumpWidget(_frame(BlockView(_b({'state': 'timeout', 'output': out, 'exit_code': 124, 'seconds': 120.0, 'note': '前台最多 120 秒'}))));
    await tester.pumpAndSettle();
    expect(find.text('超时被终止'), findsOneWidget);
    expect(find.text('前台最多 120 秒'), findsOneWidget);
    expect(find.text('2 分 00 秒'), findsOneWidget);
    expect(find.textContaining('line 9'), findsOneWidget);
    expect(find.textContaining('line 1\n'), findsNothing); // 卡片上只看尾巴
    expect(find.byTooltip('复制命令和输出'), findsOneWidget);
    await tester.tap(find.text('完整输出'));
    await tester.pumpAndSettle();
    expect(find.textContaining('line 1\nline 2'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('短输出没有“完整输出”；被拦下显示“没有执行”', (tester) async {
    await tester.pumpWidget(_frame(BlockView(_b({'state': 'done', 'output': 'ok', 'exit_code': 0, 'seconds': 0.2}))));
    await tester.pumpAndSettle();
    expect(find.text('完整输出'), findsNothing);
    expect(find.text('已完成'), findsOneWidget);
    await tester.pumpWidget(_frame(BlockView(_b({'state': 'refused', 'note': '被安全规则拦下了'}))));
    await tester.pumpAndSettle();
    expect(find.text('（没有执行）'), findsOneWidget);
    expect(find.text('被安全规则拦下了'), findsOneWidget);
  });

  testWidgets('输入框：!命令 出提示条，发送钮换成“在电脑上运行”', (tester) async {
    final sent = <String>[];
    await tester.pumpWidget(_frame(Composer(onSend: (t, _) => sent.add(t), busy: false)));
    await tester.enterText(find.byType(TextField), '!ls -la');
    await tester.pumpAndSettle();
    expect(find.textContaining('直接在电脑上运行'), findsOneWidget);
    expect(find.bySemanticsLabel('在电脑上运行'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('在电脑上运行'));
    await tester.pumpAndSettle();
    expect(sent, ['!ls -la']);
    expect(find.textContaining('直接在电脑上运行'), findsNothing);
    await tester.enterText(find.byType(TextField), '你好');
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel('发送'), findsOneWidget);
    expect(find.textContaining('直接在电脑上运行'), findsNothing);
  });
}
