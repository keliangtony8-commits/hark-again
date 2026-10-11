// 打开外部地址（系统浏览器 / 对应 App）。url_launcher 只在这里出现。
// 反方向（外部 → App）走深链：appScheme://app/<路由>?…，由 go_router 直接当作路由打开。
import 'package:url_launcher/url_launcher.dart';

/// 深链 scheme。改它要同步：AndroidManifest.xml、ios/Runner/Info.plist、后端 APP_SCHEME。
const appScheme = 'myassistant';

Future<void> openUrl(String url) => launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);

String hostOf(String url) => Uri.tryParse(url)?.host.replaceFirst('www.', '') ?? url;
