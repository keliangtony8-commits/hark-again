// v2.92 §P 改称呼 / 助手名 / 头像：“我的”页点名字或头像打开（规则在后端 app/identity.py，数据只走 profileProvider）。
// 版式同 showFormSheet：标题 → 大头像（点开动作单：相册 / 拍照 / 移除）→ 两个输入框 → 保存。头像选了立刻上传，名字点保存才送。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/media.dart';
import '../../core/profile.dart';
import '../../theme/app_theme.dart';
import '../../theme/look.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

Future<void> showProfileSheet(BuildContext context) => showAppSheet<void>(context, title: '个人资料', builder: (_) => const ProfileSheet());

class ProfileSheet extends ConsumerStatefulWidget {
  const ProfileSheet({super.key});

  @override
  ConsumerState<ProfileSheet> createState() => _ProfileSheetState();
}

class _ProfileSheetState extends ConsumerState<ProfileSheet> {
  late final Profile? _start = ref.read(profileProvider).value;
  late final _name = TextEditingController(text: _start?.displayName ?? '');
  late final _assistant = TextEditingController(text: _start?.assistantName ?? '');
  bool _saving = false, _uploading = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _assistant.dispose();
    super.dispose();
  }

  Future<void> _pickPhoto() async {
    final p = ref.read(profileProvider).value;
    final choice = await showActionSheet<String>(context, title: '头像', actions: [
      const SheetAction(Icons.photo_library_outlined, '从相册选择', value: 'gallery'),
      const SheetAction(Icons.photo_camera_outlined, '拍照', value: 'camera'),
      if (p?.avatar != null) const SheetAction(Icons.delete_outline_rounded, '移除头像', value: 'clear', danger: true),
    ]);
    if (choice == null || !mounted) return;
    final notifier = ref.read(profileProvider.notifier);
    setState(() => _uploading = true);
    try {
      if (choice == 'clear') {
        await notifier.clearAvatar();
      } else {
        final f = await ref.read(mediaProvider).pickAvatar(choice == 'camera' ? PickSource.camera : PickSource.gallery);
        if (f != null) await notifier.setAvatar(f);
      }
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _save() async {
    final changes = <String, String>{
      if (_name.text.trim() != (_start?.displayName ?? '')) 'display_name': _name.text.trim(),
      if (_assistant.text.trim() != (_start?.assistantName ?? '')) 'assistant_name': _assistant.text.trim(),
    };
    if (changes.isEmpty) {
      Navigator.pop(context);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(profileProvider.notifier).rename(changes);
      if (mounted) Navigator.pop(context);
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = ref.watch(profileProvider).value ?? _start;
    final color = ref.watch(lookProvider.select((l) => l.value?.avatar));
    final photo = p?.avatar;
    return Padding(
      padding: EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, MediaQuery.viewInsetsOf(context).bottom + Sp.x5),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Center(
            child: Stack(alignment: Alignment.center, children: [
              Avatar(
                key: const Key('profile-avatar'),
                initial: p?.initial ?? '我',
                image: photo == null ? null : ref.read(apiProvider).fileUrl(photo),
                color: color,
                size: Layout.avatarLarge,
                tooltip: '更换头像',
                onTap: _uploading ? null : _pickPhoto,
              ),
              if (_uploading) const IgnorePointer(child: TypingDots()),
            ]),
          ),
          const SizedBox(height: Sp.x2),
          Center(child: Text('点头像更换', style: context.text.bodySmall?.copyWith(color: context.palette.text3))),
          const SizedBox(height: Sp.x3),
          TextField(
            key: const Key('profile-name'),
            controller: _name,
            maxLength: 20,
            decoration: InputDecoration(labelText: '我该如何称呼你', hintText: p?.username, counterText: ''),
          ),
          const SizedBox(height: Sp.x3),
          TextField(
            key: const Key('profile-assistant'),
            controller: _assistant,
            maxLength: 20,
            decoration: InputDecoration(labelText: '助手的名字', hintText: p?.assistantDefault ?? 'Toyuis', helperText: '留空就叫 ${p?.assistantDefault ?? 'Toyuis'}', counterText: ''),
          ),
          if (_error != null) ...[
            const SizedBox(height: Sp.x2),
            Text(_error!, style: context.text.bodySmall?.copyWith(color: context.palette.danger)),
          ],
          const SizedBox(height: Sp.x4),
          FilledButton(key: const Key('profile-save'), onPressed: _saving ? null : _save, child: const Text('保存')),
        ]),
      ),
    );
  }
}
