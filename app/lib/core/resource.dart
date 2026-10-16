// 通用资源列表（与后端 crud_router 的统一形状对应）：列表、新建、修改、删除。
// 每个资源一行声明即可，页面不各自写请求逻辑。加载规则（先给缓存、后台重取、有数据时出错不打扰）全在 core/swr.dart；
// 这里只管增删改。给了 cacheKey 的再落盘（冷启动秒开）；保险箱、钱包不落盘。
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/memory_note.dart';
import '../models/wallet.dart';
import '../models/resources.dart';
import 'api.dart';
import 'swr.dart';

class ResourceNotifier<T> extends SwrNotifier<List<T>> {
  ResourceNotifier(this.path, this.fromJson, this.idOf, {this.replaceOnUpdate = false, this.cacheKey});
  @override
  final String path;

  /// 后端用 PUT 整体替换（技能）而不是 PATCH 局部修改。
  final bool replaceOnUpdate;
  final T Function(Map<String, dynamic>) fromJson;
  final String Function(T) idOf;

  /// 落盘的键（null = 只在内存）。
  final String? cacheKey;

  @override
  String? get diskKey => cacheKey;

  Api get _api => ref.read(apiProvider);

  /// 服务器原样 JSON，与 state 一一对应。
  List<Map<String, dynamic>> get _raw => [for (final j in (raw as List? ?? const [])) (j as Map).cast<String, dynamic>()];

  @override
  List<T> parse(Object? raw) => [for (final j in (raw as List? ?? const [])) fromJson((j as Map).cast<String, dynamic>())];

  Future<T> create(Map<String, dynamic> body) async {
    final j = await _api.post(path, body) as Map<String, dynamic>;
    emit([j, ..._raw]);
    return fromJson(j);
  }

  Future<void> patch(String id, Map<String, dynamic> body) async {
    final res = replaceOnUpdate ? await _api.put('$path/$id', body) : await _api.patch('$path/$id', body);
    final j = res as Map<String, dynamic>;
    emit([for (final x in _raw) idOf(fromJson(x)) == id ? j : x]);
  }

  /// 对单个条目的动作接口（POST path/id/action），返回的新条目原位替换：技能的 customize / reset。
  Future<T> act(String id, String action) async {
    final j = await _api.post('$path/$id/$action') as Map<String, dynamic>;
    emit([for (final x in _raw) idOf(fromJson(x)) == id ? j : x]);
    return fromJson(j);
  }

  Future<void> remove(String id) async {
    await _api.delete('$path/$id');
    emit([for (final x in _raw) if (idOf(fromJson(x)) != id) x]);
  }
}

typedef ResourceProvider<T> = AsyncNotifierProvider<ResourceNotifier<T>, List<T>>;

ResourceProvider<T> _resource<T>(String path, T Function(Map<String, dynamic>) fromJson, String Function(T) idOf,
        {bool replaceOnUpdate = false, String? cacheKey}) =>
    AsyncNotifierProvider<ResourceNotifier<T>, List<T>>(
        () => ResourceNotifier<T>(path, fromJson, idOf, replaceOnUpdate: replaceOnUpdate, cacheKey: cacheKey));

final projectsProvider = _resource<Project>('/api/projects', Project.fromJson, (x) => x.id, cacheKey: 'projects');
final memoriesProvider = _resource<MemoryItem>('/api/memories', MemoryItem.fromJson, (x) => x.id, cacheKey: 'memories');
final memoryNotesProvider = _resource<MemoryNote>('/api/memory-notes', MemoryNote.fromJson, (x) => x.id, cacheKey: 'memory-notes');
final tasksProvider = _resource<ScheduledTask>('/api/tasks', ScheduledTask.fromJson, (x) => x.id, cacheKey: 'tasks');
final cardsProvider = _resource<HomeCard>('/api/cards', HomeCard.fromJson, (x) => x.id, cacheKey: 'cards');
final skillsProvider = _resource<Skill>('/api/catalog/skills', Skill.fromJson, (x) => x.id, replaceOnUpdate: true, cacheKey: 'skills');
// 保险箱、钱包、MCP（地址里可能带凭据）：只在内存，不落盘。
final secretsProvider = _resource<SecretItem>('/api/vault', SecretItem.fromJson, (x) => x.id);
final walletProvider = _resource<PaymentCardItem>('/api/wallet', PaymentCardItem.fromJson, (x) => x.id);
final connectorsProvider = _resource<Connector>('/api/connectors', Connector.fromJson, (x) => x.id, cacheKey: 'connectors');
final mcpServersProvider = _resource<McpServerItem>('/api/connectors/mcp', McpServerItem.fromJson, (x) => x.id);
final pagesProvider = _resource<PageItem>('/api/pages', PageItem.fromJson, (x) => x.id, cacheKey: 'pages');

/// 项目文件按项目区分，所以是 family；路径即 id。
final projectFilesProvider = AsyncNotifierProvider.family<ResourceNotifier<ProjectFile>, List<ProjectFile>, String>(
    (pid) => ResourceNotifier<ProjectFile>('/api/projects/$pid/files', ProjectFile.fromJson, (x) => x.path));
