// 把内容交给系统分享面板（存到文件、发给微信/邮件……）。share_plus 只在这里出现。
import 'dart:convert';
import 'dart:ui' show Rect;

import 'package:share_plus/share_plus.dart';

/// 以文件形式分享一段文本。[origin] 是触发按钮在屏幕上的位置（iPad 的弹出框要用）。
/// 返回 false = 用户取消或系统不支持。
Future<bool> shareTextFile(String fileName, String text, {String mime = 'text/markdown', Rect? origin}) async {
  final r = await SharePlus.instance.share(ShareParams(
    files: [XFile.fromData(utf8.encode(text), mimeType: mime, name: fileName)],
    fileNameOverrides: [fileName],
    subject: fileName,
    sharePositionOrigin: origin,
  ));
  return r.status == ShareResultStatus.success;
}

/// 分享一个链接（发给微信好友、复制到备忘录……）。返回 false = 用户取消或系统不支持。
Future<bool> shareLink(String url, {String? subject, Rect? origin}) async {
  final r = await SharePlus.instance.share(ShareParams(text: url, subject: subject, sharePositionOrigin: origin));
  return r.status == ShareResultStatus.success;
}
