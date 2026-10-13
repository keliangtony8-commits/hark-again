// 记忆：看、找、改、删我记住的事。
// 版式自上而下（与保险箱/技能页同一套）：页头摘要 + 说明 →（空时起步卡）→“我对你的了解”概括卡 → 搜索框（≥7 条）→ 分类筛选条
// → 主题笔记（v2.21，memory_notes.dart：一个主题一篇 Markdown，同一个搜索框也筛它）→ 按分类分组（带数量）。
// 筛选纯客户端（models/memory.dart、models/memory_note.dart），列表来自 memoriesProvider / memoryNotesProvider；
// 左滑删除，点击编辑（内容 + 分类），右上角“+”选一句话记忆或主题笔记。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/memory.dart';
import '../../models/memory_note.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'memory_digest.dart';
import 'memory_notes.dart';

class MemoryScreen extends ConsumerStatefulWidget {
  const MemoryScreen({super.key});

  @override
  ConsumerState<MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends ConsumerState<MemoryScreen> {
  final _query = TextEditingController();
  String? _category; // null = 全部

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  void _clearFilters() => setState(() {
        _query.clear();
        _category = null;
      });

  @override
  Widget build(BuildContext context) {
    return SubPage(
      title: const Text('记忆'),
      actions: [
        IconButton(icon: const Icon(Icons.add_rounded), tooltip: '新增', onPressed: () => _addAny(context)),
      ],
      body: AsyncBody<MemoryItem>(
        value: ref.watch(memoriesProvider),
        onRetry: () => ref.invalidate(memoriesProvider),
        builder: (list) {
          final counts = categoryCounts(list);
          final category = counts.any((c) => c.$1 == _category) ? _category : null; // 选中的分类被删空了就回到全部
          final groups = filterMemories(list, query: _query.text, category: category);
          final notes = ref.watch(memoryNotesProvider).value ?? const [];
          final noteHits = filterNotes(notes, _query.text);
          // 笔记也算进门槛：搜着搜着删到门槛下也别把框收走
          final searchable = list.length + notes.length >= memorySearchFrom || _query.text.isNotEmpty;
          final empty = list.isEmpty && notes.isEmpty;
          var i = 0; // 整页错峰序号（Motion.stagger 自己封顶，长列表不会越排越慢）
          return PullRefresh(
            onRefresh: () => Future.wait([ref.read(memoriesProvider.notifier).reload(), ref.read(memoryNotesProvider.notifier).reload()]),
            child: PageBody(children: [
              PageIntro(summary: memorySummary(list, notes: notes.length), line: '每次对话我都会参考这些。聊天时我会自己记，说错了就改，不想让我记的直接删。'),
              if (empty)
                Padding(
                  padding: const EdgeInsets.only(top: Sp.x4),
                  child: StarterCard(
                    title: '还没有记忆',
                    text: '聊天时说“记住我不吃辣”我就会记下来，也可以先告诉我几件事。',
                    starters: [
                      for (final s in memoryStarters)
                        PillButton(label: s.label, icon: Icons.add_rounded, onTap: () => _add(context, content: s.content, category: s.category)),
                      PillButton(label: '记一个人', icon: Icons.person_add_alt_outlined, onTap: () => context.push('/me/memory/notes/new')),
                    ],
                  ),
                )
              else ...[
                const SizedBox(height: Sp.x4),
                const MemoryDigestCard(),
                if (searchable) ...[
                  const SizedBox(height: Sp.x4),
                  SearchField(controller: _query, hint: '搜索记忆', onChanged: (_) => setState(() {}), onClear: () => setState(_query.clear)),
                ],
                if (counts.length > 1) ...[
                  const SizedBox(height: Sp.x3),
                  _CategoryBar(counts: counts, total: list.length, selected: category, onSelect: (c) => setState(() => _category = c)),
                ],
                if (category == null) MemoryNotesSection(query: _query.text),
                if (groups.isEmpty && (noteHits.isEmpty || category != null) && !(list.isEmpty && _query.text.isEmpty))
                  EmptyHint(
                    icon: Icons.search_off_rounded,
                    title: '没有匹配的记忆',
                    text: '换个词，或者看看全部分类。',
                    action: TextButton(onPressed: _clearFilters, child: const Text('清除筛选')),
                  ),
                for (final (cat, items) in groups) ...[
                  SectionTitle(categoryLabel(cat), count: items.length),
                  ListGroup(children: [
                    for (final m in items)
                      SwipeToDelete(
                        id: m.id,
                        onDelete: () => ref.read(memoriesProvider.notifier).remove(m.id),
                        child: FadeSlideIn(
                          delay: Motion.stagger(i++, from: 1),
                          child: _MemoryRow(m: m, query: _query.text, onTap: () => _edit(context, m)),
                        ),
                      ),
                  ]),
                ],
              ],
            ]),
          );
        },
      ),
    );
  }

  /// 页头“+”：一句话记忆（底部表单）还是主题笔记（整页编辑）。
  Future<void> _addAny(BuildContext context) async {
    final pick = await showActionSheet<String>(context, title: '新增', actions: const [
      SheetAction(Icons.short_text_rounded, '一句话记忆', value: 'memory', subtitle: '一条偏好或事实，比如“我对花生过敏”'),
      SheetAction(Icons.description_outlined, '主题笔记', value: 'note', subtitle: '关于一个人、地方或项目的一串细节'),
    ]);
    if (!context.mounted) return;
    if (pick == 'note') {
      context.push('/me/memory/notes/new');
    } else if (pick == 'memory') {
      await _add(context);
    }
  }

  /// 新增一条：页头 + 用当前分类；起步按钮带着例句和分类打开同一张表。
  Future<void> _add(BuildContext context, {String? content, String? category}) async {
    final cat = ValueNotifier(category ?? _category ?? 'general');
    final v = await showFormSheet(context,
        title: '新增记忆',
        subtitle: '一条一件事，比如“我对花生过敏”。',
        fields: [FieldSpec('content', '内容', lines: 3, initial: content ?? '')],
        submit: '记住',
        extra: _CategoryPicker(value: cat));
    final text = v?['content'];
    if (text != null && text.isNotEmpty) await ref.read(memoriesProvider.notifier).create({'content': text, 'category': cat.value});
    cat.dispose();
  }

  Future<void> _edit(BuildContext context, MemoryItem m) async {
    final cat = ValueNotifier(m.category);
    final v = await showFormSheet(context,
        title: '修改记忆', fields: [FieldSpec('content', '内容', initial: m.content, lines: 3)], extra: _CategoryPicker(value: cat));
    final text = v?['content'];
    final body = <String, dynamic>{
      if (text != null && text != m.content) 'content': text,
      if (v != null && cat.value != m.category) 'category': cat.value,
    };
    if (body.isNotEmpty) await ref.read(memoriesProvider.notifier).patch(m.id, body);
    cat.dispose();
  }
}

class _MemoryRow extends StatelessWidget {
  const _MemoryRow({required this.m, required this.query, required this.onTap});
  final MemoryItem m;
  final String query;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(Radii.md),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: A11y.minTap),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                // 搜索时每个词都可能命中，高亮整串里的第一个词就够指路
                HighlightText(m.content, query: query.trim().split(RegExp(r'\s+')).first, style: context.text.bodyLarge, maxLines: 3),
                if (m.updatedAt != null) ...[
                  const SizedBox(height: Sp.x1),
                  Text(formatWhen(m.updatedAt), style: context.text.bodySmall?.copyWith(color: p.text3)),
                ],
              ]),
            ),
            Icon(Icons.chevron_right_rounded, color: p.text3),
          ]),
        ),
      ),
    );
  }
}

/// 横向滚动的分类筛选条：全部 + 每个分类（带条数）。
class _CategoryBar extends StatelessWidget {
  const _CategoryBar({required this.counts, required this.total, required this.selected, required this.onSelect});
  final List<(String, int)> counts;
  final int total;
  final String? selected;
  final ValueChanged<String?> onSelect;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          _chip(context, '全部 $total', selected == null, () => onSelect(null)),
          for (final (c, n) in counts) _chip(context, '${categoryLabel(c)} $n', selected == c, () => onSelect(selected == c ? null : c)),
        ]),
      );

  Widget _chip(BuildContext context, String label, bool on, VoidCallback onTap) => Padding(
        padding: const EdgeInsets.only(right: Sp.x2),
        child: ChoiceChip(label: Text(label), selected: on, onSelected: (_) => onTap(), showCheckmark: false),
      );
}

/// 表单里的分类选择（新增/修改共用），状态在调用方的 ValueNotifier 里。
class _CategoryPicker extends StatelessWidget {
  const _CategoryPicker({required this.value});
  final ValueNotifier<String> value;

  @override
  Widget build(BuildContext context) => ValueListenableBuilder(
        valueListenable: value,
        builder: (context, current, _) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('分类', style: context.text.labelSmall),
          const SizedBox(height: Sp.x2),
          Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
            for (final c in {...memoryCategories.keys, current})
              ChoiceChip(label: Text(categoryLabel(c)), selected: c == current, onSelected: (_) => value.value = c, showCheckmark: false),
          ]),
        ]),
      );
}
