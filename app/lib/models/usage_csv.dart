// 本月用量导出成 CSV（App 用系统分享、网页版下载同一份文本；网页版 lib/usageCsv.ts 是同一套规则）。
// 纯客户端：数据就是已加载的 GET /api/usage 报表，不多发请求。
// 一张“长表”：第一列“类别”区分 汇总 / 每天 / 模型 / 对话，表格软件里一筛就能分开看。
// 汇总里带上月同期 + 上月全月（服务器给了 last_month 才有；没有按模型拆分，输入/输出留空），方便自己算环比。
// 规则：没定价（priced 为空）→ 花费列整列留空；某个模型没定价 → 那一行花费留空；
// 没有输入/输出拆分的行（每天、对话）这两列留空；文本防公式注入；开头带 BOM，Excel 打开中文不乱码。
import 'usage.dart';

const usageCsvHeader = ['类别', '名称', '日期', '调用次数', '输入 token', '输出 token', '总 token'];

String usageCsv(UsageReport r) {
  final money = r.priced.isNotEmpty;
  String cost(double v, {bool priced = true}) => money && priced ? _num(v) : '';
  final rows = <List<String>>[
    [...usageCsvHeader, '花费（${r.currency}）'],
    _period('本月', r.month, money),
    _period('今天', r.today, money),
    if (r.lastMonth case final lm?) ...[_period('上月同期', lm.toDate, money), _period('上月全月', lm.total, money)],
    if (r.budget != null) ['汇总', '预算', '', '', '', '', '', _num(r.budget!)],
    for (final d in r.daily) ['每天', '', _date(d.date), '${d.calls}', '', '', '${d.tokens}', cost(d.cost)],
    for (final m in r.month.models)
      ['模型', m.model, '', '${m.calls}', '${m.promptTokens}', '${m.completionTokens}', '${m.tokens}', cost(m.cost, priced: r.priced.contains(m.model))],
    for (final c in r.conversations) ['对话', c.title ?? '已删除的对话', '', '${c.calls}', '', '', '${c.tokens}', cost(c.cost)],
  ];
  return '\uFEFF${rows.map((row) => row.map(_cell).join(',')).join('\r\n')}\r\n';
}

/// 文件名：用量-2026-10.csv（月份取报表 daily 的第一天，老服务器没有 daily 就用 [at] / 现在）。
String usageCsvFileName(UsageReport r, {DateTime? at}) {
  final d = r.daily.isNotEmpty ? r.daily.first.date : (at ?? DateTime.now());
  return '用量-${d.year}-${d.month.toString().padLeft(2, '0')}.csv';
}

List<String> _period(String name, UsagePeriod p, bool money) {
  final split = p.models.isNotEmpty; // 输入/输出拆分只能从按模型的明细加出来
  int sum(int Function(ModelUsage) f) => p.models.fold(0, (a, m) => a + f(m));
  return [
    '汇总', name, '', '${p.calls}',
    split ? '${sum((m) => m.promptTokens)}' : '',
    split ? '${sum((m) => m.completionTokens)}' : '',
    '${p.tokens}',
    money ? _num(p.cost) : '',
  ];
}

String _date(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// 花费：最多 4 位小数，去掉末尾的 0（0.0012 / 3.5 / 12）。
String _num(double v) {
  var s = v.toStringAsFixed(4);
  if (s.contains('.')) s = s.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  return s == '-0' ? '0' : s;
}

/// 一格：= + - @ 开头的文本前面垫一个 '（防表格软件当公式执行），含逗号/引号/换行就加引号。数字列不会走到注入分支。
String _cell(String v) {
  var s = v;
  if (s.isNotEmpty && '=+-@\t\r'.contains(s[0]) && double.tryParse(s) == null) s = "'$s";
  if (RegExp(r'[",\r\n]').hasMatch(s)) s = '"${s.replaceAll('"', '""')}"';
  return s;
}
