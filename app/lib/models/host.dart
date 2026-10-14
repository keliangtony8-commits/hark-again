// 服务器主机模式（v1.49，后端 app/host_mode.py + app/host_policy.py，接口 GET/PUT /api/host、DELETE /api/host/rules/{id}）。
// 纯规则：状态文案、规则行、审批卡上的批准范围文案、读屏句子；网页版 lib/host.ts 同一套。
import '../ui/format.dart';
import 'block.dart';

class HostRule {
  const HostRule({required this.id, required this.text, this.uses = 0, this.createdAt, this.lastUsedAt});

  factory HostRule.fromJson(Map<String, dynamic> j) => HostRule(
        id: j['id'] as String,
        text: j['text'] as String? ?? ((j['prefix'] as List?)?.join(' ') ?? ''),
        uses: (j['uses'] as num?)?.toInt() ?? 0,
        createdAt: DateTime.tryParse(j['created_at'] as String? ?? '')?.toLocal(),
        lastUsedAt: DateTime.tryParse(j['last_used_at'] as String? ?? '')?.toLocal(),
      );

  final String id, text;
  final int uses;
  final DateTime? createdAt, lastUsedAt;
}

class HostStatus {
  const HostStatus(
      {this.installed = false,
      this.enabled = false,
      this.reachable = false,
      this.hostname,
      this.os,
      this.uptimeSeconds,
      this.rules = const []});

  factory HostStatus.fromJson(Map<String, dynamic> j) {
    final h = (j['host'] as Map?)?.cast<String, dynamic>();
    return HostStatus(
      installed: j['installed'] == true,
      enabled: j['enabled'] == true,
      reachable: j['reachable'] == true,
      hostname: h?['hostname'] as String?,
      os: h?['os'] as String?,
      uptimeSeconds: (h?['uptime_seconds'] as num?)?.toInt(),
      rules: [for (final r in (j['rules'] as List? ?? const [])) HostRule.fromJson((r as Map).cast<String, dynamic>())],
    );
  }

  final bool installed, enabled, reachable;
  final String? hostname, os;
  final int? uptimeSeconds;
  final List<HostRule> rules;

  /// 开关能不能拨：没装不能开；已经开着的任何时候都能关。
  bool get canToggle => installed || enabled;
}

const hostSectionTitle = '服务器主机';
const hostInstallHint = '在服务器上运行 sudo bash deploy/install.sh --host-agent 装好主机代理，再回来打开。';
const hostEnableText = '打开后，我可在这台 VPS 本机以 root 运行命令：装系统软件、管服务、看系统日志、改配置。'
    '每条命令都会先弹卡等你批准；你点过“以后都允许”的那类除外。随时可以在这里关掉。';
const hostRulesEmpty = '还没有“以后都允许”的命令';
const hostRulesEmptyLine = '在审批卡上选“以后都允许…”，那类命令以后就不再问你，定时任务也能用。';

/// 开关那一行的标题。
String hostToggleTitle(HostStatus s) => s.enabled ? '主机模式已打开' : '主机模式已关闭';

/// 开关那一行的说明：机器 + 系统；没装 / 连不上说清楚。
String hostDetail(HostStatus s) {
  if (!s.installed) return '还没装主机代理';
  if (!s.reachable) return '无法连接主机代理';
  final parts = [if (s.hostname != null) s.hostname!, if (s.os != null) s.os!];
  if (s.uptimeSeconds != null) parts.add('已开机 ${hostUptime(s.uptimeSeconds!)}');
  return parts.isEmpty ? '主机代理在线' : parts.join(' · ');
}

/// 只在出问题时给行尾一句（RowHint warn）。
String? hostHint(HostStatus s) => s.installed && !s.reachable ? '无法连接' : null;

String hostUptime(int seconds) {
  final d = seconds ~/ 86400, h = seconds % 86400 ~/ 3600, m = seconds % 3600 ~/ 60;
  if (d > 0) return h > 0 ? '$d 天 $h 小时' : '$d 天';
  if (h > 0) return '$h 小时';
  return '${m < 1 ? 1 : m} 分钟';
}

/// 规则行说明：用过几次、最近一次。
String hostRuleDetail(HostRule r, {DateTime? now}) {
  if (r.uses == 0) return r.createdAt == null ? '还没用过' : '${formatAgo(r.createdAt, now: now)}加的，还没用过';
  final last = r.lastUsedAt == null ? '' : ' · 上次 ${formatAgo(r.lastUsedAt, now: now)}';
  return '放行过 ${r.uses} 次$last';
}

String hostRuleDeleteText(HostRule r) => '以后 ${r.text} 开头的命令又会先问你。';

// ---------- 审批卡 ----------

/// 批准后卡上那句：选了哪种范围（仅这一次不写）。
String? approvalGrantedLine(ApprovalBlock b) {
  if (b.state != 'approved' || b.granted == null || b.granted == 'once') return null;
  final o = b.options.where((o) => o.id == b.granted).firstOrNull;
  return o == null ? null : '已选：${o.label}';
}

/// 卡上除了主按钮之外的批准范围（第一个是“批准”按钮本身）。
List<ApprovalOption> approvalExtraOptions(ApprovalBlock b) => b.options.length > 1 ? b.options.sublist(1) : const [];

String approvalSemantics(ApprovalBlock b) {
  final where = b.onHost ? '在服务器${b.host == null ? '' : ' ${b.host}'}上运行' : b.title;
  final state = switch (b.state) { 'approved' => '已批准', 'rejected' => '已拒绝', 'expired' => '已过期', _ => '等你确认' };
  final note = (b.note ?? '').isEmpty ? '' : '，${b.note}';
  return '$where：${b.detail}$note，$state';
}
