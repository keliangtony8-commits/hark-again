// v3.5.1 新建面板 = 主页“发起”态的新面板模式（照 Hark，删了白底弹层）：整个 App 搭起来，在主页点左上 +
// → 整页磨砂、输入框聚焦、胶囊正上方居中一行“创建一个新面板”、占位词是面板示例（带图标）、不出“添加附件”；
// 点示例 / 自己写一句发出 = newPanelPrompt 包过、开新对话、切到聊天；收起 = 回到普通主页（模式清掉，再聚焦是普通建议）。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/features/home/home_screen.dart' show homePrompts;
import 'package:assistant/features/home/new_panel.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

class _ShellApi implements Api {
  @override
  Future<dynamic> get(String path) async => path == '/api/inbox' ? {'unread': 0, 'latest': null} : <dynamic>[];
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _frames(WidgetTester tester, [int n = 12]) async {
  for (var i = 0; i < n; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// 输入框上方的那行小字（主页栈底也有一颗同字的宽胶囊，用居中对齐区分）。
final _caption = find.byWidgetPredicate((w) => w is Text && w.data == newPanelCaption && w.textAlign == TextAlign.center);
Finder _chip(String label) => find.byWidgetPredicate((w) => w is GlassChip && w.label == label);
bool _scrim(WidgetTester tester) => tester.widget<FrostScrim>(find.byType(FrostScrim)).visible;
bool _focused(WidgetTester tester) => tester.widget<EditableText>(find.byType(EditableText)).focusNode.hasFocus;

Future<(ProviderContainer, FakeSocket)> _app(WidgetTester tester) async {
  tester.view.physicalSize = const Size(412, 892);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final socket = FakeSocket();
  final container = ProviderContainer(overrides: [
    sessionProvider.overrideWith(_SignedIn.new),
    apiProvider.overrideWithValue(_ShellApi()),
    chatSocketProvider.overrideWithValue(socket),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AssistantApp()));
  await _frames(tester);
  return (container, socket);
}

Future<void> _enter(WidgetTester tester) async {
  await tester.tap(find.byTooltip('新建面板'));
  await _frames(tester, 5);
}

void main() {
  testWidgets('点 + → 磨砂、聚焦、胶囊上方居中小字、占位词是面板示例（带图标）、不出添加附件', (tester) async {
    await _app(tester);
    expect(_caption, findsNothing);
    expect(_scrim(tester), isFalse);
    expect(find.byTooltip('添加附件'), findsOneWidget);

    await _enter(tester);
    expect(_scrim(tester), isTrue);
    expect(_focused(tester), isTrue, reason: '进模式即聚焦（键盘弹出）');
    expect(find.byTooltip('收起'), findsOneWidget);
    expect(_caption, findsOneWidget);
    final caption = tester.getRect(_caption), composer = tester.getRect(find.byType(Composer));
    expect(caption.bottom, lessThanOrEqualTo(composer.top), reason: '小字在输入胶囊正上方');
    expect(composer.top - caption.bottom, lessThan(40), reason: '紧贴胶囊（Hark 约 24），不飘在上面');
    expect((caption.center.dx - 412 / 2).abs(), lessThan(1), reason: '居中');

    // 占位词：面板示例第一句 + 它的图标；Hark 这里没有“+ 添加附件”
    expect(find.descendant(of: find.byType(Composer), matching: find.text(panelIdeas.first)), findsOneWidget);
    expect(find.descendant(of: find.byType(Composer), matching: find.byIcon(Icons.wb_sunny_outlined)), findsOneWidget);
    expect(find.text('给 Toyuis 发消息'), findsNothing);
    expect(find.byTooltip('添加附件'), findsNothing);

    // 原弹层的胶囊都在：示例 + 早间简报（还没排）；普通建议问题不出
    for (final idea in panelIdeas) {
      expect(_chip(idea), findsOneWidget);
    }
    expect(_chip(briefIdeaLabel), findsOneWidget);
    expect(_chip(homePrompts.first), findsNothing);
  });

  testWidgets('点示例 = newPanelPrompt 包过发进新对话、切到聊天', (tester) async {
    final (container, socket) = await _app(tester);
    await _enter(tester);
    await tester.tap(_chip(panelIdeas[1]));
    await _frames(tester);
    expect(container.read(routerProvider).state.uri.path, '/chat');
    expect(socket.sent.last['type'], 'user.message');
    expect(socket.sent.last['text'], newPanelPrompt(panelIdeas[1]));
  });

  testWidgets('自己写一句发出也包成新面板提示词', (tester) async {
    final (container, socket) = await _app(tester);
    await _enter(tester);
    await tester.enterText(find.byType(TextField), '北京的空气质量');
    await _frames(tester, 3);
    await tester.tap(find.bySemanticsLabel('发送'));
    await _frames(tester);
    expect(container.read(routerProvider).state.uri.path, '/chat');
    expect(socket.sent.last['text'], newPanelPrompt('北京的空气质量'));
  });

  testWidgets('收起 → 回到普通主页；再聚焦是普通建议、发出不再包', (tester) async {
    final (container, socket) = await _app(tester);
    await _enter(tester);
    expect(_caption, findsOneWidget);

    await tester.tap(find.byTooltip('收起'));
    await _frames(tester, 5);
    expect(_scrim(tester), isFalse);
    expect(_focused(tester), isFalse);
    expect(_caption, findsNothing);
    expect(find.text('给 Toyuis 发消息'), findsOneWidget);
    expect(find.byTooltip('添加附件'), findsOneWidget);

    await tester.tap(find.byType(TextField));
    await _frames(tester, 5);
    expect(_scrim(tester), isTrue);
    expect(_caption, findsNothing, reason: '模式已清掉');
    expect(_chip(homePrompts.first), findsOneWidget);
    expect(_chip(panelIdeas.first), findsNothing);

    await tester.tap(_chip(homePrompts.first));
    await _frames(tester);
    expect(container.read(routerProvider).state.uri.path, '/chat');
    expect(socket.sent.last['text'], homePrompts.first);
  });
}
