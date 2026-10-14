// 回复语言（v2.67）：models/preferences.dart 解析与文案 + ReplyLanguageTile（显示当前、菜单打勾、选了乐观更新 → PATCH、失败退回 + 提示）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/reply_language.dart';
import 'package:assistant/models/preferences.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _wire(String code) => {
      'reply_language': code,
      'reply_languages': [
        {'code': 'auto', 'label': '跟随我的语言'},
        {'code': 'zh-Hans', 'label': '简体中文'},
        {'code': 'zh-Hant', 'label': '繁體中文'},
        {'code': 'en', 'label': 'English'},
      ],
    };

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://me.example', token: 't');
}

class _Api implements Api {
  _Api(this.code, {this.fail = false});
  String code;
  bool fail;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return _wire(code);
  }

  @override
  Future<dynamic> patch(String path, Object b) async {
    calls.add('PATCH $path ${(b as Map)['reply_language']}');
    if (fail) throw ApiError('boom', 500);
    code = b['reply_language'] as String;
    return _wire(code);
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pump(WidgetTester tester, _Api api) async {
  tester.view.physicalSize = const Size(400, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: Column(children: [ReplyLanguageTile()]))),
  ));
  await _settle(tester);
}

void main() {
  test('解析与文案', () {
    final p = Preferences.fromJson(_wire('en'));
    expect(p.replyLanguage, 'en');
    expect(p.choices.map((c) => c.code), ['auto', 'zh-Hans', 'zh-Hant', 'en']);
    expect(p.replyLanguageLabel, 'English');
    expect(Preferences.fromJson(const {}).replyLanguageLabel, '跟随我的语言');
    expect(Preferences.fromJson({..._wire('xx')}).replyLanguageLabel, '跟随我的语言');
    expect(p.copyWith(replyLanguage: 'auto').replyLanguageLabel, '跟随我的语言');
    expect(Preferences.hintFor('auto'), contains('什么语言说'));
    expect(Preferences.hintFor('en'), contains('语音识别'));
  });

  testWidgets('显示当前、菜单打勾、选了就改', (tester) async {
    final api = _Api('auto');
    await _pump(tester, api);
    expect(find.text('回复语言'), findsOneWidget);
    expect(find.text('跟随我的语言'), findsOneWidget);
    await tester.tap(find.byKey(const Key('reply-language')));
    await _settle(tester);
    expect(find.text('English'), findsOneWidget);
    expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget); // 只有当前项打勾
    expect(find.byIcon(Icons.radio_button_unchecked_rounded), findsNWidgets(3));
    await tester.tap(find.text('English'));
    await _settle(tester);
    expect(api.calls, contains('PATCH /api/preferences en'));
    expect(find.text('English'), findsOneWidget); // 行的副标题
    expect(find.text('跟随我的语言'), findsNothing);
  });

  testWidgets('选同一项不发请求；失败退回并提示', (tester) async {
    final api = _Api('zh-Hans', fail: true);
    await _pump(tester, api);
    await tester.tap(find.byKey(const Key('reply-language')));
    await _settle(tester);
    await tester.tap(find.text('简体中文').last);
    await _settle(tester);
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty);
    await tester.tap(find.byKey(const Key('reply-language')));
    await _settle(tester);
    await tester.tap(find.text('English'));
    await _settle(tester);
    expect(api.calls, contains('PATCH /api/preferences en'));
    expect(find.text('没改成，稍后再试'), findsOneWidget);
    expect(find.text('简体中文'), findsOneWidget); // 退回原值
    await tester.pump(const Duration(seconds: 5));
  });

  testWidgets('老服务器没有接口：默认说明，点不开', (tester) async {
    final api = _OldApi();
    await _pump(tester, api);
    expect(find.text('跟随我的语言'), findsOneWidget);
    await tester.tap(find.byKey(const Key('reply-language')));
    await _settle(tester);
    expect(find.text('English'), findsNothing);
  });
}

class _OldApi extends _Api {
  _OldApi() : super('auto');
  @override
  Future<dynamic> get(String path) async => throw ApiError('Not Found', 404);
}
