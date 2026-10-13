// 两步验证（v2.58，对标 Hark 设置 → 安全）：服务器 /api/auth/2fa* 的数据和这一页用到的文字规则。
// 规则本身在后端 app/two_factor.py；这里只解析 + 决定怎么说（纯函数，test/two_factor_test.dart 覆盖）。

class TwoFactorStatus {
  const TwoFactorStatus({required this.enabled, this.enabledAt, this.recoveryLeft = 0, this.pending = false});
  final bool enabled;
  final DateTime? enabledAt;
  final int recoveryLeft;
  final bool pending;

  factory TwoFactorStatus.fromJson(Map<String, dynamic> j) => TwoFactorStatus(
        enabled: j['enabled'] == true,
        enabledAt: j['enabled_at'] is String ? DateTime.tryParse(j['enabled_at'] as String)?.toLocal() : null,
        recoveryLeft: (j['recovery_left'] as num?)?.toInt() ?? 0,
        pending: j['pending'] == true,
      );
}

/// setup 的结果：秘钥（四个一组）、otpauth 链接、二维码模块矩阵（"1" 黑 / "0" 白）。
class TwoFactorSetup {
  const TwoFactorSetup({required this.secret, required this.uri, required this.qr, required this.account});
  final String secret, uri, account;
  final List<String> qr;

  factory TwoFactorSetup.fromJson(Map<String, dynamic> j) => TwoFactorSetup(
        secret: '${j['secret'] ?? ''}',
        uri: '${j['uri'] ?? ''}',
        account: '${j['account'] ?? ''}',
        qr: [for (final r in (j['qr'] as List? ?? const [])) '$r'],
      );

  /// 二维码能画：每行一样长、方阵、只有 0/1。
  bool get drawable => qr.isNotEmpty && qr.every((r) => r.length == qr.length && RegExp(r'^[01]+$').hasMatch(r));
}

/// 恢复码剩得少了就提醒重新生成。
const recoveryLow = 2;

String twoFactorSummary(TwoFactorStatus s) => s.enabled ? '两步验证已开' : '两步验证没开';

/// “我的”页那一行的副标题。
String twoFactorRowSubtitle(TwoFactorStatus? s) {
  if (s == null) return '登录时多一道验证码';
  if (!s.enabled) return '没开 · 登录只要密码';
  return s.recoveryLeft <= recoveryLow ? '已开 · 恢复码只剩 ${s.recoveryLeft} 个' : '已开 · 登录要验证码';
}

String recoveryLine(int left) => switch (left) {
      0 => '恢复码用完了，重新生成一组',
      <= recoveryLow => '只剩 $left 个，建议重新生成',
      _ => '还剩 $left 个，每个只能用一次',
    };

/// 复制 / 保存用的纯文本。
String recoveryCodesText(List<String> codes, {String account = ''}) => [
      '私人助手 两步验证恢复码${account.isEmpty ? '' : '（$account）'}',
      '每个只能用一次；手机丢了时代替验证码登录。',
      '',
      ...codes,
    ].join('\n');

/// 登录 / 确认框里的码：去空格和横杠、全角数字转半角；6 位数字 = 验证码，其余按恢复码交给服务器判断。
String cleanCode(String raw) {
  const full = '０１２３４５６７８９';
  final b = StringBuffer();
  for (final ch in raw.trim().split('')) {
    final i = full.indexOf(ch);
    b.write(i >= 0 ? '$i' : ch);
  }
  return b.toString().replaceAll(RegExp(r'[\s_]'), '');
}

bool looksLikeTotp(String raw) => RegExp(r'^\d{6}$').hasMatch(cleanCode(raw));
