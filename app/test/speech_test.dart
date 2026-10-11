// 朗读：服务器 TTS / 系统语音的选择、同时只读一段、失败回退、按钮三态。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/core/speech.dart';
import 'package:assistant/models/block.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

class _Api implements Api {
  _Api({this.tts = 'server', this.speakFails = false});
  final String tts;
  final bool speakFails;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return {'stt': true, 'tts': tts};
  }

  @override
  Future<Uint8List> postBytes(String path, Object body) async {
    calls.add('POST $path ${(body as Map)['text']}');
    if (speakFails) throw ApiError('朗读失败（502）', 503);
    return Uint8List.fromList([1, 2, 3]);
  }

  @override
  dynamic noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

class _Engine implements SpeechEngine {
  final log = <String>[];
  void Function()? done;

  @override
  Future<void> playMp3(Uint8List bytes, void Function() onDone) async {
    log.add('mp3 ${bytes.length}');
    done = onDone;
  }

  @override
  Future<void> speakText(String text, void Function() onDone) async {
    log.add('tts $text');
    done = onDone;
  }

  @override
  Future<void> stop() async => log.add('stop');

  @override
  void dispose() {}
}

ProviderContainer _container(_Api api, _Engine engine) {
  final c = ProviderContainer(overrides: [
    sessionProvider.overrideWith(_SignedIn.new),
    apiProvider.overrideWithValue(api),
    speechEngineProvider.overrideWithValue(engine),
  ]);
  addTearDown(c.dispose);
  c.listen(speechProvider, (_, _) {});
  return c;
}

void main() {
  test('服务器开了朗读：要 mp3 播放，播完回到空闲；配置只问一次', () async {
    final api = _Api(), engine = _Engine();
    final c = _container(api, engine);
    await c.read(sessionProvider.future);
    final ctl = c.read(speechProvider.notifier);

    expect(await ctl.toggle('m1', '你好'), isNull);
    expect(c.read(speechProvider).phaseOf('m1'), SpeechPhase.playing);
    expect(engine.log, ['mp3 3']);
    engine.done!();
    expect(c.read(speechProvider).id, isNull);

    await ctl.toggle('m2', '再见');
    expect(api.calls.where((x) => x.startsWith('GET')).length, 1);
  });

  test('再点同一条 = 停；点另一条先停当前的；旧轮次的回调不改状态', () async {
    final api = _Api(), engine = _Engine();
    final c = _container(api, engine);
    await c.read(sessionProvider.future);
    final ctl = c.read(speechProvider.notifier);

    await ctl.toggle('m1', '一');
    final oldDone = engine.done!;
    await ctl.toggle('m2', '二');
    expect(engine.log.contains('stop'), isTrue);
    oldDone(); // m1 被停时引擎回调：不能把正在读的 m2 清掉
    expect(c.read(speechProvider).phaseOf('m2'), SpeechPhase.playing);

    await ctl.toggle('m2', '二');
    expect(c.read(speechProvider).id, isNull);
  });

  test('服务器没开或云端朗读失败 → 系统语音', () async {
    final engine = _Engine();
    final c = _container(_Api(tts: 'device'), engine);
    await c.read(sessionProvider.future);
    await c.read(speechProvider.notifier).toggle('m1', '你好');
    expect(engine.log, ['tts 你好']);

    final engine2 = _Engine();
    final c2 = _container(_Api(speakFails: true), engine2);
    await c2.read(sessionProvider.future);
    expect(await c2.read(speechProvider.notifier).toggle('m1', '你好'), isNull);
    expect(engine2.log, ['tts 你好']);
  });

  test('空文字不读；没在读时 stop 不碰引擎', () async {
    final engine = _Engine();
    final c = _container(_Api(), engine);
    expect(await c.read(speechProvider.notifier).toggle('m1', '  '), isNotNull);
    await c.read(speechProvider.notifier).stop();
    expect(engine.log, isEmpty);
  });

  test('speakableText 只读正文：去 Markdown、链接读文字、不读网址和代码', () {
    final blocks = [
      Block.fromJson({'type': 'text', 'text': '## 标题\n**粗体** 看 [官网](https://a.com) 或 https://b.com\n```py\nx=1\n```'}),
      Block.fromJson({'type': 'code', 'language': 'py', 'source': 'print(1)'}),
    ];
    final s = speakableText(blocks);
    expect(s, contains('标题'));
    expect(s, contains('官网'));
    expect(s, isNot(contains('http')));
    expect(s, isNot(contains('x=1')));
    expect(s, isNot(contains('*')));
    expect(s, isNot(contains('print')));
  });
}
