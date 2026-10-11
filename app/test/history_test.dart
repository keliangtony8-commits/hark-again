import 'package:assistant/features/chat/history.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('历史分组：置顶优先，其余按日期，空组不出现', () {
    final now = DateTime(2026, 10, 11, 9);
    ConversationSummary c(String id, DateTime t, {bool pinned = false}) => ConversationSummary(id: id, title: id, updatedAt: t, pinned: pinned);
    final groups = groupConversations([
      c('p', DateTime(2025, 1, 1), pinned: true),
      c('today', DateTime(2026, 10, 11, 0, 5)),
      c('yday', DateTime(2026, 10, 10, 23, 59)),
      c('week', DateTime(2026, 10, 6)),
      c('old', DateTime(2026, 9, 1)),
    ], now: now);
    expect([for (final g in groups) g.label], ['置顶', '今天', '昨天', '7 天内', '更早']);
    expect([for (final g in groups) g.items.single.id], ['p', 'today', 'yday', 'week', 'old']);
    expect(groupConversations([c('a', now)], now: now).single.label, '今天');
  });

  test('对话摘要解析 pinned / snippet', () {
    final s = ConversationSummary.fromJson({'id': '1', 'title': 't', 'pinned': true, 'snippet': '…猫…', 'updated_at': '2026-10-11T00:00:00+00:00'});
    expect(s.pinned, isTrue);
    expect(s.snippet, '…猫…');
    expect(ConversationSummary.fromJson({'id': '2'}).pinned, isFalse);
  });

  test('搜索高亮：不分大小写，多处命中', () {
    const hit = TextStyle(fontWeight: FontWeight.w700);
    final spans = highlightSpans('Cat and cat', 'CAT', hit);
    expect([for (final s in spans) s.text], ['Cat', ' and ', 'cat']);
    expect([for (final s in spans) s.style == hit], [true, false, true]);
    expect(highlightSpans('abc', '  ', hit).single.text, 'abc');
  });
}
