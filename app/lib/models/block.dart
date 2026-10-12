// 消息块：与后端 backend/app/blocks.py、docs/protocol.md 一一对应。
// 新增块类型 = 这里加一个类 + blocks/ 里加一个组件 + registry 登记。认不出的类型变成 UnknownBlock，不崩。
import 'activity.dart';

sealed class Block {
  const Block();

  factory Block.fromJson(Map<String, dynamic> j) => switch (j['type']) {
        'text' => TextBlock(j['text'] as String? ?? ''),
        'links' => LinksBlock([for (final i in (j['items'] as List? ?? [])) LinkItem.fromJson(i as Map<String, dynamic>)]),
        'table' => TableBlock(
            title: j['title'] as String?,
            columns: [for (final c in j['columns'] as List? ?? []) '$c'],
            rows: [for (final r in j['rows'] as List? ?? []) [for (final c in r as List) '$c']],
            note: j['note'] as String?),
        'code' => CodeBlock(
          language: j['language'] as String? ?? '',
          title: j['title'] as String?,
          source: j['source'] as String? ?? '',
          live: j['live'] == true,
        ),
        'file' => FileBlock(
            source: j['source'] as String? ?? 'upload',
            id: j['id'] as String,
            name: j['name'] as String? ?? '',
            mime: j['mime'] as String? ?? 'application/octet-stream',
            size: (j['size'] as num?)?.toInt() ?? 0,
            projectId: j['project_id'] as String?),
        'approval' => ApprovalBlock(
            id: j['id'] as String,
            title: j['title'] as String? ?? '',
            detail: j['detail'] as String? ?? '',
            state: j['state'] as String? ?? 'pending',
            target: j['target'] as String?,
            host: j['host'] as String?,
            note: j['note'] as String?,
            warn: j['warn'] == true,
            options: [for (final o in (j['options'] as List? ?? const [])) ?ApprovalOption.fromJson(o)],
            granted: j['granted'] as String?),
        'browser' => BrowserBlock(j['session'] as String? ?? 'main',
            site: j['site'] as String?, live: j['live'] == true, handoff: BrowserHandoff.fromJson(j['handoff']),
            files: [for (final f in (j['files'] as List? ?? [])) ?BrowserFile.fromJson(f)], workspace: j['workspace'] as String?),
        'page' => PageBlock(slug: j['slug'] as String, title: j['title'] as String? ?? '', url: j['url'] as String? ?? ''),
        'stats' => StatsBlock([for (final i in (j['items'] as List? ?? [])) StatItem.fromJson(i as Map<String, dynamic>)]),
        'memory' => MemoryBlock(
            action: j['action'] as String? ?? 'saved',
            items: [for (final i in (j['items'] as List? ?? [])) MemoryChange.fromJson(i as Map<String, dynamic>)]),
        'draft' => DraftBlock(title: j['title'] as String? ?? '草稿', body: j['body'] as String? ?? ''),
        'summary' => SummaryBlock(
            title: j['title'] as String? ?? '', subtitle: j['subtitle'] as String?, markdown: j['markdown'] as String? ?? ''),
        'images' => ImagesBlock([
            for (final i in (j['items'] as List? ?? []))
              if (ImageItem.fromJson(i as Map<String, dynamic>) case final it when it.safe) it
          ]),
        'products' => ProductsBlock(
            title: j['title'] as String?,
            pick: j['pick'] as String?,
            items: [for (final i in (j['items'] as List? ?? [])) ProductItem.fromJson(i as Map<String, dynamic>)]),
        'order' => OrderBlock.fromJson(j),
        'form' => FormBlock.fromJson(j),
        'job' => JobBlock.fromJson(j),
        'shell' => ShellBlock.fromJson(j),
        'skill' => SkillBlock(id: j['id'] as String? ?? '', name: j['name'] as String? ?? ''),
        'agent' => AgentBlock(name: j['name'] as String? ?? '子助手'),
        'preview' => PreviewBlock.fromJson(j),
        'plan' => PlanBlock.fromJson(j),
        'delegate' => DelegateBlock.fromJson(j),
        'changes' => ChangesBlock.fromJson(j),
        'plan_review' => PlanReviewBlock(
            id: j['id'] as String? ?? '',
            title: j['title'] as String? ?? '方案',
            plan: j['plan'] as String? ?? '',
            state: j['state'] as String? ?? 'pending',
            workspace: j['workspace'] as String? ?? '',
            path: j['path'] as String? ?? ''),
        _ => UnknownBlock('${j['type']}'),
      };
}

class TextBlock extends Block {
  const TextBlock(this.text);
  final String text;
  TextBlock append(String more) => TextBlock(text + more);
}

class LinkItem {
  const LinkItem({required this.url, this.label, this.title});
  factory LinkItem.fromJson(Map<String, dynamic> j) =>
      LinkItem(url: j['url'] as String, label: j['label'] as String?, title: j['title'] as String?);
  final String url;
  final String? label, title;
}

class LinksBlock extends Block {
  const LinksBlock(this.items);
  final List<LinkItem> items;
}

class TableBlock extends Block {
  const TableBlock({this.title, required this.columns, required this.rows, this.note});
  final String? title, note;
  final List<String> columns;
  final List<List<String>> rows;
}

/// [live]：命令还在跑，[source] 是最近的输出（服务器 block.update 原地换），跑完换成不带 live 的最终块。
class CodeBlock extends Block {
  const CodeBlock({required this.language, this.title, required this.source, this.live = false});
  final String language, source;
  final String? title;
  final bool live;
}

class FileBlock extends Block {
  const FileBlock({required this.source, required this.id, required this.name, required this.mime, required this.size, this.projectId});
  final String source, id, name, mime;
  final int size;
  final String? projectId;
  bool get isImage => mime.startsWith('image/');

  /// 下载路径（未带 token，由 Api.fileUrl 补上）。
  String get path => source == 'project' ? '/api/projects/$projectId/files/$id' : '/api/uploads/$id';
}

/// 审批卡上的一个批准范围（v1.49 主机命令：once 仅这一次 / session 这段对话里都允许 / rule 以后都允许某前缀）。
class ApprovalOption {
  const ApprovalOption(this.id, this.label);
  final String id, label;

  static ApprovalOption? fromJson(dynamic j) {
    if (j is! Map || j['id'] is! String) return null;
    return ApprovalOption(j['id'] as String, j['label'] as String? ?? j['id'] as String);
  }
}

/// 审批卡。主机命令卡（target == 'host'，v1.49）多带机器名、为什么要你看一眼（note；warn = 危险提示）、
/// 批准范围 options（第一个 = “批准”按钮），批准后 granted = 选的那个。
class ApprovalBlock extends Block {
  const ApprovalBlock(
      {required this.id,
      required this.title,
      required this.detail,
      required this.state,
      this.target,
      this.host,
      this.note,
      this.warn = false,
      this.options = const [],
      this.granted});
  final String id, title, detail, state;
  final String? target, host, note, granted;
  final bool warn;
  final List<ApprovalOption> options;
  bool get pending => state == 'pending';
  bool get onHost => target == 'host';
}

/// v1.71 计划模式下交给你批准的方案（后端 app/plan_mode.py；批准走 approval.reply，和审批卡同一条线）。
/// state：pending 等你批准 / approved 已批准（退出计划模式、这一轮按方案做）/ rejected 要改 / expired 没等到答复。
/// workspace + path（v1.72）= 批准后方案存进工作区的位置（老卡为空）。
class PlanReviewBlock extends Block {
  const PlanReviewBlock(
      {required this.id, required this.title, required this.plan, required this.state, this.workspace = '', this.path = ''});
  final String id, title, plan, state, workspace, path;
  bool get pending => state == 'pending';
}

/// 云浏览器实时画面卡。session = 按网站起的会话名（后端 app/browser_sessions.py；旧卡 main），
/// site = 打开的网站（卡头显示），live = 页面还在打开（还没画面时显示“正在打开”，不当作浏览器没开）。
class BrowserBlock extends Block {
  const BrowserBlock(this.session, {this.site, this.live = false, this.handoff, this.files = const [], this.workspace});
  final String session;
  final String? site;
  final bool live;
  final BrowserHandoff? handoff; // v1.29 助手请你接管（验证码、滑块、扫码），规则在 models/browser_view.dart
  final List<BrowserFile> files; // v1.32 这条回复里传到网页上的 / 网页下载存进工作区的文件（最近 8 条）
  final String? workspace; // files 所在工作区 id（点开用工作区文件接口）
}

/// 浏览器和工作区之间搬过的一个文件（后端 app/browser_files.py）：upload = 传到网页上的工作区文件，download = 网页下载、存进工作区的。
class BrowserFile {
  const BrowserFile({required this.kind, required this.name, required this.path});
  static BrowserFile? fromJson(Object? j) => j is Map<String, dynamic> && j['path'] is String
      ? BrowserFile(kind: j['kind'] == 'upload' ? 'upload' : 'download', name: j['name'] as String? ?? '', path: j['path'] as String)
      : null;
  final String kind, name, path;
  bool get uploaded => kind == 'upload';
}

/// 助手请你接管浏览器的那一步（后端 browser_handoff）：pending → done / cancelled / expired。交还 = form.reply（id 即它）。
class BrowserHandoff {
  const BrowserHandoff({required this.id, required this.reason, this.state = 'pending'});
  static BrowserHandoff? fromJson(Object? j) => j is Map<String, dynamic> && j['id'] is String
      ? BrowserHandoff(id: j['id'] as String, reason: j['reason'] as String? ?? '', state: j['state'] as String? ?? 'pending')
      : null;
  final String id, reason, state;
  bool get pending => state == 'pending';
}

/// 项目沙盒里的后台任务卡（后端 app/jobs.py）。块里是落库时的状态；运行中由卡片自己轮询 /api/jobs/{id}（models/job.dart）。
class JobBlock extends Block {
  const JobBlock({required this.id, required this.title, required this.command, required this.state,
      this.startedAt, this.finishedAt, this.exitCode, this.tail, this.stopReason, this.keepAlive = false, this.restarts = 0,
      this.memoryMax, this.memoryPeak});
  factory JobBlock.fromJson(Map<String, dynamic> j) => JobBlock(
      id: j['id'] as String? ?? '',
      title: j['title'] as String? ?? '后台任务',
      command: j['command'] as String? ?? '',
      state: j['state'] as String? ?? 'running',
      startedAt: DateTime.tryParse(j['started_at'] as String? ?? '')?.toLocal(),
      finishedAt: DateTime.tryParse(j['finished_at'] as String? ?? '')?.toLocal(),
      exitCode: (j['exit_code'] as num?)?.toInt(),
      tail: j['tail'] as String?,
      stopReason: j['stop_reason'] as String?,
      keepAlive: j['keep_alive'] as bool? ?? false,
      restarts: (j['restarts'] as num?)?.toInt() ?? 0,
      memoryMax: (j['memory_max'] as num?)?.toInt(),
      memoryPeak: (j['memory_peak'] as num?)?.toInt());
  final String id, title, command, state;
  final DateTime? startedAt, finishedAt;
  final int? exitCode;
  final String? tail;

  /// 被服务器护栏自动停掉的原因（卡住没输出 / 输出过大）；用户或助手取消的没有。
  final String? stopReason;

  /// v1.80 常驻任务：意外退出自动重启；restarts = 重启过几次。
  final bool keepAlive;
  final int restarts;

  /// v1.92 给它单独定的内存上限 / 结束时记下的内存峰值（字节，后端 app/job_memory.py）。
  final int? memoryMax, memoryPeak;
}

/// 用户自己跑的命令（输入框 !命令，后端 ShellBlock）：一条回复里只有它一张。规则在 models/shell.dart。
class ShellBlock extends Block {
  const ShellBlock({required this.command, this.state = 'running', this.output = '', this.exitCode, this.seconds, this.note});
  factory ShellBlock.fromJson(Map<String, dynamic> j) => ShellBlock(
      command: j['command'] as String? ?? '',
      state: j['state'] as String? ?? 'running',
      output: j['output'] as String? ?? '',
      exitCode: (j['exit_code'] as num?)?.toInt(),
      seconds: (j['seconds'] as num?)?.toDouble(),
      note: j['note'] as String?);
  final String command, state, output;
  final int? exitCode;
  final double? seconds;
  final String? note;
  bool get running => state == 'running';
}

class PageBlock extends Block {
  const PageBlock({required this.slug, required this.title, required this.url});
  final String slug, title, url;
}

/// 端口预览卡（后端 PreviewBlock）：工作区里跑着的网页服务，链接带期限。文案规则在 models/preview.dart。
class PreviewBlock extends Block {
  const PreviewBlock({required this.workspace, required this.port, required this.url, this.title, this.command = '', this.expiresAt});
  factory PreviewBlock.fromJson(Map<String, dynamic> j) => PreviewBlock(
        workspace: j['workspace'] as String? ?? '',
        port: (j['port'] as num?)?.toInt() ?? 0,
        url: j['url'] as String? ?? '',
        title: j['title'] as String?,
        command: j['command'] as String? ?? '',
        expiresAt: DateTime.tryParse(j['expires_at'] as String? ?? '')?.toLocal(),
      );
  final String workspace, url, command;
  final int port;
  final String? title;
  final DateTime? expiresAt;
}

class StatItem {
  const StatItem({required this.label, required this.value, this.note});
  factory StatItem.fromJson(Map<String, dynamic> j) =>
      StatItem(label: j['label'] as String? ?? '', value: j['value'] as String? ?? '', note: j['note'] as String?);
  final String label, value;
  final String? note;
}

/// 几个关键数字（面板、简报）：每项一块 标签 + 大数字 的小卡片。
class StatsBlock extends Block {
  const StatsBlock(this.items);
  final List<StatItem> items;
}

/// 记忆卡里的一条：被记住/改/忘掉的记忆。previous 只有 updated 才有（改前内容，撤销用）。
class MemoryChange {
  const MemoryChange({required this.id, required this.content, required this.category, this.previous});
  factory MemoryChange.fromJson(Map<String, dynamic> j) => MemoryChange(
      id: j['id'] as String? ?? '',
      content: j['content'] as String? ?? '',
      category: j['category'] as String? ?? 'general',
      previous: j['previous'] as String?);
  final String id, content, category;
  final String? previous;
}

/// 记忆卡：本轮回复里记住（saved）/ 改了（updated）/ 忘掉了（forgotten）哪些事。
/// “已撤销”不存在块里，由 models/memory.dart memoryCardState 对照当前记忆列表推算。
class MemoryBlock extends Block {
  const MemoryBlock({required this.action, required this.items});
  final String action;
  final List<MemoryChange> items;
}

/// 草稿卡：用户要以自己名义发出去的文字（邮件连主题行、消息、帖子）。原样显示，复制 / 分享。
class DraftBlock extends Block {
  const DraftBlock({required this.title, required this.body});
  final String title, body;
}

/// 摘要卡：用户自己读的长文（计划、行程、简报），带标题的一份 Markdown。
class SummaryBlock extends Block {
  const SummaryBlock({required this.title, this.subtitle, required this.markdown});
  final String title, markdown;
  final String? subtitle;
}

class ImageItem {
  const ImageItem({required this.url, this.caption});
  factory ImageItem.fromJson(Map<String, dynamic> j) => ImageItem(url: j['url'] as String? ?? '', caption: j['caption'] as String?);
  final String url;
  final String? caption;

  /// 只显示 http(s) 图片（服务器已校验，客户端再守一道）
  bool get safe => url.startsWith('https://') || url.startsWith('http://');
}

/// 图片卡：用户想看样子时的一组网络图片（1–6 张）。
class ImagesBlock extends Block {
  const ImagesBlock(this.items);
  final List<ImageItem> items;
}

/// 只认 http(s) 地址（服务器已校验，客户端再守一道）；其它一律当没有。
String? _http(Object? v) => v is String && (v.startsWith('https://') || v.startsWith('http://')) ? v : null;

class ProductItem {
  const ProductItem({required this.name, this.price, this.image, this.url, this.meta});
  factory ProductItem.fromJson(Map<String, dynamic> j) => ProductItem(
      name: j['name'] as String? ?? '',
      price: j['price'] as String?,
      image: _http(j['image']),
      url: _http(j['url']),
      meta: j['meta'] as String?);
  final String name;
  final String? price, image, url, meta;
}

/// 商品宫格：挑要买/要订、样子也算数的一组东西。一格 = 图 + 名字 + 价格 + 一行补充；pick = 一句推荐。
class ProductsBlock extends Block {
  const ProductsBlock({this.title, this.pick, required this.items});
  final String? title, pick;
  final List<ProductItem> items;

  /// 有任何一件带图才排宫格；一张图都没有就排成清单（v0.86：整屏空白方块没信息量）。
  bool get hasPictures => items.any((i) => i.image != null);
}

/// 没图时占位用的“字标”：名字的第一个字（跳过空白和标点），大写。网页 lib/monogram.ts 同规则。
String monogramOf(String name) {
  for (final r in name.runes) {
    final c = String.fromCharCode(r);
    if (RegExp(r'[\p{L}\p{N}]', unicode: true).hasMatch(c)) return c.toUpperCase();
  }
  return '·';
}

class OrderLine {
  const OrderLine({required this.name, required this.price, this.qty = 1, this.note, this.image});
  factory OrderLine.fromJson(Map<String, dynamic> j) => OrderLine(
      name: j['name'] as String? ?? '',
      price: j['price'] as String? ?? '',
      qty: (j['qty'] as num?)?.toInt() ?? 1,
      note: j['note'] as String?,
      image: _http(j['image']));
  final String name, price;
  final int qty;
  final String? note, image;
}

class OrderFee {
  const OrderFee(this.label, this.amount);
  final String label, amount;
}

/// 订单卡：付款前的确认（pending，按钮走审批 approval.reply）或下单后的回执（placed，带订单号）。
/// 金额全部原样显示，客户端不算账。
class OrderBlock extends Block {
  const OrderBlock({
    required this.id,
    required this.merchant,
    required this.items,
    this.breakdown = const [],
    required this.total,
    this.payment,
    this.destination,
    this.orderNumber,
    this.action = '确认下单',
    this.state = 'pending',
  });
  factory OrderBlock.fromJson(Map<String, dynamic> j) => OrderBlock(
      id: j['id'] as String? ?? '',
      merchant: j['merchant'] as String? ?? '',
      items: [for (final i in (j['items'] as List? ?? [])) OrderLine.fromJson(i as Map<String, dynamic>)],
      breakdown: [
        for (final f in (j['breakdown'] as List? ?? []))
          OrderFee((f as Map)['label'] as String? ?? '', f['amount'] as String? ?? '')
      ],
      total: j['total'] as String? ?? '',
      payment: j['payment'] as String?,
      destination: j['destination'] as String?,
      orderNumber: j['order_number'] as String?,
      action: j['action'] as String? ?? '确认下单',
      state: j['state'] as String? ?? 'pending');
  final String id, merchant, total, action, state;
  final List<OrderLine> items;
  final List<OrderFee> breakdown;
  final String? payment, destination, orderNumber;
  bool get pending => state == 'pending';
  bool get placed => state == 'placed';
}

/// 计划清单（后端 app/plan.py，update_plan 产出，v1.47）：一条回复里一张，助手边做边勾。文案规则在 models/plan.dart。
class PlanBlock extends Block {
  const PlanBlock({required this.items, this.explanation, this.settled = false});
  factory PlanBlock.fromJson(Map<String, dynamic> j) => PlanBlock(
      items: [for (final i in (j['items'] as List? ?? [])) if (i is Map<String, dynamic>) PlanItem.fromJson(i)],
      explanation: j['explanation'] as String?,
      settled: j['settled'] == true);
  final List<PlanItem> items;
  final String? explanation; // 最近一次改计划的原因
  final bool settled; // 这一轮已结束：没做完的步骤定格，不再闪“进行中”
}

enum PlanStatus { pending, inProgress, completed }

class PlanItem {
  const PlanItem(this.content, this.status);
  factory PlanItem.fromJson(Map<String, dynamic> j) => PlanItem(
      j['content'] as String? ?? '',
      switch (j['status']) { 'in_progress' => PlanStatus.inProgress, 'completed' => PlanStatus.completed, _ => PlanStatus.pending });
  final String content;
  final PlanStatus status;
}

/// 这一轮改过的文件（后端 app/turn_changes.py 收尾时出，v1.68）：每个文件一份净 diff；
/// token 非空 = 能整轮撤销；undone = 已撤销。文案规则在 models/changes.dart。
class ChangesBlock extends Block {
  const ChangesBlock({this.token = '', this.files = const [], this.more = 0, this.undone = false});
  factory ChangesBlock.fromJson(Map<String, dynamic> j) => ChangesBlock(
      token: j['token'] as String? ?? '',
      files: [for (final f in (j['files'] as List? ?? [])) ?FileChange.fromJson(f)],
      more: (j['more'] as num?)?.toInt() ?? 0,
      undone: j['undone'] == true);
  final String token;
  final List<FileChange> files;
  final int more; // 卡上没列出的文件数（撤销仍覆盖它们）
  final bool undone;
}

/// 子助手（后端 agent/subagent.py，delegate 产出，v1.48）：一次并行派出的几个子任务，执行中 live 原地更新。
/// 文案规则在 models/delegate.dart。
class DelegateBlock extends Block {
  const DelegateBlock({required this.tasks, this.live = false});
  factory DelegateBlock.fromJson(Map<String, dynamic> j) => DelegateBlock(
      tasks: [for (final t in (j['tasks'] as List? ?? [])) if (t is Map<String, dynamic>) DelegateTask.fromJson(t)],
      live: j['live'] == true);
  final List<DelegateTask> tasks;
  final bool live; // 还在跑（这一轮没结束）
}

enum DelegateState { running, done, partial, failed, stopped }

class DelegateTask {
  const DelegateTask(this.title, this.state, {this.steps = 0, this.now, this.seconds, this.result, this.note});
  factory DelegateTask.fromJson(Map<String, dynamic> j) => DelegateTask(
        j['title'] as String? ?? '',
        switch (j['state']) {
          'done' => DelegateState.done,
          'partial' => DelegateState.partial,
          'failed' => DelegateState.failed,
          'stopped' => DelegateState.stopped,
          _ => DelegateState.running,
        },
        steps: (j['steps'] as num?)?.toInt() ?? 0,
        now: j['now'] as String?,
        seconds: (j['seconds'] as num?)?.toInt(),
        result: j['result'] as String?,
        note: j['note'] as String?,
      );
  final String title;
  final DelegateState state;
  final int steps;
  final String? now; // 正在做的那一步（“正在搜索”）
  final int? seconds;
  final String? result; // 交回的结论（截断）
  final String? note; // 没做完 / 出错的原因
}

/// 用户消息里 `$技能` 点名的技能（v1.81，服务器 app/skill_mentions.py 认出来的）：气泡上方一枚小标签。
class SkillBlock extends Block {
  const SkillBlock({required this.id, required this.name});
  final String id, name;
}

/// 用户消息里 `@子助手` 点名交给子助手（v1.91，服务器 app/agent_mentions.py）：气泡上方一枚小标签。
class AgentBlock extends Block {
  const AgentBlock({this.name = '子助手'});
  final String name;
}

class UnknownBlock extends Block {
  const UnknownBlock(this.type);
  final String type;
}

/// 回复里的一段（v0.84）：连续的正文类块（文字、代码、表格、链接、数字、文件、草稿、图片、记忆）
/// 放进同一张回复卡；卡片类块（要扫一眼或要点的：审批、订单、表单、商品、摘要、浏览器）单独成卡，
/// 宽度占满聊天区，不再套在回复卡里（卡中卡、两层边框、窄得挤）。
class ReplySegment {
  const ReplySegment.prose(this.blocks) : card = false;
  ReplySegment.card(Block block)
      : blocks = [block],
        card = true;
  final List<Block> blocks;
  final bool card;
}

bool standsAlone(Block b) => switch (b) {
      ApprovalBlock() || OrderBlock() || FormBlock() || ProductsBlock() || SummaryBlock() || BrowserBlock() || JobBlock() || ShellBlock() || PlanBlock() || DelegateBlock() || ChangesBlock() || PlanReviewBlock() => true,
      _ => false,
    };

List<ReplySegment> replySegments(List<Block> blocks) {
  final out = <ReplySegment>[];
  var prose = <Block>[];
  for (final b in blocks) {
    if (b is UnknownBlock) continue; // 旧 App 不认识的新卡片：不占位，也不把前后正文切开
    if (!standsAlone(b)) {
      prose.add(b);
      continue;
    }
    if (prose.isNotEmpty) out.add(ReplySegment.prose(prose));
    prose = <Block>[];
    out.add(ReplySegment.card(b));
  }
  if (prose.isNotEmpty) out.add(ReplySegment.prose(prose));
  return out;
}

List<Block> blocksFrom(dynamic list) => [for (final b in (list as List? ?? [])) Block.fromJson(b as Map<String, dynamic>)];

String plainText(List<Block> blocks) => blocks.whereType<TextBlock>().map((b) => b.text).join('\n').trim();

/// 表单卡里的一个输入框。kind：text / email / password（遮住）/ code（数字键盘 + 短信验证码自动填充）
/// / phone（电话键盘）/ multiline（多行：地址、备注）。options = 可点选的候选（点了填进框里，仍可改）；optional = 选填；
/// minLength = 至少几个字符才能提交（要环境变量卡：太短的值没法在输出里可靠地打码）。
class FormInput {
  const FormInput(
      {required this.name, required this.label, this.kind = 'text', this.value, this.options = const [], this.optional = false, this.minLength = 0});
  factory FormInput.fromJson(Map<String, dynamic> j) => FormInput(
      name: j['name'] as String? ?? '',
      label: j['label'] as String? ?? '',
      kind: j['kind'] as String? ?? 'text',
      value: j['value'] as String?,
      options: [for (final o in (j['options'] as List? ?? [])) if (o is String && o.isNotEmpty) o],
      optional: j['optional'] as bool? ?? false,
      minLength: (j['min_length'] as num?)?.toInt() ?? 0);
  final String name, label, kind;
  final int minLength;

  /// 填了但还不够长（输入框下提示“至少 N 个字符”）；空着不算（空着由必填规则管）。
  bool tooShort(String v) => v.trim().isNotEmpty && v.length < minLength;
  final String? value; // 服务器预填的（只有不敏感的，如用户名、已知的默认值）
  final List<String> options;
  final bool optional;
}

/// info 卡提交后回显的一问一答（只有 purpose=info 才有：那是用户有意告诉助手的）。
class FormAnswer {
  const FormAnswer(this.label, this.value);
  final String label, value;
}

/// 表单卡：任务进行中向用户要东西（网站登录、验证码、助手缺的信息），答复走 form.reply。
/// login / code 的值只发给服务器交给浏览器，env（request_env）的值只发给服务器存进保险箱，都不写进卡片；
/// info（ask_user）提交后服务器把 answers 写回卡片。
class FormBlock extends Block {
  const FormBlock({
    required this.id,
    this.purpose = 'info',
    required this.title,
    this.site,
    required this.fields,
    this.remember = false,
    this.action = '提交',
    this.state = 'pending',
    this.note,
    this.answers = const [],
  });
  factory FormBlock.fromJson(Map<String, dynamic> j) => FormBlock(
      id: j['id'] as String? ?? '',
      purpose: j['purpose'] as String? ?? 'info',
      title: j['title'] as String? ?? '',
      site: j['site'] as String?,
      fields: [for (final f in (j['fields'] as List? ?? [])) FormInput.fromJson(f as Map<String, dynamic>)],
      remember: j['remember'] as bool? ?? false,
      action: j['action'] as String? ?? '提交',
      state: j['state'] as String? ?? 'pending',
      note: j['note'] as String?,
      answers: [
        for (final a in (j['answers'] as List? ?? []))
          if (a is Map) FormAnswer(a['label'] as String? ?? '', a['value'] as String? ?? ''),
      ]);
  final String id, purpose, title, action, state;
  final String? site, note;
  final List<FormInput> fields;
  final List<FormAnswer> answers;
  final bool remember; // 是否提供“记住”（login → 保险箱；info → 长期记忆）
  bool get pending => state == 'pending';

  /// 填好了没有：必填的都不是空白（选填可以空着），填了的都够长。
  bool completeWith(Map<String, String> values) => fields.every((f) {
        final v = values[f.name] ?? '';
        return (f.optional || v.trim().isNotEmpty) && !f.tooShort(v);
      });
}

/// “复制”一条回复得到的 Markdown（和后端 blocks.py 的 blocks_to_text 同一套规则，表格转成 Markdown 表）。
/// 只复制内容：审批卡、浏览器画面这类过程卡片不进剪贴板。
String copyText(List<Block> blocks) => [
      for (final b in blocks)
        switch (b) {
          TextBlock(:final text) => text.trim(),
          CodeBlock(:final language, :final source) => '```$language\n$source\n```',
          ShellBlock(:final command, :final output) => '```bash\n\$ $command\n${output.trimRight()}\n```',
          TableBlock(:final title, :final columns, :final rows, :final note) => [
              if (title != null && title.isNotEmpty) '**$title**',
              '| ${columns.join(' | ')} |',
              '|${List.filled(columns.length, ' --- ').join('|')}|',
              for (final r in rows) '| ${r.join(' | ')} |',
              if (note != null && note.isNotEmpty) note,
            ].join('\n'),
          LinksBlock(:final items) => [for (final i in items) '- ${i.title ?? i.label ?? i.url} ${i.url}'].join('\n'),
          PageBlock(:final title, :final url) => '$title $url',
          PreviewBlock(:final port, :final title, :final url) => '${title ?? '端口 $port'} $url',
          FileBlock(:final name) => '[文件：$name]',
          StatsBlock(:final items) => [for (final i in items) '${i.label}：${i.value}${i.note != null && i.note!.isNotEmpty ? '（${i.note}）' : ''}'].join('\n'),
          DraftBlock(:final body) => body.trim(),
          SummaryBlock(:final title, :final subtitle, :final markdown) =>
            ['**$title**', if (subtitle != null && subtitle.isNotEmpty) subtitle, markdown.trim()].join('\n\n'),
          ImagesBlock(:final items) => [for (final i in items) '- ${i.caption ?? '图片'} ${i.url}'].join('\n'),
          ProductsBlock(:final title, :final pick, :final items) => [
              if (title != null && title.isNotEmpty) '**$title**',
              for (final i in items) '- ${[i.name, i.price, i.meta, i.url].where((x) => x != null && x.isNotEmpty).join(' ')}',
              if (pick != null && pick.isNotEmpty) pick,
            ].join('\n'),
          _ => '',
        },
    ].where((s) => s.isNotEmpty).join('\n\n');
