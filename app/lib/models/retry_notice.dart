/// 模型调用失败、服务器正在自动重试（WS `turn.retry`，v1.50，backend/app/llm_retry.py）。
/// 只挂在生成中的占位消息上给用户一行提示，不存库：
/// - 普通重试（fallback 为空）：新的文字 / 思考 / 工具进度一到就消失（[clearsOn]）；
/// - 换了备用模型：这一轮剩下的时间都留着（用户该知道这条回复是哪个模型答的），回复完成时随占位消息一起换掉。
class RetryNotice {
  const RetryNotice({required this.attempt, required this.max, required this.delayMs, required this.reason, this.code = '', this.fallback, this.fallbackLabel});

  /// 字段缺失/类型不对时给保守值，不让一条坏事件弄崩聊天。
  factory RetryNotice.fromJson(Map<String, dynamic> j) {
    int n(Object? v) => v is num ? v.toInt() : 0;
    final fb = j['fallback'];
    final label = j['fallback_label'];
    final reason = j['reason'];
    final code = j['code'];
    return RetryNotice(
      attempt: n(j['attempt']),
      max: n(j['max']),
      delayMs: n(j['delay_ms']),
      reason: reason is String && reason.trim().isNotEmpty ? reason.trim() : '模型调用出错了',
      code: code is String ? code : '',
      fallback: fb is String && fb.isNotEmpty ? fb : null,
      fallbackLabel: label is String && label.isNotEmpty ? label : null,
    );
  }

  final int attempt, max, delayMs;
  final String reason, code;
  final String? fallback, fallbackLabel;

  bool get isFallback => fallback != null;

  /// 这些事件说明模型又开始产出了：普通重试的提示该收起（block.update 不算——撤回半截文字用的就是它，紧挨在 turn.retry 前面）。
  static const clearsOn = {'block.start', 'block.delta', 'thinking.delta', 'tool.status'};
}

/// 提示行的文字：
/// - 重试：“模型那边限流了，正在重试 2/5”（max 为 0 = 老服务器没给上限，只说“正在重试”）；
/// - 换备用：“刚才模型那边限流了，这一轮改用「快速」”。
String retryNoticeText(RetryNotice n) {
  if (n.isFallback) return '刚才${n.reason}，这一轮改用「${n.fallbackLabel ?? n.fallback}」';
  final count = n.max > 0 && n.attempt > 0 ? ' ${n.attempt}/${n.max}' : '';
  return '${n.reason}，正在重试$count';
}

/// 读屏：重试时多说一句不用操作。
String retryNoticeSemantics(RetryNotice n) => n.isFallback ? retryNoticeText(n) : '${retryNoticeText(n)}，不用操作，会自动接着回答';
