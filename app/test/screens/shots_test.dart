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
  Future<Session> build() async => const Session(server: 'https://ai.example.com', token: 't');

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

Map<String, dynamic> _cards(String id, List<Map<String, dynamic>> blocks) =>
    {'id': id, 'role': 'assistant', 'created_at': DateTime.now().toUtc().toIso8601String(), 'blocks': blocks};

// 聊天卡片家族（v0.84）：商品宫格 + 待确认订单
final _shopChat = {
  'id': 'c2',
  'title': '耳机',
  'messages': [
    _msg('s1', 'user', '帮我挑个 300 块以内的蓝牙耳机，通勤用'),
    _cards('s2', [
      {'type': 'text', 'text': '三款都在 ¥300 以内，都有主动降噪。'},
      {
        'type': 'products',
        'title': '通勤降噪耳机',
        'pick': '选 QCY HT08：降噪最好，续航 40 小时。',
        'items': [
          {'name': 'QCY HT08', 'price': '¥239', 'meta': '降噪 -43dB · 40h'},
          {'name': '漫步者 Lolli Pro 3', 'price': '¥299', 'meta': 'LDAC · 32h'},
          {'name': '小米 Redmi Buds 6', 'price': '¥199', 'meta': '降噪 -49dB · 42h'},
        ],
      },
    ]),
    _msg('s3', 'user', '就 QCY 吧，下单'),
    _cards('s4', [
      {
        'type': 'order',
        'id': 'o1',
        'merchant': 'QCY 京东自营旗舰店',
        'items': [
          {'name': 'QCY HT08 主动降噪耳机', 'price': '¥239.00', 'qty': 1, 'note': '黑色'}
        ],
        'breakdown': [
          {'label': '运费', 'amount': '¥0.00'},
          {'label': '店铺券', 'amount': '-¥10.00'}
        ],
        'total': '¥229.00',
        'payment': '招商银行 储蓄卡 8841',
        'destination': '学校南门菜鸟驿站',
        'action': '确认下单',
        'state': 'pending',
      },
    ]),
  ],
};

// 任务中途的登录卡 + 记忆卡
final _signInChat = {
  'id': 'c3',
  'title': '图书馆座位',
  'messages': [
    _msg('g1', 'user', '帮我约明天上午图书馆四楼的座位，我一般坐靠窗那排'),
    _cards('g2', [
      {
        'type': 'memory',
        'action': 'saved',
        'items': [
          {'id': 'mem12345', 'content': '图书馆习惯坐四楼靠窗', 'category': 'preference'}
        ],
      },
      {'type': 'text', 'text': '图书馆预约系统要登录，保险箱里还没有它的账号。'},
      {
        'type': 'form',
        'id': 'f1',
        'purpose': 'login',
        'title': '登录图书馆预约系统',
        'site': 'seat.lib.example.edu',
        'fields': [
          {'name': 'username', 'label': '学号', 'kind': 'text'},
          {'name': 'password', 'label': '密码', 'kind': 'password'}
        ],
        'remember': true,
        'action': '登录',
        'state': 'pending',
      },
    ]),
  ],
};

// 助手缺信息时的信息表单（ask_user）：一张已回答 + 一张待填（候选、选填、多行）
final _askChat = {
  'id': 'c4',
  'title': '寄快递',
  'messages': [
    _msg('h1', 'user', '帮我把这箱书寄回家，下周三前到就行'),
    _cards('h2', [
      {'type': 'text', 'text': '寄件还差几样信息，填好我就去下单。'},
      {
        'type': 'form',
        'id': 'f2',
        'purpose': 'info',
        'title': '寄件信息',
        'note': '填一次，我记进记忆，下次不用再问。',
        'fields': [
          {'name': 'q1', 'label': '收件人', 'kind': 'text', 'value': '柯妈妈'},
          {'name': 'q2', 'label': '电话', 'kind': 'phone'},
          {'name': 'q3', 'label': '收件地址', 'kind': 'multiline'},
          {'name': 'q4', 'label': '快递', 'kind': 'text', 'options': ['顺丰', '京东', '中通']},
          {'name': 'q5', 'label': '备注', 'kind': 'text', 'optional': true},
        ],
        'remember': true,
        'action': '告诉助手',
        'state': 'pending',
      },
    ]),
  ],
};

/// 用量报表：本月 1 号到今天每天都有数（周末少），三个最花钱的对话（一个已删），两个模型，上月同期。
Map<String, dynamic> _usage() {
  final now = DateTime.now();
  const pattern = [0.9, 1.4, 0.6, 1.8, 1.1, 0.3, 0.2, 1.6, 1.2, 2.1, 0.8, 1.3, 0.5, 0.4];
  final daily = [
    for (var d = 1; d <= now.day; d++)
      {
        'date': '${now.year}-${now.month.toString().padLeft(2, '0')}-${d.toString().padLeft(2, '0')}',
        'cost': pattern[(d - 1) % pattern.length],
        'tokens': (pattern[(d - 1) % pattern.length] * 170000).round(),
        'calls': (pattern[(d - 1) % pattern.length] * 33).round(),
      },
  ];
  return {
    'currency': 'CNY',
    'budget': 50,
    'priced': ['fast', 'smart'],
    'today': {'cost': 0.4, 'tokens': 86000, 'calls': 23},
    'month': {
      'cost': 12.3,
      'tokens': 2100000,
      'calls': 412,
      'models': [
        {'model': 'smart', 'calls': 96, 'prompt_tokens': 610000, 'completion_tokens': 140000, 'cost': 8.6},
        {'model': 'fast', 'calls': 316, 'prompt_tokens': 1120000, 'completion_tokens': 230000, 'cost': 3.7},
      ],
    },
    'daily': daily,
    'conversations': [
      {'id': 'c1', 'title': '考研英语作文批改', 'calls': 58, 'tokens': 420000, 'cost': 3.1},
      {'id': 'c2', 'title': '买一副降噪耳机', 'calls': 31, 'tokens': 260000, 'cost': 1.9},
      {'id': 'c9', 'title': null, 'calls': 12, 'tokens': 90000, 'cost': 0.6},
    ],
    'last_month': {'cost': 21.4, 'tokens': 3600000, 'calls': 700, 'to_date': {'cost': 10.2, 'tokens': 1800000, 'calls': 330}},
  };
}

/// 今天“现在 + d”那一刻的每日 cron（跨日就贴在当天边上），让“今天”日程的状态不随跑截图的时刻变。
String _cronAt(Duration d) {
  final now = DateTime.now();
  var t = now.add(d);
  if (t.day != now.day) t = d.isNegative ? DateTime(now.year, now.month, now.day) : DateTime(now.year, now.month, now.day, 23, 59);
  return '${t.minute} ${t.hour} * * *';
}

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
          'id': 'k3',
          'kind': 'action',
          'origin': 'agent',
          'action_label': '帮我订座',
          'action_prompt': '帮我约明早 8 点图书馆四楼靠窗的座位',
          'image_url': _offerImage,
          'link_url': 'https://www.seat.lib.example.edu/floor/4',
          'title': '明早图书馆四楼靠窗还有空位',
          'blocks': [
            {'type': 'text', 'text': '8:00 开放预约，靠窗那排还剩 6 个。'}
          ],
          'unread': true,
        },
        {
          'id': 'k4',
          'kind': 'action',
          'origin': 'agent',
          'action_label': '整理笔记',
          'action_prompt': '把这周的高数笔记整理成一页提纲',
          'conversation_id': 'c1',
          'title': '这周的高数笔记可以整理成提纲',
          'blocks': [
            {'type': 'text', 'text': '周五小测前过一遍，大约 10 分钟。'}
          ],
          'unread': false,
        },
        {
          'id': 'k5',
          'kind': 'action',
          'origin': 'agent',
          'target': 'connectors',
          'title': 'GitHub 连接失效了',
          'blocks': [
            {'type': 'text', 'text': '令牌昨晚过期，代码仓库的定时同步停了。重新连一下就好。'}
          ],
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
    if (path == '/api/auth/me') return {'username': 'keliang'};
    if (path == '/api/connectors') {
      return [
        {'id': 'github', 'name': 'GitHub', 'desc': '仓库、议题、代码', 'configured': true, 'account': 'keliang'},
        {'id': 'google', 'name': 'Google', 'desc': '邮件、日历、云盘', 'configured': true},
        {'id': 'notion', 'name': 'Notion', 'desc': '笔记和数据库', 'configured': false},
      ];
    }
    if (path == '/api/connectors/mcp') {
      return [
        {'id': 'mc1', 'name': '课表', 'url': 'https://timetable.example.com/mcp', 'has_token': true},
        {'id': 'mc2', 'name': '家里 NAS', 'url': 'http://nas.local:8080/mcp', 'has_token': false, 'problem': 'down'},
        {'id': 'mc3', 'name': 'Linear', 'url': 'https://mcp.linear.app/sse', 'has_token': true, 'problem': 'auth'},
      ];
    }
    if (path == '/api/tasks') {
      // v1.00 任务页：正常 / 连续失败被自动暂停（进“需要留意”组）/ 手动停。
      // v1.02 主页“今天”：时刻相对现在排（截图随时跑都有 已完成 → 失败 → 下一个 → 已暂停 → 稍后）。
      return [
        {'id': 't1', 'name': '早间简报', 'prompt': '', 'cron': _cronAt(const Duration(hours: -3)), 'active': true, 'output': 'report',
         'last_run_at': _ago(const Duration(hours: 2, minutes: 59)), 'last_status': 'ok'},
        {'id': 't4', 'name': '背单词提醒', 'prompt': '', 'cron': _cronAt(const Duration(hours: -1)), 'active': true, 'output': 'report',
         'last_run_at': _ago(const Duration(minutes: 59)), 'last_status': 'error', 'fail_streak': 1},
        {'id': 't5', 'name': '图书馆抢座', 'prompt': '', 'cron': _cronAt(const Duration(hours: 1)), 'active': true, 'output': 'report'},
        {'id': 't2', 'name': '周报整理', 'prompt': '', 'cron': _cronAt(const Duration(hours: 2)), 'active': false, 'output': 'report',
         'last_run_at': _ago(const Duration(days: 1)), 'last_status': 'error', 'fail_streak': 3, 'paused_reason': 'failures'},
        {'id': 't6', 'name': '考研倒计时面板', 'prompt': '', 'cron': '0 * * * *', 'active': true, 'output': 'panel',
         'last_run_at': _ago(const Duration(minutes: 20)), 'last_status': 'ok'},
        {'id': 't7', 'name': '查明天天气', 'prompt': '', 'cron': _cronAt(const Duration(hours: 5)), 'active': true, 'output': 'report'},
        {'id': 't3', 'name': '晚间复盘', 'prompt': '', 'cron': '0 21 * * *', 'active': false, 'output': 'report'},
      ];
    }
    if (path.startsWith('/api/usage')) return _usage();
    if (path == '/api/memories') {
      return [
        {'id': 'mem12345', 'content': '图书馆习惯坐四楼靠窗', 'category': 'preference', 'updated_at': _ago(Duration.zero)}
      ];
    }
    if (path == '/api/conversations/c2') return _shopChat;
    if (path == '/api/conversations/c3') return _signInChat;
    if (path == '/api/conversations/c4') return _askChat;
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
        {'id': 'c1', 'title': '额度'},
        {'id': 'c2', 'title': '耳机'},
        {'id': 'c3', 'title': '图书馆座位'},
        {'id': 'c4', 'title': '寄快递'},
      ];
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

/// 建议卡配图：测试里网络图片拿不到（400 → 坏图占位），先把一张画出来的图塞进图片缓存，
/// 键和 Image.network 用的 NetworkImage(url) 相同，NetImage 就直接拿到它。
const _offerImage = 'https://img.example.com/library-window.jpg';

Future<void> _seedImage(String url) async {
  const w = 800, h = 400;
  final rec = ui.PictureRecorder();
  final c = Canvas(rec);
  final rect = Rect.fromLTWH(0, 0, w.toDouble(), h.toDouble());
  c.drawRect(rect, Paint()..shader = ui.Gradient.linear(Offset.zero, const Offset(0, 400), const [Color(0xFFF3E3C8), Color(0xFFC9A27A)]));
  final frame = Paint()..color = const Color(0xFF6B4E37);
  for (var i = 0; i < 3; i++) {
    final x = 70.0 + i * 230;
    c.drawRect(Rect.fromLTWH(x, 50, 200, 230), frame);
    c.drawRect(Rect.fromLTWH(x + 10, 60, 180, 210), Paint()..shader = ui.Gradient.linear(Offset(x, 60), Offset(x, 270), const [Color(0xFFDDEBF2), Color(0xFFA9C7D8)]));
    c.drawRect(Rect.fromLTWH(x + 97, 60, 6, 210), frame);
  }
  c.drawRect(const Rect.fromLTWH(0, 300, 800, 26), Paint()..color = const Color(0xFF8A6446));
  final image = await rec.endRecording().toImage(w, h);
  PaintingBinding.instance.imageCache.putIfAbsent(
    NetworkImage(url),
    () => OneFrameImageStreamCompleter(Future.value(ImageInfo(image: image))),
  );
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
    await tester.runAsync(() => _seedImage(_offerImage));
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
      await tester.dragFrom(const Offset(200, 600), const Offset(0, -1000)); // 往下翻：后几张建议卡（含“需要你亲自处理”）
      await _shot(tester, '$mode-home-end');
      await tester.dragFrom(const Offset(200, 600), const Offset(0, -3000)); // 翻到底：“今天”日程（v1.02）
      await _shot(tester, '$mode-home-today');
      await tester.dragFrom(const Offset(200, 300), const Offset(0, 3000));
      await tester.pump(const Duration(seconds: 1));
      await tester.tap(find.byType(TextField)); // 底部输入胶囊聚焦：磨砂 + 收起钮 + 建议
      await _shot(tester, '$mode-home-focused');
      FocusManager.instance.primaryFocus?.unfocus();
      router.go('/chat');
      await tester.runAsync(() => container.read(chatProvider('').notifier).open('c1'));
      await _shot(tester, '$mode-chat');
      await tester.runAsync(() => container.read(chatProvider('').notifier).open('c2'));
      await _shot(tester, '$mode-chat-shop');
      await tester.dragFrom(const Offset(200, 400), const Offset(0, 600)); // 往回翻：商品宫格
      await _shot(tester, '$mode-chat-shop-top');
      await tester.runAsync(() => container.read(chatProvider('').notifier).open('c3'));
      await _shot(tester, '$mode-chat-form');
      await tester.runAsync(() => container.read(chatProvider('').notifier).open('c4'));
      await _shot(tester, '$mode-chat-ask');
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
      router.push('/me/connectors'); // 连接器：MCP 行上的问题（v0.97）
      await _shot(tester, '$mode-connectors');
      router.pop();
      router.push('/me/tasks'); // 定时任务：自动暂停的进“需要留意”（v1.00）
      await _shot(tester, '$mode-tasks');
      router.pop();
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
