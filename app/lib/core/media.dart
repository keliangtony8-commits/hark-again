// 设备媒体能力（选文件、拍照、录音）+ 上传/转写。插件只在这里出现，
// 界面拿到的永远是服务器回来的 FileBlock 或文字，不直接碰平台 API。
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../models/block.dart';
import 'api.dart';

enum PickSource { gallery, camera, file }

class Media {
  Media(this._api);
  final Api _api;
  final _recorder = AudioRecorder();
  final _images = ImagePicker();

  /// 选取本地文件，返回路径（用户取消 = 空列表）。
  Future<List<File>> pick(PickSource source) async {
    switch (source) {
      case PickSource.camera:
        final x = await _images.pickImage(source: ImageSource.camera, imageQuality: 85, maxWidth: 2400);
        return x == null ? [] : [File(x.path)];
      case PickSource.gallery:
        final xs = await _images.pickMultiImage(imageQuality: 85, maxWidth: 2400);
        return [for (final x in xs) File(x.path)];
      case PickSource.file:
        final fs = await FilePicker.pickFiles();
        return [for (final f in fs) if (f.path != null) File(f.path!)];
    }
  }

  /// v2.92 §P 选一张头像：缩到 512px、JPEG 质量 85（几十 KB，服务器上限 2 MB）。取消 = null。
  Future<File?> pickAvatar(PickSource source) async {
    final x = await _images.pickImage(
        source: source == PickSource.camera ? ImageSource.camera : ImageSource.gallery, imageQuality: 85, maxWidth: 512, maxHeight: 512);
    return x == null ? null : File(x.path);
  }

  Future<FileBlock> upload(File f) async {
    final j = await _api.upload('/api/uploads', f) as Map<String, dynamic>;
    return Block.fromJson({'type': 'file', 'source': 'upload', ...j}) as FileBlock;
  }

  /// 放进项目文件夹（沙箱里的代码和我都能读到）。
  Future<void> uploadToProject(String projectId, File f) => _api.upload('/api/projects/$projectId/files', f);

  /// 开始录音；没有麦克风权限返回 false。
  Future<bool> startRecording() async {
    if (!await _recorder.hasPermission()) return false;
    final dir = await getTemporaryDirectory();
    await _recorder.start(const RecordConfig(encoder: AudioEncoder.aacLc, sampleRate: 16000, numChannels: 1),
        path: '${dir.path}/voice-${DateTime.now().millisecondsSinceEpoch}.m4a');
    return true;
  }

  Future<void> cancelRecording() => _recorder.cancel();

  /// 停止并转成文字（服务器端识别）。
  Future<String> stopAndTranscribe() async {
    final path = await _recorder.stop();
    if (path == null) return '';
    final file = File(path);
    try {
      final j = await _api.upload('/api/voice/transcribe', file) as Map<String, dynamic>;
      return (j['text'] as String? ?? '').trim();
    } finally {
      if (await file.exists()) await file.delete();
    }
  }

  void dispose() => _recorder.dispose();
}

final mediaProvider = Provider<Media>((ref) {
  final m = Media(ref.watch(apiProvider));
  ref.onDispose(m.dispose);
  return m;
});
