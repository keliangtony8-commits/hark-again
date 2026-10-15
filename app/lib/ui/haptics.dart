// 震动反馈的唯一入口（v2.99 E4）。全 App 只在少数关键点轻触一下，其余交互不震（克制）：
//   tap   —— 轻选择（selectionClick）：发送消息、开关切换、菜单选中、复制、评分、点气泡看时间、继续、下拉刷新触发
//   press —— 长按确认（mediumImpact）：长按聚焦菜单、接管页长按
// 尊重系统设置：Flutter 引擎 Android 端（PlatformPlugin.vibrateHapticFeedback）所有类型都走 View.performHapticFeedback、不带
// FLAG_IGNORE_GLOBAL_SETTING，系统关了“触摸反馈”就不震；selectionClick → CLOCK_TICK（最轻的一下）、mediumImpact → KEYBOARD_TAP。
// 不用 vibrate()（→ LONG_PRESS，偏重、语义是长按）。按 Apple HIG「Playing haptics」：只给离散事件、同一动作同一种触感、宁少勿多。
// HapticFeedback 只许出现在本文件（test/haptics_test.dart 守卫）。
// 网页端不做振动：见 docs/devlog.md「v2.99」（电脑端无振动；navigator.vibrate 在 iOS 不存在、在 Android 是马达长震且不受系统设置约束）。
import 'package:flutter/services.dart';

abstract final class Haptics {
  static void tap() => HapticFeedback.selectionClick();
  static void press() => HapticFeedback.mediumImpact();
}
