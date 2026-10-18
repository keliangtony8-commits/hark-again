// 主聊天的对话目录（v2.95 项目 = 一段对话后只剩主聊天用它）。
// 两种摆法同一份内容：手机上是聊天标签里的一页（v3.5.2 照 Hark：/chat/history，HistoryPage，聊天左上 ☰ 进来、
//   左上 + = 新对话；点开对话 = 退回聊天，系统返回键同样）；平板双栏时常驻左侧（docked，标题旁自带新对话钮）。
// 顶部搜索（标题 + 内容，防抖；点内容命中的结果 = 打开并定位到那条消息）；平时按 置顶/今天/昨天/… 分组；长按行 = 重命名 / 置顶 / 删除，左滑删除。
// 数据全走 ChatController，这里只管展示和交互。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/share.dart';
import '../../models/export.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../shell/shell_page.dart';
import 'chat_scaffold.dart' show backToDirectory, chatLeadTag;
import 'chat_controller.dart';
import 'conversation_files.dart';
import 'conversation_share.dart';
import 'history.dart';
import 'open_conversation.dart';

class HistoryPanel extends ConsumerStatefulWidget {
  const HistoryPanel({super.key, this.docked = false});

  /// true = 常驻侧栏；false = 对话目录页（选中对话后退回聊天）
  final bool docked;

  @override
  ConsumerState<HistoryPanel> createState() => _HistoryPanelState();
}

/// 手机上的对话目录页（/chat/history，聊天分支内）：顶栏照常，左上 + = 新对话（和聊天的 ☰ 同一颗钮，Hero morph）。
class HistoryPage extends ConsumerWidget {
  const HistoryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        backgroundColor: Colors.transparent,
        body: ShellPage(
          lead: MenuPlusHero(
            tag: chatLeadTag,
            plus: true,
            frame: (glyph) => GlassIconButton.glyph(
                glyph: glyph,
                tooltip: '新对话',
                onTap: () {
                  ref.read(chatProvider('').notifier).open(null);
                  backToDirectory(context, '/chat');
                }),
          ),
          child: const HistoryPanel(),
        ),
      );
}

class _HistoryPanelState extends ConsumerState<HistoryPanel> {
  final _query = TextEditingController();
  Timer? _debounce;
  int _seq = 0; // 只认最后一次搜索的结果，旧请求晚到直接丢弃
  List<ConversationSummary>? _results; // null = 没在搜索
  bool _loading = false;

  ChatController get _ctl => ref.read(chatProvider('').notifier);
  String get _q => _query.text.trim();

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _onQuery(String _) {
    _debounce?.cancel();
    setState(() {}); // 刷新清除按钮
    if (_q.isEmpty) {
      _seq++;
      setState(() => _results = null);
      return;
    }
    _debounce = Timer(Timing.searchDebounce, _search);
  }

  Future<void> _search() async {
    final seq = ++_seq;
    setState(() => _loading = true);
    try {
      final r = await _ctl.search(_q);
      if (mounted && seq == _seq) setState(() => _results = r);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted && seq == _seq) setState(() => _loading = false);
    }
  }

  void _clear() {
    _query.clear();
    _onQuery('');
  }

  /// 改动后：搜索视图也要跟着刷新，列表本身由 controller 刷新。
  Future<void> _run(Future<void> Function() action) async {
    try {
      await action();
      if (_results != null) await _search();
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    }
  }

  Future<void> _rename(ConversationSummary c) async {
    final v = await showFormSheet(context, title: '重命名对话', fields: [FieldSpec('title', '标题', initial: c.title)]);
    final title = v?['title'];
    if (title != null && title != c.title) await _run(() => _ctl.rename(c.id, title));
  }

  Future<bool> _confirmDelete(ConversationSummary c) =>
      confirmDanger(context, title: '删除「${c.title}」？', text: '对话里的消息会一起删除，不能恢复。');

  Future<void> _delete(ConversationSummary c) async {
    if (await _confirmDelete(c)) await _run(() => _ctl.remove(c.id));
  }

  /// 导出：拉全文 → 系统分享面板（存文件 / 发给别的 App）。不走 _run：导出不改列表，不必重搜。
  Future<void> _export(ConversationSummary c) async {
    final box = context.findRenderObject() as RenderBox?;
    final origin = box == null ? null : box.localToGlobal(Offset.zero) & box.size; // iPad 弹出框锚点
    try {
      final md = await _ctl.exportMarkdown(c.id, c.title);
      await shareTextFile(exportFileName(c.title), md, origin: origin);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } catch (_) {
      if (mounted) showToast(context, '这台设备打不开分享面板');
    }
  }

  void _menu(ConversationSummary c) => showActionSheet<void>(context, title: c.title, actions: [
        SheetAction(Icons.edit_outlined, '重命名', onTap: () => _rename(c)),
        SheetAction(c.pinned ? Icons.push_pin_outlined : Icons.push_pin_rounded, c.pinned ? '取消置顶' : '置顶',
            onTap: () => _run(() => _ctl.setPinned(c.id, !c.pinned))),
        SheetAction(Icons.folder_copy_outlined, '全部文件', onTap: () => showConversationFiles(context, c.id)),
        SheetAction(Icons.public_rounded, '分享为网页', onTap: () => showConversationShare(context, c.id)),
        SheetAction(Icons.ios_share_rounded, '导出 Markdown', onTap: () => _export(c)),
        SheetAction(Icons.delete_outline_rounded, '删除', danger: true, onTap: () => _delete(c)),
      ]);

  void _newChat() => _ctl.open(null);

  void _open(ConversationSummary c) {
    final pid = c.projectId;
    if (!widget.docked) backToDirectory(context, '/chat');
    if (pid != null) {
      openConversation(context, ref, c.id, focus: c.messageId, projectId: pid); // v3.2.1：命中项目那段 → 跳进项目
    } else {
      _ctl.open(c.id, focus: c.messageId); // 内容命中：打开后滚到那条消息
    }
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider(''));
    final p = context.palette;
    final searching = _results != null || (_q.isNotEmpty && _loading);
    // 自带 Material：常驻时它在聊天区 Scaffold 之外，搜索框和水波纹需要一张“纸”
    return Material(
      color: widget.docked ? p.bg : Colors.transparent, // 手机：透出外壳的壁纸
      child: SafeArea(
        right: false,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          // 双栏：标题 + 新对话；手机目录页没有大标题（照 Hark），新对话 = 左上 +（HistoryPage）
          if (widget.docked)
            Padding(
              padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x2, Sp.x1),
              child: Row(children: [
                Expanded(child: Text('历史对话', style: context.text.titleLarge)),
                IconButton(icon: const Icon(Icons.edit_square), tooltip: '新对话', color: p.text, onPressed: _newChat),
              ]),
            )
          else
            const SizedBox(height: Sp.x2),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x4),
            child: SearchField(controller: _query, hint: '搜索标题和内容', onChanged: _onQuery, onClear: _clear, loading: _loading),
          ),
          const SizedBox(height: Sp.x2),
          Expanded(
            child: AnimatedSwitcher(
              duration: Motion.base,
              switchInCurve: Motion.ease,
              child: searching ? _buildResults(chat.activeId) : _buildGroups(chat.conversations, chat.activeId),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _buildGroups(List<ConversationSummary> list, String? activeId) {
    if (list.isEmpty) {
      return const EmptyHint(key: ValueKey('empty'), icon: Icons.forum_outlined, title: '还没有对话', text: '聊过的内容会出现在这里');
    }
    var i = 0;
    return ListView(
      key: const ValueKey('groups'),
      padding: const EdgeInsets.fromLTRB(Sp.x2, 0, Sp.x2, Sp.x5),
      children: [
        for (final g in groupConversations(list)) ...[
          Padding(padding: const EdgeInsets.symmetric(horizontal: Sp.x2), child: SectionTitle(g.label)),
          for (final c in g.items) _row(c, activeId, i++),
        ],
      ],
    );
  }

  Widget _buildResults(String? activeId) {
    final r = _results;
    if (r == null) return const SizedBox.shrink(key: ValueKey('pending'));
    if (r.isEmpty) {
      return EmptyHint(key: const ValueKey('none'), icon: Icons.search_off_rounded, title: '没有找到', text: '未找到结果。搜索范围包括标题和聊天内容，多个词以空格分隔');
    }
    return ListView.builder(
      key: ValueKey('results:${_q.toLowerCase()}'),
      padding: const EdgeInsets.fromLTRB(Sp.x2, Sp.x2, Sp.x2, Sp.x5),
      itemCount: r.length,
      itemBuilder: (_, i) => _row(r[i], activeId, i, query: _q),
    );
  }

  Widget _row(ConversationSummary c, String? activeId, int i, {String query = ''}) => FadeSlideIn(
        key: ValueKey(c.id),
        delay: Motion.stagger(i),
        child: SwipeToDelete(
          id: c.id,
          confirm: () => _confirmDelete(c),
          onDelete: () => _run(() => _ctl.remove(c.id)),
          child: _ConversationRow(c: c, active: c.id == activeId, query: query, onTap: () => _open(c),
              onLongPress: c.projectId == null ? () => _menu(c) : null), // 项目那段归项目管：搜索结果里只能打开
        ),
      );
}

class _ConversationRow extends StatelessWidget {
  const _ConversationRow({required this.c, required this.active, required this.query, required this.onTap, required this.onLongPress});
  final ConversationSummary c;
  final bool active;
  final String query;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final titleStyle = context.text.titleMedium?.copyWith(fontWeight: active ? Weights.strong : null);
    final snippet = c.snippet;
    return AnimatedContainer(
      duration: Motion.base,
      curve: Motion.ease,
      decoration: BoxDecoration(color: active ? context.tileFill : null, borderRadius: BorderRadius.circular(Radii.inner)),
      child: InkWell(
        borderRadius: BorderRadius.circular(Radii.inner),
        onTap: onTap,
        onLongPress: onLongPress,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x3),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                HighlightText(c.title, query: query, style: titleStyle),
                if (c.projectName != null || snippet != null) ...[
                  const SizedBox(height: Sp.x1 / 2),
                  // v3.2.1：命中在哪个项目（= 网页 .conv-where），后面接摘录
                  HighlightText([?c.projectName, ?snippet].join(' · '),
                      query: query, style: context.text.bodySmall, maxLines: 2),
                ],
              ]),
            ),
            const SizedBox(width: Sp.x2),
            if (c.pinned) Padding(padding: const EdgeInsets.only(right: Sp.x1), child: Icon(Icons.push_pin_rounded, size: Fs.sm, color: p.text3)),
            Text(formatAgo(c.updatedAt), style: context.text.labelSmall?.copyWith(color: p.text3)),
          ]),
        ),
      ),
    );
  }
}
