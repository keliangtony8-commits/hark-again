// 输入框：圆角胶囊 + 附件托盘 + 录音态。
// 三种形态平滑切换：空 → 显示麦克风；有字/附件 → 发送键；录音中 → 红点计时 + 完成/取消。
// 生成中右侧圆钮换成“停止”（onStop 为 null = 已请求停止，置灰等服务器收尾）；输入框照常可打字，说完再发。
// 引用回复（quoting 不为 null，§J）：顶部引用条（竖线 + 原文一行 + ✕），和编辑条同一个槽位；编辑态优先。
// 编辑态（editing 不为 null）：顶部“编辑消息”条 + 原文字填进输入框；原来的附件随消息保留，
//   这里的附件托盘和草稿先收起，退出编辑（发出或取消）后原样回来。
// accessory：右侧圆钮左边的插槽（聊天页放模型钮，Composer 不认识它）。
// 设计 v2：整条是浮在内容上的玻璃胶囊（真模糊，外面用 ui/kit.dart FloatingFooter 让位）；
//   leading：胶囊左边、胶囊外的圆钮位（一级页面聚焦时的“收起”），出现/消失用 RiseSwitcher 横向长出；
//   focusNode：外面要知道聚焦状态时传进来（LaunchComposer 用它开关整页磨砂）。
// workspace：这段对话的工作区（core/workspace.dart；项目 = 项目文件，主聊天 = 我的文件）。“添加附件”多一个从它选
// （features/projects pickProjectFiles，不上传，只带引用）；null = 没有这个来源（如首页的快捷输入框）。
// 打 $ → 顶部列出启用的技能，点一下补成 `$id `（服务器 app/skill_mentions.py 把正文给模型）。
// 开头打 / → 顶部列出斜杠命令（models/slash.dart）：/init 原文发给服务器；本机命令（/new /compact /plan /copy /status）
// 交给 onSlash（ChatView → slash_actions.dart），不发消息。点候选：不接话的本机命令直接执行，其余补成 `/xxx `。
// 生成中不能用的命令：提示条说“回答结束后再用”、发送钮灰掉。
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
import '../../models/slash.dart';
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
import 'quote_line.dart';
import '../../brand.dart';

/// 正在编辑的那条用户消息。hasFiles：带附件的消息文字清空也能发（只剩附件）。
class EditDraft {
  const EditDraft(this.id, this.text, {this.hasFiles = false});
  EditDraft.of(Message m) : this(m.id, plainText(m.blocks), hasFiles: m.blocks.any((b) => b is FileBlock));
  final String id;
  final String text;
  final bool hasFiles;
}

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
      this.quoting,
      this.onCancelQuote,
      this.accessory,
      this.hint = '给 $appName 发消息',
      this.leading,
      this.focusNode,
      this.workspace,
      this.onSlash});
  final void Function(String text, List<FileBlock> files) onSend;
  final bool busy;
  final bool streaming;

  /// 生成中可以补一句给正在进行的这一轮（ChatState.canSteer）：有字时停止钮换成“补充”钮。
  final bool canSteer;
  final VoidCallback? onStop;
  final EditDraft? editing;
  final VoidCallback? onCancelEdit;

  /// 正在引用回复的那条（§J，ChatView 持有）：顶部出引用条、输入框获得焦点；发出后由 ChatView 清掉。编辑态优先。
  final MessageQuote? quoting;
  final VoidCallback? onCancelQuote;

  /// 右侧圆钮左边的小部件（模型钮）；录音态不显示。
  final Widget? accessory;
  final String hint;
  final Widget? leading;
  final FocusNode? focusNode;

  /// 工作区 id（null = 没有“从工作区引用文件”这个来源）。
  final String? workspace;

  /// 本机斜杠命令（/new /compact /plan /copy /status）的执行者；null = 这个输入框不接本机命令（打了当普通文字发）。
  final void Function(SlashCall call, List<FileBlock> files)? onSlash;

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
  String? _slash; // 开头正在打的 /xxx（编辑消息时不弹）

  Media get _media => ref.read(mediaProvider);

  @override
  void initState() {
    super.initState();
    _c.addListener(_trackMention); // 光标挪动（不改字）也要更新
  }

  void _trackMention() {
    final sel = _c.selection;
    // $技能、@子助手 哪儿都能用（@文件 要有工作区）；!命令 里的 @ / $ 是给电脑的，都不弹
    final m = !sel.isValid || !sel.isCollapsed || shellCommandOf(_c.text) != null
        ? null
        : mentionAt(_c.text, sel.baseOffset, sigils: const {skillSigil, fileSigil});
    final s = !sel.isValid || !sel.isCollapsed || _editing ? null : slashQueryAt(_c.text, sel.baseOffset);
    if ((m != _mention || s != _slash) && mounted) {
      setState(() {
        _mention = m;
        _slash = s;
      });
    }
  }

  void _pickSlash(String name) {
    final c = slashCommands.firstWhere((c) => c.name == name);
    final call = SlashCall(c, '');
    if (c.local && !c.args && !slashBlocked(call, busy: widget.busy)) {
      _c.clear(); // Codex：不带参数的命令点了就执行
      widget.onSlash?.call(call, const []);
      return;
    }
    final (text, caret) = applySlash(c);
    _c.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: caret));
    _focus.requestFocus();
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
    if (widget.quoting != null && widget.quoting!.id != old.quoting?.id) _focus.requestFocus(); // 点了“回复”：直接打字
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
  bool get _canSend {
    final cmd = _command;
    if (cmd != null && cmd.local) return !slashBlocked(cmd, busy: widget.busy) && !_uploading;
    return (!widget.busy || _steering) && !_uploading && _hasContent;
  }

  /// 生成中有字或附件：照常能发（v2.90 服务器 message_intake 判断是补充还是另一件事，每件事都回）；没内容时这个位置是停止。
  bool get _steering =>
      widget.streaming && widget.canSteer && !_editing && !_shell && _command == null && _hasContent &&
      !mentionsAgent(_c.text); // 点名子助手是一件新的事：排成下一轮（服务器同样不插队）

  /// 整条是本机命令（不发消息）。
  bool get _local => _command?.local ?? false;

  /// 生成中也能马上执行的本机命令（/copy /status）：停止钮让位给执行钮。
  bool get _runsNow {
    final c = _command;
    return c != null && c.local && !slashBlocked(c, busy: widget.busy);
  }

  /// 整条是 `!命令`（且没带附件）：发出去不问助手，直接在这段对话的电脑上跑（后端 user_shell）。
  bool get _shell => !_editing && _attachments.isEmpty && shellCommandOf(_c.text) != null;

  /// 整条是一条斜杠命令（编辑消息时不认）。/init 生成中发出去排成下一轮；本机命令只在没带附件时认（/plan 接话可带）。
  SlashCall? get _command {
    if (_editing) return null;
    final c = slashOf(_c.text, local: widget.onSlash != null);
    if (c != null && c.local && _attachments.isNotEmpty && !c.command.args) return null;
    return c;
  }

  void _send() {
    if (!_canSend) return;
    if (_editing) {
      widget.onSend(_c.text, const []); // 草稿由 didUpdateWidget 在退出编辑时放回
      return;
    }
    final files = [for (final a in _attachments) if (a.file != null) a.file!];
    final cmd = _command;
    if (cmd != null && cmd.local) {
      widget.onSlash!(cmd, files);
    } else {
      widget.onSend(_c.text, files);
    }
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
                  // mainAxisSize.min：GlassSheet 给内容的是“最高到屏幕”的松约束，Column 默认 max 会把弹层撑满全屏（v2.97 附件弹层高度）
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
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
            child: _slash != null && rankSlash(_slash!, local: widget.onSlash != null).isNotEmpty
                ? _slashList()
                : _mention != null
                ? _mentionList()
                : _editing
                ? _EditBar(onCancel: widget.onCancelEdit)
                : widget.quoting != null
                ? QuoteBar(widget.quoting!, key: ValueKey('quote-${widget.quoting!.id}'), onCancel: widget.onCancelQuote)
                : _shell
                ? const _HintBar(key: ValueKey('shell'), icon: Icons.terminal_rounded, text: '直接在电脑上运行 · 不经过助手，结果它下次能看到')
                : _command != null
                ? _HintBar(key: ValueKey('slash-${_command!.command.name}'), icon: _command!.command.icon, text: slashBarText(_command!, busy: widget.busy))
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

  Widget _slashList() => MentionList(
        key: const ValueKey('slash'),
        items: [
          for (final c in rankSlash(_slash!, local: widget.onSlash != null))
            MentionItem(
                key: c.name,
                icon: c.icon,
                title: c.token,
                subtitle: slashSubtitle(c, busy: widget.busy),
                semantic: '命令 ${c.token}：${slashSubtitle(c, busy: widget.busy)}'),
        ],
        empty: '',
        onPick: _pickSlash,
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
    final ws = widget.workspace;
    final files = ws == null ? null : ref.watch(projectFilesProvider(ws));
    final agent = agentMatches(m.query);
    return MentionList(
      key: const ValueKey('mention'),
      items: [
        if (agent) MentionItem.agent(), // 子助手永远在第一行（Gemini：@名字先按代理认）
        for (final f in rankMentions(files?.value ?? const [], m.query, max: agent ? mentionMax - 1 : mentionMax)) MentionItem.file(f),
      ],
      empty: files == null
          ? '打 @$agentMention 可以把这件事交给子助手'
          : files.isLoading && !files.hasValue
              ? '正在找文件…'
              : '没有对得上的文件 · 发出去我也会按名字再找一次',
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
              hintText: widget.hint,
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
          child: widget.streaming && !_steering && !_runsNow
              ? _RoundButton(
                  key: const ValueKey('stop'),
                  icon: Icons.stop_rounded,
                  label: '停止生成',
                  filled: widget.onStop != null,
                  onTap: widget.onStop,
                )
              : _hasContent || widget.busy
              ? _RoundButton(
                  key: ValueKey(_steering ? 'steer' : (_shell ? 'run' : (_local ? 'slash' : 'send'))),
                  icon: _shell ? Icons.terminal_rounded : (_local ? Icons.keyboard_return_rounded : Icons.arrow_upward_rounded),
                  label: _editing
                      ? '保存并重新回答'
                      : (_shell ? '在电脑上运行' : (_steering ? '发送' : (_local ? '执行 ${_command!.command.token}' : '发送'))),
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
/// 输入胶囊顶部的一行说明（!命令、/init 共用）。
class _HintBar extends StatelessWidget {
  const _HintBar({super.key, required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, 0),
        child: Row(children: [
          Icon(icon, size: 16, color: p.text2),
          const SizedBox(width: Sp.x2),
          Expanded(
            child: Text(text,
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
