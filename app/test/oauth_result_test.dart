import 'package:assistant/features/me/connectors_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('深链参数 → OAuthResult', () {
    final uri = Uri.parse('myassistant://app/me/connectors?connected=google');
    expect(uri.path, '/me/connectors'); // go_router 只看 path + query
    expect(OAuthResult.fromQuery(uri.queryParameters), const OAuthResult(connected: 'google'));
    expect(OAuthResult.fromQuery({'error': '已取消'})?.error, '已取消');
    expect(OAuthResult.fromQuery(const {}), isNull);
  });
}
