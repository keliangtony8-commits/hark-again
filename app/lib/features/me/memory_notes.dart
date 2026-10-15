// 记忆笔记（v2.21）：一个主题一篇 Markdown —— 记忆页里的“主题笔记”一节 + 单篇的阅读 / 编辑页。
// 一句话记忆管“不吃香菜”，笔记管“妈妈：生日、开花店、上次聊到…”这种一串细节；聊天里助手自己建、自己补（memory_note 工具），
// 这里给用户看、改、删。阅读态渲染 Markdown；点“编辑”切到表单（名字 / 标题 / 类别 / 正文），只有真改了才能保存，
// 带着没保存的改动离开先确认（和技能编辑页同一套约定）。名字只填一段时按类别补文件夹（人 → people/），表单下面实时预览路径。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/memory_note.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/markdown.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/sub_page.dart';

/// 记忆页里的一节：标题（带篇数）+ 每篇一行（左滑删、点开阅读）。没有笔记且没在搜索时整节不出现（新建在页头“+”里）。
class MemoryNotesSection extends ConsumerWidget {
  const MemoryNotesSection({super.key, required this.query, this.from = 1});
  final String query;
  final int from; // 整页错峰起点

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final all = ref.watch(memoryNotesProvider).value ?? const <MemoryNote>[];
    final notes = filterNotes(all, query);
    return FadeSwitcher(
      alignment: AlignmentDirectional.topStart,
      child: notes.isEmpty
          ? const SizedBox(width: double.infinity, key: ValueKey('no-notes'))
          : Column(
              key: const ValueKey('notes'),
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SectionTitle('主题笔记', count: notes.length),
                ListGroup(children: [
                  for (final (i, n) in notes.indexed)
                    SwipeToDelete(
                      id: n.id,
                      confirm: () => confirmDanger(context, title: '删除笔记「${n.title}」？', text: '整篇内容都会删掉，我以后也看不到它。'),
                      onDelete: () => ref.read(memoryNotesProvider.notifier).remove(n.id),
                      child: FadeSlideIn(delay: Motion.stagger(i, from: from), child: _NoteRow(n: n, query: query)),
                    ),
                ]),
              ],
            ),
    );
  }
}

class _NoteRow extends StatelessWidget {
  const _NoteRow({required this.n, required this.query});
  final MemoryNote n;
  final String query;

  @override
  Widget build(BuildContext context) => ListRow(
        icon: noteKindIcon(n.kind),
        title: n.title,
        titleWidget: HighlightText(n.title, query: query.trim().split(RegExp(r'\s+')).first, style: context.text.bodyLarge),
        subtitle: noteSubtitle(n),
        semanticLabel: noteSemantics(n),
        onTap: () => context.push('/me/memory/notes/${n.id}'),
      );
}

/// 单篇笔记：id == 'new' 为新建（直接是表单），否则先阅读。
class MemoryNoteScreen extends ConsumerStatefulWidget {
  const MemoryNoteScreen({super.key, required this.id});
  final String id;

  @override
  ConsumerState<MemoryNoteScreen> createState() => _MemoryNoteScreenState();
}

class _MemoryNoteScreenState extends ConsumerState<MemoryNoteScreen> {
  late MemoryNote? _note = ref.read(memoryNotesProvider).value?.where((n) => n.id == widget.id).firstOrNull;
  late final _path = TextEditingController(text: _note?.path ?? '');
  late final _title = TextEditingController(text: _note?.title ?? '');
  late final _body = TextEditingController(text: _note?.body ?? '');
  late String _kind = _note?.kind ?? 'contact';
  late bool _editing = widget.id == 'new';
  late final _form = Listenable.merge([_path, _title, _body]);
  bool _busy = false;
  bool _saved = false;

  bool get _isNew => widget.id == 'new';

  bool get _dirty {
    final n = _note;
    return _path.text.trim() != (n?.path ?? '') ||
        _title.text.trim() != (n?.title ?? '') ||
        _body.text != (n?.body ?? '') ||
        (n != null && _kind != n.kind) ||
        (n == null && _body.text.isNotEmpty);
  }

  bool get _canSave => _editing && _dirty && _path.text.trim().isNotEmpty;

  @override
  void dispose() {
    _path.dispose();
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() op) async {
    setState(() => _busy = true);
    try {
      await op();
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() => _run(() async {
        final ctl = ref.read(memoryNotesProvider.notifier);
        final cur = _note;
        final title = _title.text.trim();
        if (cur == null) {
          await ctl.create({'path': _path.text.trim(), 'kind': _kind, 'body': _body.text, if (title.isNotEmpty) 'title': title});
          if (!mounted) return;
          _saved = true;
          context.pop();
          return;
        }
        await ctl.patch(cur.id, {
          if (_path.text.trim() != cur.path) 'path': _path.text.trim(),
          if (title != cur.title) 'title': title,
          if (_kind != cur.kind) 'kind': _kind,
          if (_body.text != cur.body) 'body': _body.text,
        });
        if (!mounted) return;
        final fresh = ref.read(memoryNotesProvider).value?.where((n) => n.id == cur.id).firstOrNull ?? cur;
        setState(() {
          _note = fresh;
          _editing = false;
        });
        _fill(fresh);
        showToast(context, '已保存');
      });

  void _fill(MemoryNote n) {
    _path.text = n.path;
    _title.text = n.title;
    _body.text = n.body;
    _kind = n.kind;
  }

  Future<void> _delete() async {
    final n = _note!;
    final ok = await confirmDanger(context, title: '删除笔记「${n.title}」？', text: '整篇内容都会删掉，我以后也看不到它。');
    if (!ok || !mounted) return;
    await _run(() async {
      await ref.read(memoryNotesProvider.notifier).remove(n.id);
      if (!mounted) return;
      _saved = true;
      context.pop();
    });
  }

  /// 编辑中取消：有改动先问；新建页取消 = 返回。
  Future<void> _cancel() async {
    if (_dirty && !await confirmDanger(context, title: '放弃没保存的改动？', text: '刚才改的内容不会保存。', action: '放弃')) return;
    if (!mounted) return;
    if (_isNew) {
      _saved = true;
      context.pop();
      return;
    }
    setState(() => _editing = false);
    _fill(_note!);
  }

  @override
  Widget build(BuildContext context) {
    // 列表刷新后（比如助手刚改了这篇）阅读态跟着换；编辑中不打断
    ref.listen(memoryNotesProvider, (_, next) {
      final live = next.value?.where((n) => n.id == widget.id).firstOrNull;
      if (_editing || live == null) return;
      setState(() => _note = live);
      _fill(live);
    });
    return ListenableBuilder(
      listenable: _form,
      builder: (context, _) {
        final n = _note;
        return PopScope(
          canPop: !_editing || !_dirty || _saved,
          onPopInvokedWithResult: (didPop, _) {
            if (!didPop) _cancel();
          },
          child: SubPage(
            title: Text(_isNew ? '新笔记' : (_editing ? '编辑笔记' : '笔记')),
            actions: [
              if (!_editing && n != null) ...[
                IconButton(icon: const Icon(Icons.delete_outline_rounded), tooltip: '删除笔记', onPressed: _busy ? null : _delete),
                Padding(
                  padding: const EdgeInsets.only(right: Sp.x2),
                  child: FilledButton.tonal(onPressed: _busy ? null : () => setState(() => _editing = true), child: const Text('编辑')),
                ),
              ],
              if (_editing) ...[
                TextButton(onPressed: _busy ? null : _cancel, child: const Text('取消')),
                Padding(
                  padding: const EdgeInsets.only(right: Sp.x2),
                  child: FilledButton(onPressed: _busy || !_canSave ? null : _save, child: const Text('保存')),
                ),
              ],
            ],
            body: !_isNew && n == null
                ? (ref.watch(memoryNotesProvider).isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : const EmptyHint(icon: Icons.description_outlined, title: '该笔记已删除', text: '可能已经被删掉或改了名字。'))
                : PageBody(children: [FadeSwitcher(child: _editing ? _editor(context) : _reading(context, n!))]),
          ),
        );
      },
    );
  }

  Widget _reading(BuildContext context, MemoryNote n) {
    final p = context.palette;
    return Column(
      key: const ValueKey('read'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FadeSlideIn(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(n.title, style: context.text.titleLarge),
              const SizedBox(height: Sp.x2),
              Wrap(spacing: Sp.x2, runSpacing: Sp.x1, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Pill(noteKindLabel(n.kind)),
                Text(n.path, style: context.text.bodySmall?.copyWith(color: p.text3)),
                if (n.updatedAt != null) Text('更新于 ${formatWhen(n.updatedAt)}', style: context.text.bodySmall?.copyWith(color: p.text3)),
              ]),
            ]),
          ),
        ),
        const SizedBox(height: Sp.x4),
        FadeSlideIn(
          delay: Motion.stagger(1),
          child: AppCard(
            child: n.body.trim().isEmpty
                ? Text('还没写内容。点“编辑”补上，或在聊天里告诉我。', style: context.text.bodySmall)
                : AppMarkdown(n.body),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x3, Sp.x1, 0),
          child: Text('聊天时我会自己补充这篇；说错了就在这里改。', style: context.text.bodySmall?.copyWith(color: p.text3)),
        ),
      ],
    );
  }

  Widget _editor(BuildContext context) {
    final p = context.palette;
    final preview = notePathPreview(_path.text, _kind);
    final showPreview = _path.text.trim().isNotEmpty && preview != _path.text.trim();
    return Column(
      key: const ValueKey('form'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('类别', style: context.text.labelSmall),
        const SizedBox(height: Sp.x2),
        Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
          for (final k in noteKinds.keys)
            ChoiceChip(
              avatar: Icon(noteKindIcon(k), size: 18),
              label: Text(noteKindLabel(k)),
              selected: k == _kind,
              showCheckmark: false,
              onSelected: (_) => setState(() => _kind = k),
            ),
        ]),
        const SizedBox(height: Sp.x4),
        TextField(
          controller: _path,
          decoration: const InputDecoration(labelText: '名字', hintText: '比如：妈妈、学校、考研计划'),
        ),
        // 只填名字时实时告诉用户会存成什么路径（人 → people/妈妈）
        SwapSwitcher(
          child: showPreview
              ? Padding(
                  key: ValueKey(preview),
                  padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x1, 0, 0),
                  child: Text('会存成 $preview', style: context.text.bodySmall?.copyWith(color: p.text3)),
                )
              : const SizedBox(width: double.infinity, key: ValueKey('no-preview')),
        ),
        const SizedBox(height: Sp.x3),
        TextField(controller: _title, decoration: const InputDecoration(labelText: '标题（可不填）', hintText: '默认和名字一样')),
        const SizedBox(height: Sp.x3),
        TextField(
          controller: _body,
          minLines: 12,
          maxLines: null,
          style: context.text.bodyMedium?.copyWith(fontFamily: 'monospace', fontSize: Fs.sm),
          decoration: const InputDecoration(
            labelText: '内容（Markdown）',
            alignLabelWithHint: true,
            hintText: '# 妈妈\n- 生日 6 月 1 日\n- 在老家开花店',
          ),
        ),
      ],
    );
  }
}
