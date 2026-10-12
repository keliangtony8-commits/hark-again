// 输入框：圆角胶囊 + 附件托盘 + 录音态。
// 三种形态平滑切换：空 → 显示麦克风；有字/附件 → 发送键；录音中 → 红点计时 + 完成/取消。
// 生成中右侧圆钮换成“停止”（onStop 为 null = 已请求停止，置灰等服务器收尾）；输入框照常可打字，说完再发。
// 编辑态（editing 不为 null）：顶部“编辑消息”条 + 原文字填进输入框；原来的附件随消息保留，
//   这里的附件托盘和草稿先收起，退出编辑（发出或取消）后原样回来。
// accessory：右侧圆钮左边的插槽（聊天页放模型钮，Composer 不认识它）。
// 设计 v2：整条是浮在内容上的玻璃胶囊（真模糊，外面用 ui/kit.dart FloatingFooter 让位）；
//   leading：胶囊左边、胶囊外的圆钮位（一级页面聚焦时的“收起”），出现/消失用 RiseSwitcher 横向长出；
//   focusNode：外面要知道聚焦状态时传进来（LaunchComposer 用它开关整页磨砂）。
// workspace：这段对话的工作区（core/workspace.dart；项目 = 项目文件，主聊天 = 我的文件）。“添加附件”多一个从它选
// （features/projects pickProjectFiles，不上传，只带引用）；null = 没有这个来源（如首页的快捷输入框）。
// 打 $ → 顶部列出启用的技能，点一下补成 `$id `（服务器 app/skill_mentions.py 把正文给模型）。
// 打 @ → 顶部列出工作区文件（features/chat/mentions.dart），点一下补成 `@路径 `；服务器发出时解析成引用（app/file_mentions.py）。
// 上传、转写走 core/media.dart；这里只管交互状态。
import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/media.dart';
import '../../models/block.dart';
import '../../models/message.dart';
import '../../models/shell.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../core/workspace.dart';
import '../../core/resource.dart';
import '../projects/project_files_sheet.dart';
import 'attachment_tray.dart';
import 'mentions.dart';

/// 正在编辑的那条用户消息。hasFiles：带附件的消息文字清空也能发（只剩附件）。
class EditDraft {
  const EditDraft(this.id, this.text, {this.hasFiles = false});
  EditDraft.of(Message m) : this(m.id, plainText(m.blocks), hasFiles: m.blocks.any((b) => b is FileBlock));
  final String id;
  final String text;
  final bool hasFiles;
}

/// 生成中输入框的提示：这时发出去的话会并进正在进行的回答（后端 steering）。
const steerHint = '补充或纠正，会并进这次回答';

class Composer extends ConsumerStatefulWidget {
  const Composer(
      {super.key,
      required this.onSend,
      required this.busy,
      this.streaming = false,
      this.canSteer = false,
      this.onStop,
      this.editing,
      this.onCancelEdit,
      this.accessory,
      this.hint = '给助手发消息',
      this.leading,
      this.focusNode,
      this.workspace});
  final void Function(String text, List<FileBlock> files) onSend;
  final bool busy;
  final bool streaming;

  /// 生成中可以补一句给正在进行的这一轮（ChatState.canSteer）：有字时停止钮换成“补充”钮。
  final bool canSteer;
  final VoidCallback? onStop;
  final EditDraft? editing;
  final VoidCallback? onCancelEdit;

  /// 右侧圆钮左边的小部件（模型钮）；录音态不显示。
  final Widget? accessory;
  final String hint;
  final Widget? leading;
  final FocusNode? focusNode;

  /// 工作区 id（null = 没有“从工作区引用文件”这个来源）。
  final String? workspace;

  @override
  ConsumerState<Composer> createState() => _ComposerState();
}

enum _Voice { idle, recording, transcribing }

/// 附件来源：本机三种（交给 core/media.dart）+ 项目文件引用。
enum _From {
  gallery(PickSource.gallery),
  camera(PickSource.camera),
  file(PickSource.file),
  project(null);

  const _From(this.device);
  final PickSource? device;
}

class _ComposerState extends ConsumerState<Composer> {
  final _c = TextEditingController();
  FocusNode? _ownFocus;
  FocusNode get _focus => widget.focusNode ?? (_ownFocus ??= FocusNode());
  final _attachments = <Attachment>[];
  String? _stash; // 进入编辑前输入框里的草稿
  var _voice = _Voice.idle;
  Timer? _ticker;
  int _seconds = 0;
  MentionQuery? _mention; // 光标前正在打的 @xxx（没有工作区 / 在打命令时不算）

  Media get _media => ref.read(mediaProvider);

  @override
  void initState() {
    super.initState();
    _c.addListener(_trackMention); // 光标挪动（不改字）也要更新
  }

  void _trackMention() {
    final sel = _c.selection;
    // $技能 哪儿都能用；@文件 要有工作区；!命令 里的 @ / $ 是给电脑的，都不弹
    final m = !sel.isValid || !sel.isCollapsed || shellCommandOf(_c.text) != null
        ? null
        : mentionAt(_c.text, sel.baseOffset, sigils: {skillSigil, if (widget.workspace != null) fileSigil});
    if (m != _mention && mounted) setState(() => _mention = m);
  }

  void _pickMention(String key) {
    final m = _mention;
    if (m == null) return;
    final (text, caret) = applyMention(_c.text, m, key);
    _c.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: caret));
    _focus.requestFocus();
  }

  @override
  void dispose() {
    _c.removeListener(_trackMention);
    _c.dispose();
    _ownFocus?.dispose();
    _ticker?.cancel();
    super.dispose();
  }

  @override
  void didUpdateWidget(Composer old) {
    super.didUpdateWidget(old);
    final e = widget.editing;
    if (e?.id == old.editing?.id) return;
    if (old.editing == null) _stash = _c.text; // 进入编辑：收起草稿
    _setText(e?.text ?? _stash ?? '');
    if (e == null) _stash = null;
    if (e != null) _focus.requestFocus();
  }

  void _setText(String t) {
    _c.text = t;
    _c.selection = TextSelection.collapsed(offset: t.length);
  }

  bool get _editing => widget.editing != null;
  bool get _uploading => !_editing && _attachments.any((a) => a.uploading);
  bool get _hasContent =>
      _c.text.trim().isNotEmpty || (_editing ? widget.editing!.hasFiles : _attachments.any((a) => a.file != null));
  bool get _canSend => (!widget.busy || _steering) && !_uploading && _hasContent;

  /// 生成中打了纯文字：发出去是补充给这一轮（不带附件 / 不是命令 / 不在编辑），否则仍只能停止。
  bool get _steering =>
      widget.streaming && widget.canSteer && !_editing && _attachments.isEmpty && !_shell && _c.text.trim().isNotEmpty;

  /// 整条是 `!命令`（且没带附件）：发出去不问助手，直接在这段对话的电脑上跑（后端 user_shell）。
  bool get _shell => !_editing && _attachments.isEmpty && shellCommandOf(_c.text) != null;

  void _send() {
    if (!_canSend) return;
    if (_editing) {
      widget.onSend(_c.text, const []); // 草稿由 didUpdateWidget 在退出编辑时放回
      return;
    }
    widget.onSend(_c.text, [for (final a in _attachments) if (a.file != null) a.file!]);
    _c.clear();
    setState(_attachments.clear);
  }

  // ---- 附件 ----
  Future<void> _pick() async {
    final pid = widget.workspace;
    final source = await showAppSheet<_From>(
      context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x4),
          child: Row(children: [
            for (final (src, icon, label) in [
              (_From.gallery, Icons.photo_library_outlined, '相册'),
              (_From.camera, Icons.photo_camera_outlined, '拍照'),
              (_From.file, Icons.insert_drive_file_outlined, '文件'),
              if (pid != null) (_From.project, Icons.folder_outlined, workspaceFilesTitle(pid)),
            ])
              Expanded(
                child: Pressable(
                  onTap: () => Navigator.pop(ctx, src),
                  semanticLabel: label,
                  child: Column(children: [
                    Container(
                      width: Sp.x7 + Sp.x2,
                      height: Sp.x7 + Sp.x2,
                      decoration: BoxDecoration(color: ctx.tileFill, shape: BoxShape.circle),
                      child: IconBadge(icon),
                    ),
                    const SizedBox(height: Sp.x2),
                    Text(label, style: ctx.text.bodyMedium),
                  ]),
                ),
              ),
          ]),
        ),
      ),
    );
    if (source == null || !mounted) return;
    if (source == _From.project) return _pickProject(pid!);
    final files = await _media.pick(source.device!);
    for (final f in files) {
      _upload(f);
    }
  }

  Future<void> _pickProject(String pid) async {
    final taken = {for (final a in _attachments) if (a.fromProject) a.file!.id};
    final room = maxMessageFiles - _attachments.length;
    if (room <= 0) return showToast(context, '一条消息最多带 $maxMessageFiles 个文件');
    final picked = await pickProjectFiles(context, pid, taken: taken, room: room);
    if (picked == null || picked.isEmpty || !mounted) return;
    setState(() => _attachments.addAll(picked.map(Attachment.ref)));
    _focus.requestFocus();
  }

  Future<void> _upload(File f) async {
    final a = Attachment(name: f.uri.pathSegments.last, local: f);
    setState(() => _attachments.add(a));
    try {
      final block = await _media.upload(f);
      if (mounted) setState(() => a.file = block);
    } catch (e) {
      if (!mounted) return;
      setState(() => _attachments.remove(a));
      showToast(context, '上传失败：${e is ApiError ? e.message : e}');
    }
  }

  // ---- 语音 ----
  Future<void> _startVoice() async {
    if (!await _media.startRecording()) {
      if (mounted) showToast(context, '需要麦克风权限');
      return;
    }
    setState(() {
      _voice = _Voice.recording;
      _seconds = 0;
    });
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => setState(() => _seconds++));
  }

  Future<void> _finishVoice({required bool keep}) async {
    _ticker?.cancel();
    if (!keep) {
      await _media.cancelRecording();
      setState(() => _voice = _Voice.idle);
      return;
    }
    setState(() => _voice = _Voice.transcribing);
    try {
      final text = await _media.stopAndTranscribe();
      if (text.isNotEmpty) {
        // 先回填让用户改，不自动发送：识别错了也来得及修
        _c.text = _c.text.isEmpty ? text : '${_c.text} $text';
        _c.selection = TextSelection.collapsed(offset: _c.text.length);
      }
    } catch (e) {
      if (mounted) showToast(context, e is ApiError ? e.message : '没听清，再试一次');
    } finally {
      if (mounted) setState(() => _voice = _Voice.idle);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x3, Sp.x2, Sp.x3, Sp.x3),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: Layout.contentMax),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              RiseSwitcher(
                axis: Axis.horizontal,
                child: widget.leading == null
                    ? null
                    : Padding(key: const ValueKey('leading'), padding: const EdgeInsets.only(right: Sp.x2), child: widget.leading),
              ),
              Expanded(child: _capsule(p)),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _capsule(Palette p) => GlassSurface(
        blur: true,
        borderColor: _voice == _Voice.recording ? p.danger.withValues(alpha: 0.5) : null,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          AnimatedSize(
            duration: context.motion(Motion.base),
            curve: Motion.ease,
            alignment: Alignment.topCenter,
            child: _mention != null
                ? _mentionList()
                : _editing
                ? _EditBar(onCancel: widget.onCancelEdit)
                : _shell
                ? const _ShellBar(key: ValueKey('shell'))
                : const SizedBox(width: double.infinity),
          ),
          AttachmentTray(items: _editing ? const [] : _attachments, onRemove: (a) => setState(() => _attachments.remove(a))),
          AnimatedSwitcher(
            duration: Motion.base,
            switchInCurve: Motion.ease,
            transitionBuilder: (child, anim) => FadeTransition(opacity: anim, child: SizeTransition(sizeFactor: anim, alignment: Alignment.bottomCenter, child: child)),
            child: _voice == _Voice.idle ? _inputRow(p) : _voiceRow(p),
          ),
        ]),
      );

  Widget _mentionList() {
    final m = _mention!;
    if (m.isSkill) {
      final skills = ref.watch(skillsProvider);
      return MentionList(
        key: const ValueKey('mention-skill'),
        items: [for (final s in rankSkills(skills.value ?? const [], m.query)) MentionItem.skill(s)],
        empty: skills.isLoading && !skills.hasValue ? '正在读技能…' : '没有对得上的技能 · 可以在“我的 › 技能”里新建',
        emptyIcon: Icons.auto_awesome_rounded,
        onPick: _pickMention,
      );
    }
    final files = ref.watch(projectFilesProvider(widget.workspace!));
    return MentionList(
      key: const ValueKey('mention'),
      items: [for (final f in rankMentions(files.value ?? const [], m.query)) MentionItem.file(f)],
      empty: files.isLoading && !files.hasValue ? '正在找文件…' : '没有对得上的文件 · 发出去我也会按名字再找一次',
      onPick: _pickMention,
    );
  }

  Widget _inputRow(Palette p) => Row(key: const ValueKey('input'), crossAxisAlignment: CrossAxisAlignment.end, children: [
        IconButton(
          onPressed: widget.busy || _editing ? null : _pick,
          icon: Icon(Icons.add_circle_outline_rounded, color: p.text2),
          tooltip: '添加附件',
        ),
        Expanded(
          child: TextField(
            controller: _c,
            focusNode: _focus,
            minLines: 1,
            maxLines: 6,
            textInputAction: TextInputAction.newline,
            onChanged: (_) => setState(() {}),
            style: context.text.bodyLarge,
            decoration: InputDecoration(
              hintText: widget.streaming && widget.canSteer && !_editing ? steerHint : widget.hint,
              filled: false,
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
              contentPadding: const EdgeInsets.symmetric(vertical: Sp.x3),
            ),
          ),
        ),
        ?widget.accessory,
        AnimatedSwitcher(
          duration: context.motion(Motion.fast),
          transitionBuilder: (child, anim) => ScaleTransition(scale: anim, child: child),
          child: widget.streaming && !_steering
              ? _RoundButton(
                  key: const ValueKey('stop'),
                  icon: Icons.stop_rounded,
                  label: '停止生成',
                  filled: widget.onStop != null,
                  onTap: widget.onStop,
                )
              : _hasContent || widget.busy
              ? _RoundButton(
                  key: ValueKey(_steering ? 'steer' : (_shell ? 'run' : 'send')),
                  icon: _shell ? Icons.terminal_rounded : Icons.arrow_upward_rounded,
                  label: _editing ? '保存并重新回答' : (_shell ? '在电脑上运行' : (_steering ? '补充给正在进行的回答' : '发送')),
                  filled: _canSend,
                  onTap: _canSend ? _send : null,
                )
              : _RoundButton(key: const ValueKey('mic'), icon: Icons.mic_none_rounded, label: '语音输入', filled: false, onTap: _startVoice),
        ),
      ]);

  Widget _voiceRow(Palette p) {
    final transcribing = _voice == _Voice.transcribing;
    final time = '${_seconds ~/ 60}:${(_seconds % 60).toString().padLeft(2, '0')}';
    return Padding(
      key: const ValueKey('voice'),
      padding: const EdgeInsets.only(left: Sp.x2),
      child: Row(children: [
        IconButton(
          onPressed: transcribing ? null : () => _finishVoice(keep: false),
          icon: Icon(Icons.close_rounded, color: p.text2),
          tooltip: '取消',
        ),
        if (transcribing) ...[
          const TypingDots(),
          const SizedBox(width: Sp.x2),
          Text('正在识别…', style: context.text.bodyMedium?.copyWith(color: p.text2)),
        ] else ...[
          PulseDot(color: p.danger),
          const SizedBox(width: Sp.x2),
          Text('正在听  $time', semanticsLabel: '正在录音 $_seconds 秒', style: context.text.bodyMedium?.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
        ],
        const Spacer(),
        _RoundButton(icon: Icons.check_rounded, label: '完成录音', filled: !transcribing, onTap: transcribing ? null : () => _finishVoice(keep: true)),
      ]),
    );
  }
}

/// 编辑态的顶条：说明在改哪条，叉号取消。
class _EditBar extends StatelessWidget {
  const _EditBar({this.onCancel});
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.only(left: Sp.x4),
        child: Row(children: [
          Icon(Icons.edit_outlined, size: 16, color: p.text2),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text('编辑消息 · 发送后重新回答', style: context.text.bodySmall?.copyWith(color: p.text2))),
          IconButton(
            onPressed: onCancel,
            tooltip: '取消编辑',
            iconSize: 18,
            visualDensity: VisualDensity.compact,
            icon: Icon(Icons.close_rounded, color: p.text3),
          ),
        ]),
      ),
    );
  }
}

/// `!命令` 的顶条：说明这条不问助手、直接在电脑上跑（和编辑条同一个位置、同一种出场）。
class _ShellBar extends StatelessWidget {
  const _ShellBar({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, 0),
        child: Row(children: [
          Icon(Icons.terminal_rounded, size: 16, color: p.text2),
          const SizedBox(width: Sp.x2),
          Expanded(
            child: Text('直接在电脑上运行 · 不经过助手，结果它下次能看到',
                style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
        ]),
      ),
    );
  }
}

/// 40 的圆钮，外圈留到 48 的可点区域（视觉不变，手指和读屏都好点）。
class _RoundButton extends StatelessWidget {
  const _RoundButton({super.key, required this.icon, required this.label, required this.filled, this.onTap});
  final IconData icon;
  final String label;
  final bool filled;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Pressable(
      onTap: onTap,
      scale: 0.9,
      semanticLabel: label,
      child: SizedBox.square(
        dimension: A11y.minTap,
        child: Center(
          child: AnimatedContainer(
            duration: context.motion(Motion.fast),
            width: 40,
            height: 40,
            decoration: BoxDecoration(color: filled ? p.ink : context.tileFill, shape: BoxShape.circle),
            child: Icon(icon, size: Layout.rowIcon, color: filled ? p.onInk : p.text2),
          ),
        ),
      ),
    );
  }
}
