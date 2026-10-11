// 通用资源列表（与后端 crud_router 的统一形状对应）：列表、新建、修改、删除。
// 每个资源一行声明即可，页面不各自写请求逻辑。离线要看的（项目、首页卡片）加 cacheKey。
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/resources.dart';
import 'api.dart';
import 'cache.dart';

class ResourceNotifier<T> extends AsyncNotifier<List<T>> {
  ResourceNotifier(this.path, this.fromJson, this.idOf, {this.replaceOnUpdate = false, this.cacheKey});
  final String path;

  /// 后端用 PUT 整体替换（技能）而不是 PATCH 局部修改。
  final bool replaceOnUpdate;
  final T Function(Map<String, dynamic>) fromJson;
  final String Function(T) idOf;

  /// 给了就离线可读：先用缓存（瞬开），后台再拉新的；后台没连上就继续显示缓存，不打扰。
  final String? cacheKey;

  /// 服务器原样 JSON，与 state 一一对应；缓存存的就是它（模型不用写 toJson）。
  List<Map<String, dynamic>> _raw = [];

  Api get _api => ref.read(apiProvider);
  CacheStore get _cache => ref.read(cacheStoreProvider);

  @override
  Future<List<T>> build() async {
    _raw = [];
    if (cacheKey != null) {
      final cached = await _cache.read(cacheKey!);
      if (cached is List) {
        _raw = [for (final j in cached) if (j is Map) j.cast<String, dynamic>()];
        Future.microtask(_revalidate);
        return _parse();
      }
    }
    _raw = await _fetchRaw();
    _save();
    return _parse();
  }

  Future<List<Map<String, dynamic>>> _fetchRaw() async => [for (final j in (await _api.get(path) as List)) j as Map<String, dynamic>];

  List<T> _parse() => [for (final j in _raw) fromJson(j)];

  void _save() {
    if (cacheKey != null) unawaited(_cache.write(cacheKey!, _raw));
  }

  void _emit(List<Map<String, dynamic>> raw) {
    _raw = raw;
    state = AsyncData(_parse());
    _save();
  }

  Future<void> _revalidate() async {
    try {
      _emit(await _fetchRaw());
    } on ApiError catch (e) {
      if (!e.isNetwork) state = AsyncError(e, StackTrace.current);
    } catch (_) {} // 已被销毁等：缓存照常显示
  }

  Future<void> reload() async => _emit(await _fetchRaw());

  Future<T> create(Map<String, dynamic> body) async {
    final j = await _api.post(path, body) as Map<String, dynamic>;
    _emit([j, ..._raw]);
    return fromJson(j);
  }

  Future<void> patch(String id, Map<String, dynamic> body) async {
    final res = replaceOnUpdate ? await _api.put('$path/$id', body) : await _api.patch('$path/$id', body);
    final j = res as Map<String, dynamic>;
    _emit([for (final x in _raw) idOf(fromJson(x)) == id ? j : x]);
  }

  /// 对单个条目的动作接口（POST path/id/action），返回的新条目原位替换：技能的 customize / reset。
  Future<T> act(String id, String action) async {
    final j = await _api.post('$path/$id/$action') as Map<String, dynamic>;
    _emit([for (final x in _raw) idOf(fromJson(x)) == id ? j : x]);
    return fromJson(j);
  }

  Future<void> remove(String id) async {
    await _api.delete('$path/$id');
    _emit([for (final x in _raw) if (idOf(fromJson(x)) != id) x]);
  }
}

typedef ResourceProvider<T> = AsyncNotifierProvider<ResourceNotifier<T>, List<T>>;

ResourceProvider<T> _resource<T>(String path, T Function(Map<String, dynamic>) fromJson, String Function(T) idOf,
        {bool replaceOnUpdate = false, String? cacheKey}) =>
    AsyncNotifierProvider<ResourceNotifier<T>, List<T>>(
        () => ResourceNotifier<T>(path, fromJson, idOf, replaceOnUpdate: replaceOnUpdate, cacheKey: cacheKey));

final projectsProvider = _resource<Project>('/api/projects', Project.fromJson, (x) => x.id, cacheKey: 'projects');
final memoriesProvider = _resource<MemoryItem>('/api/memories', MemoryItem.fromJson, (x) => x.id);
final tasksProvider = _resource<ScheduledTask>('/api/tasks', ScheduledTask.fromJson, (x) => x.id);
final cardsProvider = _resource<HomeCard>('/api/cards', HomeCard.fromJson, (x) => x.id, cacheKey: 'cards');
final skillsProvider = _resource<Skill>('/api/catalog/skills', Skill.fromJson, (x) => x.id, replaceOnUpdate: true);
final secretsProvider = _resource<SecretItem>('/api/vault', SecretItem.fromJson, (x) => x.id);
final connectorsProvider = _resource<Connector>('/api/connectors', Connector.fromJson, (x) => x.id);
final mcpServersProvider = _resource<McpServerItem>('/api/connectors/mcp', McpServerItem.fromJson, (x) => x.id);
final pagesProvider = _resource<PageItem>('/api/pages', PageItem.fromJson, (x) => x.id);

/// 项目文件按项目区分，所以是 family；路径即 id。
final projectFilesProvider = AsyncNotifierProvider.family<ResourceNotifier<ProjectFile>, List<ProjectFile>, String>(
    (pid) => ResourceNotifier<ProjectFile>('/api/projects/$pid/files', ProjectFile.fromJson, (x) => x.path));
