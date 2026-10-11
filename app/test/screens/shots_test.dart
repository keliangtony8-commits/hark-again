// 截图回归（设计 v2 每个阶段交付前跑一遍，和 docs/design-refs 对着看）。默认跳过，不进 CI：
//   SHOTS=1 SHOTS_FONTS=/tmp/shots/fonts SHOTS_OUT=/tmp/shots/out flutter test test/screens/shots_test.dart
// 字体：测试环境没有中文字体，需要先下载 Noto Sans SC / Noto Serif SC / Noto Emoji（命令见 app/README.md「截图」），图标字体取 Flutter SDK 自带的。
// 时钟：用 TZ=Asia/Shanghai 跑，问候语和时间是白天的样子。
// 画面是真 App（AssistantApp + 真路由），只把网络换成假数据；尺寸 = 1080×2340 @2.625（常见安卓手机）。
import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/ui/sheets.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../chat_controller_test.dart' show FakeSocket;

final _on = Platform.environment['SHOTS'] == '1';
final _fonts = Platform.environment['SHOTS_FONTS'] ?? '/tmp/shots/fonts';
final _out = Platform.environment['SHOTS_OUT'] ?? '/tmp/shots/out';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');

  @override
  Future<void> signOut() async => state = const AsyncData(Session(server: 'https://my.server'));
}

Map<String, dynamic> _msg(String id, String role, String text, {bool yesterday = false}) => {
      'id': id,
      'role': role,
      'created_at': DateTime.now().subtract(Duration(days: yesterday ? 1 : 0)).toUtc().toIso8601String(),
      'blocks': [
        {'type': 'text', 'text': text}
      ],
    };

String _ago(Duration d) => DateTime.now().subtract(d).toUtc().toIso8601String();

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 1, 'latest': null};
    if (path == '/api/cards') {
      return [
        {
          'id': 'k1',
          'kind': 'action',
          'title': '本月模型花费已到预算的 80%',
          'blocks': [
            {'type': 'text', 'text': '本月已用 **¥8.10**，预算 ¥10.00。'}
          ],
          'target': 'usage',
          'unread': true,
        },
        {
          'id': 'k2',
          'kind': 'panel',
          'title': '今天的天气',
          'blocks': [
            {
              'type': 'stats',
              'items': [
                {'label': '多云', 'value': '22°C', 'note': '比昨天 ↑2°'},
                {'label': '日落', 'value': '17:48'},
              ]
            },
            {'type': 'text', 'text': '下午可能有小雨，出门带伞。'}
          ],
          'updated_at': DateTime.now().toUtc().toIso8601String(),
        },
      ];
    }
    if (path == '/api/projects') {
      return [
        {'id': 'p1', 'name': '考研复习', 'emoji': '📚', 'rules': '每天 8 点提醒我背单词', 'conversation_count': 12, 'last_active_at': _ago(const Duration(hours: 2))},
        {'id': 'p2', 'name': '找实习', 'emoji': '💼', 'rules': '', 'conversation_count': 3, 'last_active_at': _ago(const Duration(days: 1))},
        {'id': 'p3', 'name': '国庆旅行', 'emoji': '🏔️', 'rules': '预算 3000 以内', 'conversation_count': 0, 'last_active_at': _ago(const Duration(days: 9))},
      ];
    }
    if (path.startsWith('/api/usage')) {
      return {'currency': 'CNY', 'budget': 50, 'priced': ['fast'], 'today': {'cost': 0.4, 'tokens': 86000, 'calls': 23}, 'month': {'cost': 12.3, 'tokens': 2100000, 'calls': 412}};
    }
    if (path.startsWith('/api/conversations/')) {
      return {
        'id': 'c1',
        'title': '额度',
        'messages': [
          _msg('m1', 'user', '额度', yesterday: true),
          _msg('m2', 'assistant', '今天的日额度已经用了 65%，比一小时前的 33% 涨得挺快，今天下午 4:01 会重置。本月总额度用了 13%。', yesterday: true),
          _msg('m3', 'user', '那我省着点用'),
          _msg('m4', 'assistant', '好的。等你的助手 Android 版装上手机，你最想先拿它干哪件事？管课程作业、记账省钱，还是帮你写代码？'),
          // 聊天块坐在 AI 玻璃卡里：代码块 / 待确认 用 tileFill / cardFill（v0.54）
          {
            'id': 'm5',
            'role': 'assistant',
            'created_at': DateTime.now().toUtc().toIso8601String(),
            'blocks': [
              {'type': 'text', 'text': '先写个记账脚本，用 `sqlite` 存：'},
              {'type': 'code', 'language': 'python', 'source': 'db.execute("insert into spend values (?, ?)", (day, yuan))'},
              {'type': 'approval', 'id': 'a1', 'title': '在沙盒里运行脚本', 'detail': 'python spend.py --init', 'state': 'pending'},
            ],
          },
        ],
      };
    }
    if (path.startsWith('/api/conversations')) {
      return [
        {'id': 'c1', 'title': '额度'}
      ];
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _loadFonts() async {
  Future<void> load(String family, String path) async {
    final f = File(path);
    if (!f.existsSync()) throw StateError('缺字体 $path（见 app/README.md「截图」）');
    final loader = FontLoader(family)..addFont(Future.value(ByteData.sublistView(f.readAsBytesSync())));
    await loader.load();
  }

  await load('Roboto', '$_fonts/NotoSansSC.ttf'); // 安卓默认字族名，正文中英文都用它
  await load('serif', '$_fonts/NotoSerifSC.ttf'); // 衬线点缀（tokens Fonts.serif）
  await load('monospace', '$_fonts/NotoSansSC.ttf'); // 代码块的字族名：测试里没有真等宽字体，借正文字体免得是方块
  await load('Noto Color Emoji', '$_fonts/NotoEmoji.ttf'); // tokens Fonts.emoji 的第一个名字； // 表情的兜底（项目图标），不然是方块
  final sdk = Platform.environment['FLUTTER_ROOT'] ?? '/tmp/flutter';
  await load('MaterialIcons', '$sdk/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf');
}

Future<void> _shot(WidgetTester tester, String name) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(const ValueKey('shot')));
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: tester.view.devicePixelRatio);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    Directory(_out).createSync(recursive: true);
    File('$_out/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
  });
}

void main() {
  testWidgets('设计 v2 截图', skip: !_on, (tester) async {
    await tester.runAsync(_loadFonts);
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.625;
    tester.view.padding = const FakeViewPadding(top: 63, bottom: 42);
    tester.view.viewPadding = const FakeViewPadding(top: 63, bottom: 42);
    addTearDown(tester.view.reset);

    for (final mode in ['light', 'dark']) {
      SharedPreferences.setMockInitialValues({'appearance': mode});
      final container = ProviderContainer(overrides: [
        sessionProvider.overrideWith(_SignedIn.new),
        apiProvider.overrideWithValue(_Api()),
        chatSocketProvider.overrideWithValue(FakeSocket()),
        cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
      ]);
      await tester.pumpWidget(RepaintBoundary(
        key: const ValueKey('shot'),
        child: UncontrolledProviderScope(container: container, child: const AssistantApp()),
      ));
      await tester.pump();
      final router = container.read(routerProvider);
      await _shot(tester, '$mode-home');
      await tester.tap(find.byType(TextField)); // 底部输入胶囊聚焦：磨砂 + 收起钮 + 建议
      await _shot(tester, '$mode-home-focused');
      FocusManager.instance.primaryFocus?.unfocus();
      router.go('/chat');
      await tester.runAsync(() => container.read(chatProvider('').notifier).open('c1'));
      await _shot(tester, '$mode-chat');
      router.go('/projects');
      await _shot(tester, '$mode-projects');
      // 弹层（GlassSheet）：表单盖在项目页上，看玻璃透出的内容和 tile 底的输入框
      final nav = router.routerDelegate.navigatorKey.currentContext!;
      unawaited(showFormSheet(nav, title: '新建项目', subtitle: '项目有自己的规则、档案和文件', fields: const [
        FieldSpec('name', '名字', hint: '比如：毕业论文'),
        FieldSpec('rules', '规则', hint: '这个项目里我该怎么做', lines: 3, required: false),
      ]));
      await _shot(tester, '$mode-sheet-form');
      Navigator.of(nav).pop();
      await tester.pumpAndSettle();
      unawaited(showActionSheet<int>(nav, title: '毕业论文', actions: const [
        SheetAction(Icons.edit_outlined, '改名', value: 1),
        SheetAction(Icons.folder_outlined, '文件', value: 2),
        SheetAction(Icons.delete_outline, '删除', value: 3, danger: true),
      ]));
      await _shot(tester, '$mode-sheet-actions');
      Navigator.of(nav).pop();
      await tester.pumpAndSettle();
      // 对话框（GlassDialog + 磨砂遮罩）：危险确认盖在项目页上
      unawaited(confirmDanger(nav, title: '删除“毕业论文”？', text: '项目里的对话、档案和文件会一起删掉，找不回来。'));
      await _shot(tester, '$mode-dialog');
      Navigator.of(nav).pop();
      await tester.pumpAndSettle();
      router.push('/me');
      await _shot(tester, '$mode-me');
      router.push('/me/usage'); // 子页面（SubPage 玻璃标题栏）
      await _shot(tester, '$mode-usage');
      router.go('/projects/p1/brief');
      await _shot(tester, '$mode-brief');
      await container.read(sessionProvider.notifier).signOut(); // 登录页
      await _shot(tester, '$mode-login');
      await tester.pumpWidget(const SizedBox());
      container.dispose();
    }
  });
}
