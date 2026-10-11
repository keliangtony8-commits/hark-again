// 本地离线缓存：只存服务器原样返回的 JSON（不另写序列化），打开即显示、断网可读。
// 规则：
//  - 缓存是“锦上添花”：读写失败一律吞掉，绝不让缓存问题弄坏界面（测试里没有 path_provider 也照常跑）。
//  - 按服务器地址分命名空间；退出登录时 SessionNotifier.signOut 整个清空（换人登录看不到上一个人的数据）。
//  - 页面不直接用它：对话走 features/chat/chat_cache.dart，列表资源走 core/resource.dart 的 cacheKey。
import 'dart:convert';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import 'session.dart';

abstract class CacheStore {
  Future<Object?> read(String key);
  Future<void> write(String key, Object? json);
  Future<void> remove(String key);
  Future<void> clear();
}

/// 测试和“没有磁盘”的场合用。
class MemoryCacheStore implements CacheStore {
  final data = <String, String>{};
  @override
  Future<Object?> read(String key) async => data[key] == null ? null : jsonDecode(data[key]!);
  @override
  Future<void> write(String key, Object? json) async => data[key] = jsonEncode(json);
  @override
  Future<void> remove(String key) async => data.remove(key);
  @override
  Future<void> clear() async => data.clear();
}

/// 应用支持目录下 `cache/命名空间/key.json`；先写临时文件再改名，断电也不会留下半个文件。
class FileCacheStore implements CacheStore {
  FileCacheStore(this.namespace, {Future<Directory> Function()? root}) : _root = root ?? getApplicationSupportDirectory;
  final String namespace;
  final Future<Directory> Function() _root;
  Future<Directory>? _dir;

  Future<Directory> get _base async => Directory('${(await _root()).path}/cache');
  Future<Directory> _ensureDir() => _dir ??= () async {
        final d = Directory('${(await _base).path}/$namespace');
        await d.create(recursive: true);
        return d;
      }();

  Future<File> _file(String key) async => File('${(await _ensureDir()).path}/${_safe(key)}.json');

  @override
  Future<Object?> read(String key) async {
    try {
      final f = await _file(key);
      if (!await f.exists()) return null;
      return jsonDecode(await f.readAsString());
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> write(String key, Object? json) async {
    try {
      final f = await _file(key);
      final tmp = File('${f.path}.tmp');
      await tmp.writeAsString(jsonEncode(json), flush: true);
      await tmp.rename(f.path);
    } catch (_) {}
  }

  @override
  Future<void> remove(String key) async {
    try {
      final f = await _file(key);
      if (await f.exists()) await f.delete();
    } catch (_) {}
  }

  /// 清掉所有命名空间（退出登录时调用，不只当前服务器）。
  @override
  Future<void> clear() async {
    try {
      final b = await _base;
      if (await b.exists()) await b.delete(recursive: true);
    } catch (_) {}
    _dir = null;
  }

  static String _safe(String key) => key.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
}

/// FNV-1a：把服务器地址变成短而稳定的目录名（不引入 crypto 依赖）。
String cacheNamespace(String server) {
  var h = 0x811c9dc5;
  for (final c in utf8.encode(server)) {
    h = ((h ^ c) * 0x01000193) & 0xffffffff;
  }
  return 's${h.toRadixString(16)}';
}

final cacheStoreProvider = Provider<CacheStore>((ref) {
  final server = ref.watch(sessionProvider.select((s) => s.value?.server ?? ''));
  return FileCacheStore(cacheNamespace(server));
});
