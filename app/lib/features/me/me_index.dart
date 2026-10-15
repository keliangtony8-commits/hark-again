// “我的”页底部设置搜索的索引（v3.0，docs/devlog.md「2026-10-15 v3.0」）：全 App 唯一的设置搜索，只搜“某个设置 / 页面在哪”，
// 不搜对话（对话在历史抽屉里搜）。网页同一份在 frontend/src/features/me/meIndex.ts——两份逐字对照，test/me_search_test.dart 会比，
// 也会检查每个路由都在 app.dart、每个定位 id 在页面里真有 Spotlight（网页有 spot=）。改设置页的行 / 分区时顺手改这里。
// 一行一条：e(id, 标题, 分区, 路由, 定位 id 或 null, '空格分隔的同义词')。分区决定结果行的图标和“所在位置”。
import 'package:flutter/material.dart';

import '../../ui/kit.dart' show searchTerms;

enum MeSection {
  me('我的', Icons.person_outline_rounded),
  profile('个人资料', Icons.person_outline_rounded),
  tasks('定时任务', Icons.schedule_rounded),
  connectors('连接的账号', Icons.hub_outlined),
  wallet('钱包', Icons.credit_card_rounded),
  computer('我的电脑', Icons.computer_rounded),
  usage('用量', Icons.data_usage_rounded),
  security('安全', Icons.shield_outlined),
  preferences('偏好设置', Icons.tune_rounded),
  feedback('反馈', Icons.feedback_outlined),
  about('关于', Icons.info_outline_rounded);

  const MeSection(this.label, this.icon);
  final String label;
  final IconData icon;
}

class MeEntry {
  const MeEntry(this.id, this.title, this.section, this.route, this.focus, this.keywords);
  final String id, title, route;
  final MeSection section;

  /// 进页后要滚到并闪一下的那一项（页面里 Spotlight(id: focus)）；null = 只到页面。
  final String? focus;
  final String keywords;

  /// 结果行副标题：这一项在哪（页面条目写“我的”或所属的收拢页，设置项写所在页面）。
  String get where => section.label;

  /// 点了去哪：带定位 id 时加 ?focus=。
  String get location => focus == null ? route : '$route?focus=$focus';
}

MeEntry _e(String id, String title, MeSection section, String route, String? focus, String keywords) => MeEntry(id, title, section, route, focus, keywords);

final meIndex = <MeEntry>[
  _e('profile', '个人资料', MeSection.me, '/me/profile', null, '资料 记忆 技能'),
  _e('memory', '记忆', MeSection.profile, '/me/memory', null, '记住 偏好 事实 人物 笔记 忘记'),
  _e('skills', '技能', MeSection.profile, '/me/skills', null, '方法 步骤 做事 规则'),
  _e('tasks', '定时任务', MeSection.me, '/me/tasks', null, '提醒 每天 定时 计划 自动 周期 面板 Home 闹钟'),
  _e('connectors', '连接的账号', MeSection.me, '/me/connectors', null, '连接器 授权 OAuth Google GitHub Gmail 邮箱 MCP 保险箱 密钥 API Key 环境变量 网站登录 账户'),
  _e('wallet', '钱包', MeSection.me, '/me/wallet', null, '付款 银行卡 信用卡 支付 结账 卡'),
  _e('computer', '我的电脑', MeSection.me, '/me/computer', null, '电脑 服务器 沙盒 容器 状态 内存 端口 程序 文件'),
  _e('pages', 'Pages', MeSection.computer, '/me/pages', null, '网页 页面 分享 链接 发布 下线'),
  _e('usage', '用量', MeSection.me, '/me/usage', null, '花费 费用 成本 账单 预算 token 钱 模型 自动选模型 按模型'),
  _e('security', '安全', MeSection.me, '/me/security', null, '密码 登录 验证 账号安全'),
  _e('preferences', '偏好设置', MeSection.me, '/me/preferences', null, '设置 外观 主题 语言'),
  _e('feedback', '反馈', MeSection.me, '/me/feedback', null, '问题 报告 bug 点踩 差评'),
  _e('about', '关于', MeSection.me, '/me/about', null, '版本 更新 服务器 介绍'),
  _e('appearance', '外观', MeSection.preferences, '/me/preferences', 'appearance', '深色 浅色 暗色 夜间 黑暗 主题 跟随系统 模式 dark light'),
  _e('solid', '减少透明度', MeSection.preferences, '/me/preferences', 'solid', '透明 毛玻璃 模糊 玻璃 对比度 不透明'),
  _e('avatar-color', '头像颜色', MeSection.preferences, '/me/preferences', 'avatar-color', '头像 颜色 色彩 换色'),
  _e('reply-language', '回复语言', MeSection.preferences, '/me/preferences', 'reply-language', '语言 中文 英文 English 日文 翻译'),
  _e('two-factor', '两步验证', MeSection.security, '/me/security', 'two-factor', '2FA 二次验证 双重验证 验证码 身份验证器 Authenticator'),
  _e('recovery', '恢复码', MeSection.security, '/me/security', 'two-factor', '备用码 恢复 两步验证 2FA'),
  _e('sessions', '登录设备', MeSection.security, '/me/security', 'sessions', '设备 退出其他设备 下线 会话 登录记录'),
  _e('version', '版本', MeSection.about, '/me/about', 'version', '版本号 更新 升级 请更新'),
  _e('browser-logins', '浏览器登录', MeSection.computer, '/me/computer', 'browser-logins', '网站 登录 cookie 浏览器 会话'),
  _e('host', '主机模式', MeSection.computer, '/me/computer', 'host', '服务器 主机 宿主机 权限 规则 root'),
  _e('disk', '磁盘', MeSection.computer, '/me/computer', 'disk', '空间 存储 清理 容量 装过的工具 文件'),
];

/// 按 [query] 筛选（与对话搜索同一套 searchTerms 分词）：每个词都要命中“标题 + 位置 + 关键词”；
/// 排序：标题以第一个词开头 > 标题包含任一词 > 只命中位置 / 关键词，同档保持索引顺序。空查询返回空。
List<MeEntry> searchMe(String query) {
  final terms = [for (final t in searchTerms(query)) t.toLowerCase()];
  if (terms.isEmpty) return const [];
  int rank(MeEntry e) {
    final t = e.title.toLowerCase();
    if (t.startsWith(terms.first)) return 0;
    if (terms.any(t.contains)) return 1;
    return 2;
  }

  final hits = [
    for (final e in meIndex)
      if (terms.every('${e.title} ${e.where} ${e.keywords}'.toLowerCase().contains)) e,
  ];
  final order = {for (var i = 0; i < hits.length; i++) hits[i]: i};
  hits.sort((a, b) {
    final r = rank(a).compareTo(rank(b));
    return r != 0 ? r : order[a]!.compareTo(order[b]!);
  });
  return hits;
}
