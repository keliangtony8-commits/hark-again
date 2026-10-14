// 钱包里的付款卡（v2.74，后端 app/wallet.py；只有名字 / 卡组织 / 尾号 / 有效期，卡号和安全码永远不回到手机上）。
// 这里还放加卡表单的纯规则（分组显示、卡组织、Luhn、有效期解析），和后端同一套，方便当场提示、不等服务器报错。

class PaymentCardItem {
  const PaymentCardItem({required this.id, required this.label, required this.brand, required this.brandName, required this.last4,
      required this.exp, this.holder = '', this.postalCode = '', this.expired = false, this.lastUsedAt});
  factory PaymentCardItem.fromJson(Map<String, dynamic> j) => PaymentCardItem(
        id: j['id'] as String,
        label: j['label'] as String? ?? '',
        brand: j['brand'] as String? ?? 'card',
        brandName: j['brand_name'] as String? ?? '银行卡',
        last4: j['last4'] as String? ?? '',
        exp: j['exp'] as String? ?? '',
        holder: j['holder'] as String? ?? '',
        postalCode: j['postal_code'] as String? ?? '',
        expired: j['expired'] as bool? ?? false,
        lastUsedAt: DateTime.tryParse(j['last_used_at'] as String? ?? '')?.toLocal(),
      );
  final String id, label, brand, brandName, last4, exp, holder, postalCode;
  final bool expired;
  final DateTime? lastUsedAt;

  /// 行副标题：Visa •••• 1111 · 有效期 09/28
  String get line => '$brandName •••• $last4 · 有效期 $exp';
}

/// 卡号只留数字。
String cardDigits(String s) => s.replaceAll(RegExp(r'\D'), '');

/// 卡号分组显示：运通 4-6-5，其余每 4 位一组。
String groupCardNumber(String digits) {
  final d = cardDigits(digits);
  final sizes = cardBrand(d) == 'amex' ? const [4, 6, 5] : const [4, 4, 4, 4, 4];
  final out = <String>[];
  var i = 0;
  for (final n in sizes) {
    if (i >= d.length) break;
    out.add(d.substring(i, (i + n).clamp(0, d.length)));
    i += n;
  }
  return out.join(' ');
}

/// 卡组织（和后端 wallet.brand 同规则）；位数不够判不出 → 'card'。
String cardBrand(String digits) {
  final n = cardDigits(digits);
  if (n.isEmpty) return 'card';
  int p(int k) => n.length >= k ? int.parse(n.substring(0, k)) : -1;
  if (p(2) == 34 || p(2) == 37) return 'amex';
  if (n.startsWith('4')) return 'visa';
  if ((p(2) >= 51 && p(2) <= 55) || (p(4) >= 2221 && p(4) <= 2720)) return 'mastercard';
  if (p(2) == 62) return 'unionpay';
  if (p(4) >= 3528 && p(4) <= 3589) return 'jcb';
  if (n.startsWith('6011') || p(2) == 65 || (p(3) >= 644 && p(3) <= 649)) return 'discover';
  if (p(2) == 36 || p(2) == 38 || (p(3) >= 300 && p(3) <= 305)) return 'diners';
  return 'card';
}

const brandNames = {
  'visa': 'Visa', 'mastercard': 'Mastercard', 'amex': 'American Express', 'unionpay': '银联',
  'jcb': 'JCB', 'discover': 'Discover', 'diners': 'Diners Club', 'card': '银行卡',
};

bool luhnOk(String digits) {
  final n = cardDigits(digits);
  var total = 0;
  for (var i = 0; i < n.length; i++) {
    var d = int.parse(n[n.length - 1 - i]);
    if (i.isOdd) d = d > 4 ? d * 2 - 9 : d * 2;
    total += d;
  }
  return n.isNotEmpty && total % 10 == 0;
}

/// 卡号的问题（null = 没问题）。银联放宽 Luhn（有的借记卡不满足），和后端一致。
String? cardNumberError(String input) {
  final n = cardDigits(input);
  if (n.length < 12 || n.length > 19) return '卡号位数不对';
  if (cardBrand(n) != 'unionpay' && !luhnOk(n)) return '卡号校验没通过，可能抄错了一位';
  return null;
}

/// "09/28"、"0928"、"9/2028" → (9, 2028)；写不对 → null。只管格式，过期由 [expiryError] 判。
(int, int)? parseExpiry(String s) {
  final m = RegExp(r'^\s*(\d{1,2})\s*[/\-\s]?\s*(\d{2}|\d{4})\s*$').firstMatch(s);
  if (m == null) return null;
  final month = int.parse(m[1]!);
  var year = int.parse(m[2]!);
  if (year < 100) year += 2000;
  if (month < 1 || month > 12) return null;
  return (month, year);
}

String? expiryError(String s, {DateTime? now}) {
  final e = parseExpiry(s);
  if (e == null) return '有效期写成 月/年，比如 09/28';
  final t = now ?? DateTime.now();
  if (e.$2 < t.year || (e.$2 == t.year && e.$1 < t.month)) return '这张卡已经过期了';
  if (e.$2 > t.year + 20) return '有效期的年份不对';
  return null;
}

String? cvcError(String s, String brand) {
  final c = s.trim();
  final want = brand == 'amex' ? 4 : 3;
  if (!RegExp(r'^\d+$').hasMatch(c) || (brand == 'card' ? c.length < 3 || c.length > 4 : c.length != want)) {
    return '安全码是卡背面的 $want 位数字';
  }
  return null;
}

/// 页头摘要：2 张卡 · 1 张已过期
String walletSummary(List<PaymentCardItem> cards) {
  if (cards.isEmpty) return '还没有卡';
  final old = cards.where((c) => c.expired).length;
  return '${cards.length} 张卡${old > 0 ? ' · $old 张已过期' : ''}';
}
