// 朗读：App 里唯一的播放入口（和 media.dart 管“听”对称，这里管“说”）。
// - 服务器开了云端朗读（GET /api/voice/config → tts=server，阶跃 stepaudio）→ POST /api/voice/speak 拿 mp3 播放；
// - 否则、老服务器、或云端朗读这次失败 → 系统语音（flutter_tts，免费、离线）。
// 同一时间只读一段：点另一条先停当前的；再点同一条 = 停。离开聊天区（ChatView 卸载 / 换对话）也停。
// 插件只在 PluginSpeechEngine 里出现；界面只看 SpeechState（哪条消息、在准备还是在读），测试换假引擎。
import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:path_provider/path_provider.dart';

import '../models/block.dart';
import 'api.dart';
import 'session.dart';

enum SpeechPhase { idle, loading, playing }

@immutable
class SpeechState {
  const SpeechState([this.id, this.phase = SpeechPhase.idle]);
  final String? id; // 正在朗读的消息
  final SpeechPhase phase;
  static const idle = SpeechState();
  SpeechPhase phaseOf(String messageId) => id == messageId ? phase : SpeechPhase.idle;
}

/// 平台播放能力。两种都在播完、被停或出错时调用 onDone 一次（之后的回调由控制器按轮次忽略）。
abstract class SpeechEngine {
  Future<void> playMp3(Uint8List bytes, void Function() onDone);
  Future<void> speakText(String text, void Function() onDone);
  Future<void> stop();
  void dispose();
}

class PluginSpeechEngine implements SpeechEngine {
  AudioPlayer? _player;
  FlutterTts? _tts;
  StreamSubscription<void>? _sub;
  File? _file;

  @override
  Future<void> playMp3(Uint8List bytes, void Function() onDone) async {
    // 写临时文件再播：BytesSource 在 iOS 上不可用，文件源两端都稳
    final dir = await getTemporaryDirectory();
    final f = _file = File('${dir.path}/speak.mp3');
    await f.writeAsBytes(bytes, flush: true);
    final p = _player ??= AudioPlayer();
    await _sub?.cancel();
    _sub = p.onPlayerComplete.listen((_) => onDone());
    await p.play(DeviceFileSource(f.path));
  }

  @override
  Future<void> speakText(String text, void Function() onDone) async {
    final t = _tts ??= FlutterTts();
    await t.setLanguage(RegExp(r'[\u4e00-\u9fa5]').hasMatch(text) ? 'zh-CN' : 'en-US');
    t.setCompletionHandler(onDone);
    t.setCancelHandler(onDone);
    t.setErrorHandler((_) => onDone());
    await t.speak(text);
  }

  @override
  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    await _player?.stop();
    await _tts?.stop();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _player?.dispose();
    _tts?.stop();
    final f = _file;
    if (f != null) f.delete().ignore();
  }
}

final speechEngineProvider = Provider<SpeechEngine>((ref) {
  final e = PluginSpeechEngine();
  ref.onDispose(e.dispose);
  return e;
});

/// 回复里值得读出来的部分：只取正文块，去掉 Markdown 记号；链接读文字不读网址；代码、表格、卡片不读。
String speakableText(List<Block> blocks) => [
      for (final b in blocks)
        if (b is TextBlock) b.text,
    ]
        .join('\n')
        .replaceAllMapped(RegExp(r'!?\[([^\]]*)\]\([^)]*\)'), (m) => m[1]!)
        .replaceAll(RegExp(r'```[\s\S]*?```'), '')
        .replaceAll(RegExp(r'https?://\S+'), '')
        .replaceAll(RegExp(r'[#*`>|_~]'), '')
        .replaceAll(RegExp(r'\n{2,}'), '\n')
        .trim();

class SpeechController extends Notifier<SpeechState> {
  String? _modeServer; // 下面的 _mode 是哪台服务器的（换服务器重新问）
  String? _mode; // server | device
  int _round = 0; // 每次开始/停止 +1；旧轮次的回调一律忽略

  SpeechEngine get _engine => ref.read(speechEngineProvider);

  @override
  SpeechState build() => SpeechState.idle;

  Future<String> _voiceMode() async {
    final server = ref.read(sessionProvider).value?.server ?? '';
    if (_mode != null && _modeServer == server) return _mode!;
    try {
      final j = await ref.read(apiProvider).get('/api/voice/config');
      _mode = j is Map && j['tts'] == 'server' ? 'server' : 'device';
      _modeServer = server;
      return _mode!;
    } on ApiError catch (e) {
      if (e.isNetwork) return 'device'; // 连不上不记住，下次再问
      _mode = 'device'; // 老服务器没有这个接口
      _modeServer = server;
      return _mode!;
    }
  }

  /// 点“朗读”：同一条在读 → 停；否则停掉别的、读这条。返回给用户看的错误（没有 = null）。
  Future<String?> toggle(String messageId, String text) async {
    if (state.id == messageId) {
      await stop();
      return null;
    }
    final spoken = text.trim();
    if (spoken.isEmpty) return '这条回复没有可朗读的文字';
    if (state.id != null) await _engine.stop(); // 先停正在读的那条
    final round = ++_round;
    state = SpeechState(messageId, SpeechPhase.loading);
    void done() {
      if (round == _round) state = SpeechState.idle;
    }

    try {
      if (await _voiceMode() == 'server') {
        try {
          final mp3 = await ref.read(apiProvider).postBytes('/api/voice/speak', {'text': spoken});
          if (round != _round) return null;
          state = SpeechState(messageId, SpeechPhase.playing);
          await _engine.playMp3(mp3, done);
          return null;
        } on ApiError catch (e) {
          if (e.status == 401) rethrow;
          // 云端朗读这次不行（额度、网络、服务器关了）→ 退回系统语音，不打断用户
        }
      }
      if (round != _round) return null;
      state = SpeechState(messageId, SpeechPhase.playing);
      await _engine.speakText(spoken, done);
      return null;
    } catch (e) {
      done();
      return e is ApiError ? e.message : '朗读失败';
    }
  }

  Future<void> stop() async {
    _round++;
    if (state.id == null) return; // 没在读：不碰引擎（卸载时也不必建插件）
    state = SpeechState.idle;
    await _engine.stop();
  }
}

final speechProvider = NotifierProvider<SpeechController, SpeechState>(SpeechController.new);
