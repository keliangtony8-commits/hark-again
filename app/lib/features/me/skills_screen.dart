// 技能：教我做事的固定方法（Markdown）。三种出身：
// - 内置原样：只读，可“复制一份来改”→ 变成同 id 的自定义版（顶替内置，模型只看到这一份）；
// - 自定义版：可改，“恢复默认”丢掉改动回到内置原文；不能删（内置总在）；
// - 自己写的：可改可删（左滑）。
// 每个技能都能停用（行尾开关 / 编辑页开关）：留在库里变淡，模型不再看到它。
// 正文可能很长，所以编辑是一整页，而不是底部弹层。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/markdown.dart';
import 'skill_library.dart';

class SkillsScreen extends ConsumerStatefulWidget {
  const SkillsScreen({super.key});

  @override
  ConsumerState<SkillsScreen> createState() => _SkillsScreenState();
}

class _SkillsScreenState extends ConsumerState<SkillsScreen> {
  final _query = TextEditingController();

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final skills = ref.watch(skillsProvider);
    return SubPage(
      title: const Text('技能'),
      actions: [IconButton(icon: const Icon(Icons.add_rounded), tooltip: '新技能', onPressed: () => context.push('/me/skills/new'))],
      body: AsyncBody<Skill>(
        value: skills,
        onRetry: () => ref.invalidate(skillsProvider),
        builder: (list) {
          final q = _query.text;
          final (:mine, :builtin) = filterSkills(list, q);
          final searching = q.trim().isNotEmpty;
          var i = 0; // 整页错峰序号：页头之后一行一行进
          Widget rows(List<Skill> items) => ListGroup(children: [for (final s in items) _SkillRow(s, delay: Motion.stagger(i++, from: 1))]);
          return PullRefresh(
            onRefresh: () => ref.read(skillsProvider.notifier).reload(),
            child: PageBody(children: [
              PageIntro(summary: skillSummary(list), line: '技能是我做某类事的固定方法。我会在合适的时候按它做；停用的留在库里，我看不到。'),
              if (list.length >= skillSearchFrom) ...[
                const SizedBox(height: Sp.x4),
                SearchField(controller: _query, hint: '搜索技能', onChanged: (_) => setState(() {}), onClear: () => setState(_query.clear)),
              ],
              if (searching && mine.isEmpty && builtin.isEmpty)
                EmptyHint(
                  icon: Icons.search_off_rounded,
                  title: '没有匹配的技能',
                  text: '换个词试试，名称、用途和步骤都会搜。',
                  action: TextButton(onPressed: () => setState(_query.clear), child: const Text('清除搜索')),
                ),
              if (!searching || mine.isNotEmpty) ...[
                SectionTitle('我的技能', count: mine.isEmpty ? null : mine.length),
                if (mine.isEmpty) const _Starters() else rows(mine),
              ],
              if (builtin.isNotEmpty) ...[
                SectionTitle('内置', count: builtin.length),
                rows(builtin),
              ],
            ]),
          );
        },
      ),
    );
  }
}

/// “我的技能”为空：起步模板（点了带内容进新建页，没保存前什么都不会存）。
class _Starters extends StatelessWidget {
  const _Starters();

  @override
  Widget build(BuildContext context) => StarterCard(
        title: '还没有自己写的',
        text: '在这里写，或在聊天里说“把刚才的做法存成技能”。也可以从一个开始改：',
        starters: [
          for (final st in skillStarters)
            PillButton(label: st.name, icon: Icons.add_rounded, onTap: () => context.push('/me/skills/new', extra: st)),
        ],
      );
}

/// 启用/停用一个技能：开关先动（乐观），服务器失败再拨回并提示。行和编辑页共用。
Future<Skill?> toggleSkill(BuildContext context, WidgetRef ref, Skill s, bool on) async {
  try {
    return await ref.read(skillsProvider.notifier).act(s.id, on ? 'enable' : 'disable');
  } on ApiError catch (e) {
    if (context.mounted) showToast(context, e.message);
    return null;
  }
}

class _SkillRow extends ConsumerStatefulWidget {
  const _SkillRow(this.s, {this.delay = Duration.zero});
  final Skill s;
  final Duration delay;

  @override
  ConsumerState<_SkillRow> createState() => _SkillRowState();
}

class _SkillRowState extends ConsumerState<_SkillRow> {
  bool? _pending; // 开关已拨、服务器还没回

  Future<void> _toggle(bool on) async {
    setState(() => _pending = on);
    await toggleSkill(context, ref, widget.s, on);
    if (mounted) setState(() => _pending = null);
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.s;
    final on = _pending ?? s.enabled;
    final row = FadeSlideIn(
      delay: widget.delay,
      child: RowTile(
          dimmed: !on,
          icon: s.builtin ? Icons.auto_awesome_outlined : Icons.edit_note_rounded,
          title: s.name,
          subtitle: s.description,
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            if (s.customized) const Padding(padding: EdgeInsets.only(right: Sp.x2), child: RowHint('已自定义')),
            Semantics(
              label: '启用「${s.name}」',
              child: Switch(value: on, onChanged: _pending == null ? _toggle : null),
            ),
          ]),
          onTap: () => context.push('/me/skills/${s.id}'),
        ),
    );
    if (s.fromBuiltin) return row;
    return SwipeToDelete(
      id: s.id,
      confirm: () => confirmDanger(context, title: '删除技能「${s.name}」？'),
      onDelete: () => ref.read(skillsProvider.notifier).remove(s.id),
      child: row,
    );
  }
}

/// 查看 / 编辑一个技能。id == 'new' 为新建（[starter] 不为空时带着模板内容）；
/// 内置原样是“阅读态”：名称、用途、渲染后的步骤，顶部可复制成自定义版；自定义版和自己写的是表单，
/// 步骤可在“编辑 / 预览”间切换。只有内容真的改了才能保存，带着没保存的改动离开要先确认。
class SkillEditorScreen extends ConsumerStatefulWidget {
  const SkillEditorScreen({super.key, required this.id, this.starter});
  final String id;
  final SkillStarter? starter;

  @override
  ConsumerState<SkillEditorScreen> createState() => _SkillEditorScreenState();
}

class _SkillEditorScreenState extends ConsumerState<SkillEditorScreen> {
  late Skill? _skill = ref.read(skillsProvider).value?.where((s) => s.id == widget.id).firstOrNull;
  late final _name = TextEditingController(text: _skill?.name ?? widget.starter?.name);
  late final _desc = TextEditingController(text: _skill?.description ?? widget.starter?.description);
  late final _body = TextEditingController(text: _skill?.body ?? widget.starter?.body);
  late final _form = Listenable.merge([_name, _desc, _body]);
  bool _busy = false;
  bool _preview = false;
  bool _saved = false;

  bool get _readOnly => _skill?.builtin ?? false;

  /// 和服务器上的版本（新建时是空白）比，有没有没保存的改动。模板带进来的内容算改动。
  bool get _dirty {
    final s = _skill;
    return _name.text != (s?.name ?? '') || _desc.text != (s?.description ?? '') || _body.text != (s?.body ?? '');
  }

  bool get _canSave => !_readOnly && _dirty && _name.text.trim().isNotEmpty && _desc.text.trim().isNotEmpty;

  @override
  void dispose() {
    _name.dispose();
    _desc.dispose();
    _body.dispose();
    super.dispose();
  }

  /// 统一的忙碌 / 报错外壳：同一时刻只做一件事，失败提示服务器的话。
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

  void _fill(Skill s) {
    _name.text = s.name;
    _desc.text = s.description;
    _body.text = s.body;
  }

  Future<void> _save() async {
    final body = {'name': _name.text.trim(), 'description': _desc.text.trim(), 'body': _body.text};
    final ctl = ref.read(skillsProvider.notifier);
    final cur = _skill;
    await _run(() async {
      cur == null ? await ctl.create(body) : await ctl.patch(cur.id, body);
      if (!mounted) return;
      _saved = true; // 已存：返回不再拦
      context.pop();
    });
  }

  /// 内置 → 自定义版：内容不变，只是变成可改（服务器已有自定义版时返回它，填回输入框）。
  Future<void> _customize() => _run(() async {
        final s = await ref.read(skillsProvider.notifier).act(_skill!.id, 'customize');
        if (!mounted) return;
        setState(() => _skill = s);
        _fill(s);
        showToast(context, '已复制，改完点保存');
      });

  Future<void> _toggle(bool on) => _run(() async {
        final s = await toggleSkill(context, ref, _skill!, on);
        if (s != null && mounted) setState(() => _skill = s); // 只换开关状态；输入框里没保存的改动不动，也照样算改动
      });

  Future<void> _reset() async {
    final ok = await confirmDanger(context,
        title: '恢复「${_skill!.name}」的默认做法？', text: '你的改动会丢掉，回到内置原文。', action: '恢复默认');
    if (!ok || !mounted) return;
    await _run(() async {
      final s = await ref.read(skillsProvider.notifier).act(_skill!.id, 'reset');
      if (!mounted) return;
      setState(() {
        _skill = s;
        _preview = false;
      });
      _fill(s);
      showToast(context, '已恢复默认');
    });
  }

  /// 带着没保存的改动返回：先问一句。
  Future<void> _maybeLeave() async {
    final ok = await confirmDanger(context, title: '放弃没保存的改动？', text: '刚才改的内容不会保存。', action: '放弃');
    if (ok && mounted) context.pop();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _form,
      builder: (context, _) {
        final s = _skill;
        return PopScope(
          canPop: _readOnly || !_dirty || _saved,
          onPopInvokedWithResult: (didPop, _) {
            if (!didPop) _maybeLeave();
          },
          child: SubPage(
            title: Text(s == null ? '新技能' : (_readOnly ? '内置技能' : '编辑技能')),
            actions: [
              if (s?.customized ?? false) TextButton(onPressed: _busy ? null : _reset, child: const Text('恢复默认')),
              if (!_readOnly)
                Padding(
                  padding: const EdgeInsets.only(right: Sp.x2),
                  child: FilledButton(onPressed: _busy || !_canSave ? null : _save, child: const Text('保存')),
                ),
            ],
            body: PageBody(children: [
              if (s != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: Sp.x3),
                  child: ListGroup(children: [
                    RowTile(
                      icon: s.enabled ? Icons.toggle_on_outlined : Icons.toggle_off_outlined,
                      title: '启用',
                      subtitle: s.enabled ? '我会在合适的时候按它做' : '已停用：我看不到它，也不会用它',
                      trailing: Semantics(
                        label: '启用「${s.name}」',
                        child: Switch(value: s.enabled, onChanged: _busy ? null : _toggle),
                      ),
                    ),
                  ]),
                ),
              SwapSwitcher(child: _Origin(key: ValueKey('${s?.builtin}-${s?.customized}'), skill: s, busy: _busy, onCustomize: _customize)),
              FadeSwitcher(child: _readOnly ? _reading(context, s!) : _editor(context)),
            ]),
          ),
        );
      },
    );
  }

  /// 内置原样：像读一篇说明，而不是一张填不了的表。
  Widget _reading(BuildContext context, Skill s) => Column(
        key: const ValueKey('read'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x1),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(s.name, style: context.text.titleLarge),
              const SizedBox(height: Sp.x1),
              Text(s.description, style: context.text.bodyMedium?.copyWith(color: context.palette.text2)),
            ]),
          ),
          const SectionTitle('步骤'),
          AppCard(child: s.body.trim().isEmpty ? Text('（没有写步骤）', style: context.text.bodySmall) : AppMarkdown(s.body)),
        ],
      );

  Widget _editor(BuildContext context) => Column(
        key: const ValueKey('form'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(controller: _name, decoration: const InputDecoration(labelText: '名称', hintText: '比如：写周报')),
          const SizedBox(height: Sp.x3),
          TextField(
            controller: _desc,
            maxLines: 2,
            decoration: const InputDecoration(labelText: '什么时候用', hintText: '用户让我写周报、总结一周进展时'),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x4, 0, Sp.x2),
            child: Row(children: [
              Expanded(child: Text('步骤（Markdown）', style: context.text.labelSmall)),
              SegmentedButton<bool>(
                showSelectedIcon: false,
                segments: const [ButtonSegment(value: false, label: Text('编辑')), ButtonSegment(value: true, label: Text('预览'))],
                selected: {_preview},
                onSelectionChanged: (v) => setState(() => _preview = v.first),
              ),
            ]),
          ),
          SwapSwitcher(
            child: _preview
                ? AppCard(
                    key: const ValueKey('preview'),
                    child: _body.text.trim().isEmpty
                        ? Text('还没有写步骤', style: context.text.bodySmall)
                        : AppMarkdown(_body.text),
                  )
                : TextField(
                    key: const ValueKey('edit'),
                    controller: _body,
                    minLines: 12,
                    maxLines: null,
                    style: context.text.bodyMedium?.copyWith(fontFamily: 'monospace', fontSize: Fs.sm),
                    decoration: const InputDecoration(
                        labelText: '步骤（Markdown）', alignLabelWithHint: true, hintText: '1. 先列出本周完成的事\n2. …'),
                  ),
          ),
        ],
      );
}

/// 编辑页顶部的出身说明：内置原样给“复制一份来改”，自定义版说明会顶替内置；自己写的不显示。
class _Origin extends StatelessWidget {
  const _Origin({super.key, required this.skill, required this.busy, required this.onCustomize});
  final Skill? skill;
  final bool busy;
  final VoidCallback onCustomize;

  @override
  Widget build(BuildContext context) {
    final s = skill;
    if (s == null || !s.fromBuiltin) return const SizedBox(width: double.infinity);
    return Padding(
      padding: const EdgeInsets.only(bottom: Sp.x3),
      child: AppCard(
        color: s.builtin ? null : context.tileFill,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            s.builtin ? '内置技能随服务器更新，不能直接改。想按自己的习惯来，就复制一份：之后我只按你的版本做。' : '这是内置技能的自定义版，我会按你改的做。不满意随时恢复默认。',
            style: context.text.bodySmall,
          ),
          if (s.builtin) ...[
            const SizedBox(height: Sp.x2),
            FilledButton.tonalIcon(
              onPressed: busy ? null : onCustomize,
              icon: const Icon(Icons.copy_rounded, size: 18),
              label: const Text('复制一份来改'),
            ),
          ],
        ]),
      ),
    );
  }
}
