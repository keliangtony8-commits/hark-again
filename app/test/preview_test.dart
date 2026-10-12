// 端口预览（v1.30）：预览卡（打开 / 复制、过期态）、有效期文案、电脑页“正在监听的端口”（只听本机的标“打不开”、点了签链接）。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/preview_block.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/computer_details.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/models/preview.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

final _now = DateTime(2026, 10, 12, 14, 0);

Map<String, dynamic> _block({String? title = '记账小工具', DateTime? exp}) => {
      'type': 'preview',
      'workspace': 'me',
      'port': 8000,
      'url': 'https://me.example/api/preview/me.8000.1.x/',
      'title': title,
      'command': 'python3 -m http.server 8000 --bind 0.0.0.0',
      'expires_at': (exp ?? _now.add(const Duration(hours: 24))).toUtc().toIso8601String(),
    };

Map<String, dynamic> _status() => {
      'workspace': 'me',
      'sandbox': {'state': 'running'},
      'storage': {},
      'running_jobs': [],
      'ports': [
        {'port': 8000, 'loopback': false, 'pid': 9, 'command': 'python3 -m http.server 8000'},
        {'port': 5173, 'loopback': true, 'pid': 10, 'command': 'node vite'},
      ],
    };

class _Api implements Api {
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async => _status();

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path $body');
    return {'url': 'https://me.example/api/preview/x/', 'port': 8000};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Widget _wrap(Widget child, {Api? api}) => ProviderScope(
      overrides: [if (api != null) apiProvider.overrideWithValue(api)],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: SingleChildScrollView(child: child))),
    );

void main() {
  test('有效期与端口文案', () {
    expect(previewExpiry(_now.add(const Duration(hours: 24)), _now), '24 小时内有效');
    expect(previewExpiry(_now.add(const Duration(hours: 3, minutes: 20)), _now), '4 小时内有效');
    expect(previewExpiry(_now.add(const Duration(minutes: 40)), _now), '还能用 40 分钟');
    expect(previewExpiry(_now.subtract(const Duration(minutes: 1)), _now), '已过期');
    expect(previewExpiry(null, _now), '');
    expect(previewExpired(_now, _now), isTrue);
    expect(portTitle(8000), '端口 8000');
    expect(portTitle(8000, ' 看板 '), '看板');
    expect(portLine(const ListeningPort(port: 1, loopback: true)), contains('0.0.0.0'));
    expect(shortCommand('a' * 60).length, 48);
    final b = Block.fromJson(_block()) as PreviewBlock;
    expect(b.port, 8000);
    expect(copyText([b]), '记账小工具 https://me.example/api/preview/me.8000.1.x/');
    expect(copyText([Block.fromJson(_block(title: null))]), startsWith('端口 8000 '));
    final s = ComputerStatus.fromJson(_status());
    expect(s.ports.map((p) => p.port), [8000, 5173]);
    expect(s.ports.last.loopback, isTrue);
  });

  testWidgets('预览卡：标题、端口 + 程序、打开 / 复制链接', (tester) async {
    await tester.pumpWidget(_wrap(PreviewBlockView(Block.fromJson(_block()) as PreviewBlock, now: _now)));
    expect(find.text('记账小工具'), findsOneWidget);
    expect(find.textContaining('端口 8000 · python3 -m http.server'), findsOneWidget);
    expect(find.text('24 小时内有效'), findsOneWidget);
    expect(find.text('打开'), findsOneWidget);
    await tester.tap(find.text('复制链接'));
    await tester.pump();
    expect(find.text('链接已复制'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
  });

  testWidgets('过期的预览卡：没有按钮，提示重新生成', (tester) async {
    final b = Block.fromJson(_block(exp: _now.subtract(const Duration(hours: 1)))) as PreviewBlock;
    await tester.pumpWidget(_wrap(PreviewBlockView(b, now: _now)));
    expect(find.text('已过期'), findsOneWidget);
    expect(find.text('打开'), findsNothing);
    expect(find.textContaining('重新生成'), findsOneWidget);
  });

  testWidgets('BlockView 认得 preview', (tester) async {
    await tester.pumpWidget(_wrap(BlockView(Block.fromJson(_block()))));
    expect(find.byType(PreviewBlockView), findsOneWidget);
  });

  testWidgets('电脑页端口：只听本机的标打不开、不可点；长按复制签好的链接', (tester) async {
    tester.view.physicalSize = const Size(400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = _Api();
    await tester.pumpWidget(_wrap(const PortsSection(ws: 'me'), api: api));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('正在监听的端口'), findsOneWidget);
    expect(find.text('端口 8000'), findsOneWidget);
    expect(find.textContaining('打不开'), findsOneWidget);
    await tester.tap(find.text('端口 5173'));
    await tester.pump();
    expect(api.calls, isEmpty);
    await tester.longPress(find.text('端口 8000'));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.calls.single, contains('/api/projects/me/computer/preview'));
    expect(find.textContaining('预览链接已复制'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
  });
}
