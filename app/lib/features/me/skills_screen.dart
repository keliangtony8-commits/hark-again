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

class SkillsScreen extends ConsumerWidget {
  const SkillsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final skills = ref.watch(skillsProvider);
    return SubPage(
      title: const Text('技能'),
      floatingActionButton: FloatingActionButton(onPressed: () => context.push('/me/skills/new'), tooltip: '新技能', child: const Icon(Icons.add_rounded)),
      body: AsyncBody<Skill>(
        value: skills,
        onRetry: () => ref.invalidate(skillsProvider),
        builder: (list) {
          final mine = [for (final s in list) if (!s.fromBuiltin) s];
          final builtin = [for (final s in list) if (s.fromBuiltin) s];
          return PageBody(children: [
            const SectionTitle('我的技能'),
            if (mine.isEmpty)
              const AppCard(child: Text('还没有。可以在这里写，也可以在聊天里说“把刚才的做法存成技能”。'))
            else
              ListGroup(children: [for (final s in mine) _SkillRow(s)]),
            const SectionTitle('内置'),
            ListGroup(children: [for (final s in builtin) _SkillRow(s)]),
          ]);
        },
      ),
    );
  }
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
  const _SkillRow(this.s);
  final Skill s;

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
      child: Dimmed(
        dimmed: !on,
        child: RowTile(
          icon: s.builtin ? Icons.auto_awesome_outlined : Icons.edit_note_rounded,
          title: s.name,
          subtitle: s.description,
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            if (s.customized) const Pill('已自定义', strong: true),
            Semantics(
              label: '启用「${s.name}」',
              child: Switch(value: on, onChanged: _pending == null ? _toggle : null),
            ),
          ]),
          onTap: () => context.push('/me/skills/${s.id}'),
        ),
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

/// 查看 / 编辑一个技能。id == 'new' 为新建；内置原样只读，可复制成自定义版；自定义版可恢复默认。
class SkillEditorScreen extends ConsumerStatefulWidget {
  const SkillEditorScreen({super.key, required this.id});
  final String id;

  @override
  ConsumerState<SkillEditorScreen> createState() => _SkillEditorScreenState();
}

class _SkillEditorScreenState extends ConsumerState<SkillEditorScreen> {
  late Skill? _skill = ref.read(skillsProvider).value?.where((s) => s.id == widget.id).firstOrNull;
  late final _name = TextEditingController(text: _skill?.name);
  late final _desc = TextEditingController(text: _skill?.description);
  late final _body = TextEditingController(text: _skill?.body);
  bool _busy = false;

  bool get _readOnly => _skill?.builtin ?? false;

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
    if (_name.text.trim().isEmpty || _desc.text.trim().isEmpty) {
      showToast(context, '名称和“什么时候用”都要填');
      return;
    }
    final body = {'name': _name.text.trim(), 'description': _desc.text.trim(), 'body': _body.text};
    final ctl = ref.read(skillsProvider.notifier);
    final cur = _skill;
    await _run(() async {
      cur == null ? await ctl.create(body) : await ctl.patch(cur.id, body);
      if (mounted) context.pop();
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
        if (s != null && mounted) setState(() => _skill = s); // 只换开关状态，输入框里没保存的改动不动
      });

  Future<void> _reset() async {
    final ok = await confirmDanger(context,
        title: '恢复「${_skill!.name}」的默认做法？', text: '你的改动会丢掉，回到内置原文。', action: '恢复默认');
    if (!ok || !mounted) return;
    await _run(() async {
      final s = await ref.read(skillsProvider.notifier).act(_skill!.id, 'reset');
      if (!mounted) return;
      setState(() => _skill = s);
      _fill(s);
      showToast(context, '已恢复默认');
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = _skill;
    return SubPage(
      title: Text(s == null ? '新技能' : (_readOnly ? '内置技能' : '编辑技能')),
      actions: [
        if (s?.customized ?? false) TextButton(onPressed: _busy ? null : _reset, child: const Text('恢复默认')),
        if (!_readOnly)
          Padding(
            padding: const EdgeInsets.only(right: Sp.x2),
            child: FilledButton(onPressed: _busy ? null : _save, child: const Text('保存')),
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
        TextField(controller: _name, readOnly: _readOnly, decoration: const InputDecoration(labelText: '名称', hintText: '比如：写周报')),
        const SizedBox(height: Sp.x3),
        TextField(
          controller: _desc,
          readOnly: _readOnly,
          maxLines: 2,
          decoration: const InputDecoration(labelText: '什么时候用', hintText: '用户让我写周报、总结一周进展时'),
        ),
        const SizedBox(height: Sp.x3),
        TextField(
          controller: _body,
          readOnly: _readOnly,
          minLines: 12,
          maxLines: null,
          style: context.text.bodyMedium?.copyWith(fontFamily: 'monospace', fontSize: Fs.sm),
          decoration: const InputDecoration(labelText: '步骤（Markdown）', alignLabelWithHint: true, hintText: '1. 先列出本周完成的事\n2. …'),
        ),
      ]),
    );
  }
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
