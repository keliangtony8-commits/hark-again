// 消息块：与后端 backend/app/blocks.py、docs/protocol.md 一一对应。
// 新增块类型 = 这里加一个类 + blocks/ 里加一个组件 + registry 登记。认不出的类型变成 UnknownBlock，不崩。
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
        'code' => CodeBlock(language: j['language'] as String? ?? '', title: j['title'] as String?, source: j['source'] as String? ?? ''),
        'file' => FileBlock(
            source: j['source'] as String? ?? 'upload',
            id: j['id'] as String,
            name: j['name'] as String? ?? '',
            mime: j['mime'] as String? ?? 'application/octet-stream',
            size: (j['size'] as num?)?.toInt() ?? 0,
            projectId: j['project_id'] as String?),
        'approval' => ApprovalBlock(
            id: j['id'] as String, title: j['title'] as String? ?? '', detail: j['detail'] as String? ?? '', state: j['state'] as String? ?? 'pending'),
        'browser' => BrowserBlock(j['session'] as String? ?? 'main'),
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

class CodeBlock extends Block {
  const CodeBlock({required this.language, this.title, required this.source});
  final String language, source;
  final String? title;
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

class ApprovalBlock extends Block {
  const ApprovalBlock({required this.id, required this.title, required this.detail, required this.state});
  final String id, title, detail, state;
  bool get pending => state == 'pending';
}

class BrowserBlock extends Block {
  const BrowserBlock(this.session);
  final String session;
}

/// 项目沙盒里的后台任务卡（后端 app/jobs.py）。块里是落库时的状态；运行中由卡片自己轮询 /api/jobs/{id}（models/job.dart）。
class JobBlock extends Block {
  const JobBlock({required this.id, required this.title, required this.command, required this.state,
      this.startedAt, this.finishedAt, this.exitCode, this.tail});
  factory JobBlock.fromJson(Map<String, dynamic> j) => JobBlock(
      id: j['id'] as String? ?? '',
      title: j['title'] as String? ?? '后台任务',
      command: j['command'] as String? ?? '',
      state: j['state'] as String? ?? 'running',
      startedAt: DateTime.tryParse(j['started_at'] as String? ?? '')?.toLocal(),
      finishedAt: DateTime.tryParse(j['finished_at'] as String? ?? '')?.toLocal(),
      exitCode: (j['exit_code'] as num?)?.toInt(),
      tail: j['tail'] as String?);
  final String id, title, command, state;
  final DateTime? startedAt, finishedAt;
  final int? exitCode;
  final String? tail;
}

class PageBlock extends Block {
  const PageBlock({required this.slug, required this.title, required this.url});
  final String slug, title, url;
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
      ApprovalBlock() || OrderBlock() || FormBlock() || ProductsBlock() || SummaryBlock() || BrowserBlock() || JobBlock() => true,
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
/// / phone（电话键盘）/ multiline（多行：地址、备注）。options = 可点选的候选（点了填进框里，仍可改）；optional = 选填。
class FormInput {
  const FormInput({required this.name, required this.label, this.kind = 'text', this.value, this.options = const [], this.optional = false});
  factory FormInput.fromJson(Map<String, dynamic> j) => FormInput(
      name: j['name'] as String? ?? '',
      label: j['label'] as String? ?? '',
      kind: j['kind'] as String? ?? 'text',
      value: j['value'] as String?,
      options: [for (final o in (j['options'] as List? ?? [])) if (o is String && o.isNotEmpty) o],
      optional: j['optional'] as bool? ?? false);
  final String name, label, kind;
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
/// login / code 的值只发给服务器交给浏览器，不写进卡片；info（ask_user）提交后服务器把 answers 写回卡片。
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

  /// 填好了没有：必填的都不是空白（选填可以空着）。
  bool completeWith(Map<String, String> values) =>
      fields.every((f) => f.optional || (values[f.name] ?? '').trim().isNotEmpty);
}

/// “复制”一条回复得到的 Markdown（和后端 blocks.py 的 blocks_to_text 同一套规则，表格转成 Markdown 表）。
/// 只复制内容：审批卡、浏览器画面这类过程卡片不进剪贴板。
String copyText(List<Block> blocks) => [
      for (final b in blocks)
        switch (b) {
          TextBlock(:final text) => text.trim(),
          CodeBlock(:final language, :final source) => '```$language\n$source\n```',
          TableBlock(:final title, :final columns, :final rows, :final note) => [
              if (title != null && title.isNotEmpty) '**$title**',
              '| ${columns.join(' | ')} |',
              '|${List.filled(columns.length, ' --- ').join('|')}|',
              for (final r in rows) '| ${r.join(' | ')} |',
              if (note != null && note.isNotEmpty) note,
            ].join('\n'),
          LinksBlock(:final items) => [for (final i in items) '- ${i.title ?? i.label ?? i.url} ${i.url}'].join('\n'),
          PageBlock(:final title, :final url) => '$title $url',
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
