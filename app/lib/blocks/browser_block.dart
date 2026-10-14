// 云浏览器实时画面卡 = 预览 + 接管入口（v2.82 §H：卡片上不再能直接点/打字，接管在全屏页 blocks/browser_takeover.dart）。
// 可见时按节奏刷新截图（models/browser_view.dart screenInterval：助手在等你快、打开中中、看着慢，只是看着 2 分钟后暂停，点一下继续）；
// 接管页开着时卡片不刷（页里自己刷）。点画面或“接管” → 推出接管页。
// 每个请求都带卡上的会话名（v1.26 按网站分会话）；卡头写网站名。block.live = 页面还在打开：没画面时显示“正在打开”并继续刷，不当作浏览器没开。
// v1.29 接管交还：block.handoff pending = 助手在等你（验证码、滑块、扫码）→ 卡头下出“需要你来”条（HandoffBar，和接管页同一个），
// 并且自动推出接管页（每个 handoff 只推一次；只读场景不推）。完成 → onForm(id, {})，做不了 → onForm(id, null)；结束后一行小字说明结果。
// v1.32 画面下列出这条回复里传到网页上的 / 网页下载存进工作区的文件（block.files），点开用工作区文件接口。
// v2.28 block.down = 浏览器服务本身不能用：不拉画面、不能接管，画面位置换成 _DownPanel（一句原因 + 怎么办）。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../core/links.dart';
import '../core/workspace.dart';
import '../models/block.dart';
import '../models/browser_view.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import 'block_actions.dart';
import 'block_frame.dart';
import 'browser_takeover.dart';

class BrowserBlockView extends ConsumerStatefulWidget {
  const BrowserBlockView(this.block, {super.key});
  final BrowserBlock block;

  /// 已自动推过接管页的 handoff id：聊天列表回收重建卡片时不再推第二次。
  static final autoOpened = <String>{};

  @override
  ConsumerState<BrowserBlockView> createState() => _BrowserBlockViewState();
}

class _BrowserBlockViewState extends ConsumerState<BrowserBlockView> {
  Timer? _timer;
  int _tick = 0;
  bool _broken = false, _paused = false, _away = false; // _away = 接管页开着
  String? _replied; // 已答复过的接管 id（等服务器把卡改成 done/cancelled 之前不再显示按钮）
  Duration _idle = Duration.zero; // 只是看着多久了（按排过的帧累计：后台、测试里都准，不读墙钟）
  late final _live = ValueNotifier<BrowserBlock>(widget.block); // 给接管页：卡片更新它跟着变

  BrowserHandoff? get _handoff => widget.block.handoff;
  bool get _waiting => _handoff?.pending == true && _replied != _handoff!.id;
  String? get _down => widget.block.down;

  @override
  void initState() {
    super.initState();
    _schedule();
    _maybeAutoOpen();
  }

  @override
  void didUpdateWidget(BrowserBlockView old) {
    super.didUpdateWidget(old);
    _live.value = widget.block;
    final h = _handoff;
    if (old.block.live != widget.block.live || old.block.handoff?.state != h?.state || old.block.down != _down) {
      if (!widget.block.live) _broken = false; // 打开完成：再试一次拿画面
      _wake();
    }
    if (h != null && h.pending && old.block.handoff?.id != h.id) _maybeAutoOpen();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _live.dispose();
    super.dispose();
  }

  /// 助手在等你：直接推出接管页（每个 handoff 一次；只读场景、服务坏了不推）。
  void _maybeAutoOpen() {
    final h = _handoff;
    if (h == null || !_waiting || _down != null) return;
    if (!BrowserBlockView.autoOpened.add(h.id)) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && BlockActions.of(context)?.onForm != null) _open();
    });
  }

  Future<void> _open() async {
    if (_away || _down != null) return;
    setState(() => _away = true);
    _timer?.cancel();
    final canAnswer = BlockActions.of(context)?.onForm != null;
    await openBrowserTakeover(context, block: _live, onAnswer: canAnswer ? _answer : null);
    if (!mounted) return;
    setState(() => _away = false);
    _wake();
  }

  void _schedule() {
    _timer?.cancel();
    if (_down != null || _away) return; // 服务坏了 / 接管页开着：卡片不拉画面
    final every = screenInterval(control: _waiting, live: widget.block.live);
    _timer = Timer(every, () => _onTick(every));
  }

  void _onTick(Duration waited) {
    if (!mounted || _away) return;
    _idle += waited;
    final pause = screenShouldPause(idle: _idle, control: false, live: widget.block.live, pending: _waiting);
    if (pause) return setState(() => _paused = true); // 不再排下一帧，点一下继续
    if (!_broken && TickerMode.valuesOf(context).enabled) setState(() => _tick++);
    _schedule();
  }

  /// 有动静（点了、卡片状态变了、从接管页回来）：重置“只是看着”的计时，暂停中就恢复。
  void _wake() {
    _idle = Duration.zero;
    if (_paused) setState(() => _paused = false);
    _schedule();
  }

  Api get _api => ref.read(apiProvider);
  String get _session => widget.block.session;

  /// 还在打开时拿不到画面是正常的：不进“没打开”状态。
  bool get _opening => widget.block.live;

  void _tapStage() => _paused ? _wake() : _open();

  /// 完成 / 做不了（卡上的条和接管页共用）；没连上返回 false，按钮留着。
  bool _answer(bool done) {
    final h = _handoff;
    final onForm = BlockActions.of(context)?.onForm;
    if (h == null || onForm == null) return false;
    if (!onForm(h.id, done ? const {} : null, false)) return false;
    setState(() => _replied = h.id);
    _wake();
    return true;
  }

  void _answerOnCard(bool done) {
    if (!_answer(done)) showToast(context, '还没连上，连上后再点一次');
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final h = _handoff;
    final control = _waiting;
    final line = h == null || h.pending ? '' : handoffStateLine(h);
    return BlockFrame(
      tone: control ? FrameTone.live : FrameTone.calm,
      padding: EdgeInsets.zero,
      clip: true,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x1, Sp.x2, Sp.x1),
          child: Row(children: [
            Icon(Icons.public_rounded, size: 18, color: p.text2),
            const SizedBox(width: Sp.x2),
            Flexible(
              child: Text(widget.block.site ?? '云浏览器',
                  style: context.text.labelLarge, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
            const SizedBox(width: Sp.x2),
            FadeSwitcher(child: !_broken && !_paused && _down == null ? PulseDot(key: const ValueKey('on'), color: p.danger, size: 7) : const SizedBox(key: ValueKey('off'))),
            const Spacer(),
            if (_down == null)
              TextButton.icon(
                onPressed: _open,
                icon: const Icon(Icons.open_in_full_rounded, size: 16),
                label: const Text(takeoverLabel),
              )
            else
              const SizedBox(height: kMinInteractiveDimension),
          ]),
        ),
        RiseSwitcher(
          child: _waiting
              ? HandoffBar(key: ValueKey(h!.id), reason: h.reason, onAnswer: BlockActions.of(context)?.onForm == null ? null : _answerOnCard)
              : line.isNotEmpty
                  ? Padding(
                      key: ValueKey('line-${h!.id}-${h.state}'),
                      padding: const EdgeInsets.fromLTRB(Sp.x4, 0, Sp.x4, Sp.x2),
                      child: Text(line, style: context.text.bodySmall?.copyWith(color: p.text2)),
                    )
                  : null,
        ),
        RiseSwitcher(
          child: _down != null
              ? _DownPanel(key: ValueKey('down-$_down'), reason: _down!)
              : KeyedSubtree(
                  key: const ValueKey('stage'),
                  child: GestureDetector(
                    onTap: _tapStage,
                    excludeFromSemantics: true,
                    child: Semantics(
                      label: browserScreenSemantics(takeover: false, paused: _paused, site: widget.block.site),
                      image: true,
                      button: true,
                      child: AspectRatio(aspectRatio: browserAspect, child: _screen(context)),
                    ),
                  ),
                ),
        ),
        AnimatedSize(
          duration: context.motion(Motion.base),
          curve: Motion.ease,
          alignment: Alignment.topCenter,
          child: widget.block.files.isEmpty || widget.block.workspace == null
              ? const SizedBox(width: double.infinity)
              : _FileRows(files: widget.block.files, workspace: widget.block.workspace!),
        ),
      ]),
    );
  }

  Widget _screen(BuildContext context) => Stack(fit: StackFit.expand, children: [
        _base(context),
        FadeSwitcher(
          child: _paused
              ? Container(
                  key: const ValueKey('paused'),
                  color: context.palette.scrim,
                  alignment: Alignment.center,
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.play_arrow_rounded, size: 18, color: context.palette.onInk),
                    const SizedBox(width: Sp.x1),
                    Text('画面已暂停，点一下继续', style: context.text.bodySmall?.copyWith(color: context.palette.onInk)),
                  ]),
                )
              : const SizedBox.shrink(key: ValueKey('live')),
        ),
      ]);

  Widget _base(BuildContext context) {
    if (_broken) {
      return InkWell(
        onTap: () {
          setState(() => _broken = false);
          _wake();
        },
        child: Container(
          color: context.tileFill,
          alignment: Alignment.center,
          child: Text('浏览器没打开或已休眠，点此重试', style: context.text.bodySmall),
        ),
      );
    }
    return Image.network(
      '${_api.fileUrl('/api/browser/screen')}&session=${Uri.encodeQueryComponent(_session)}&t=$_tick',
      excludeFromSemantics: true,
      fit: BoxFit.cover,
      gaplessPlayback: true, // 刷新时不闪白
      errorBuilder: (_, _, _) {
        if (_opening) {
          return Container(
            color: context.tileFill,
            alignment: Alignment.center,
            child: Text('正在打开${widget.block.site == null ? '网页' : ' ${widget.block.site}'}…', style: context.text.bodySmall),
          );
        }
        WidgetsBinding.instance.addPostFrameCallback((_) => mounted ? setState(() => _broken = true) : null);
        return Container(color: context.tileFill);
      },
    );
  }
}

/// 浏览器服务不能用：图标 + 标题 + 原因 + 怎么办（读屏一次读完）。
class _DownPanel extends StatelessWidget {
  const _DownPanel({super.key, required this.reason});
  final String reason;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      container: true,
      liveRegion: true,
      label: '$browserDownTitle：$reason。$browserDownHint',
      child: ExcludeSemantics(
        child: Container(
          margin: const EdgeInsets.fromLTRB(Sp.x2, 0, Sp.x2, Sp.x2),
          padding: const EdgeInsets.all(Sp.x3),
          decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.only(top: 2), child: Icon(Icons.public_off_rounded, size: 18, color: p.warning)),
            const SizedBox(width: Sp.x2),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(browserDownTitle, style: context.text.labelLarge),
                const SizedBox(height: Sp.x1),
                Text(reason, style: context.text.bodySmall?.copyWith(color: p.text2)),
                const SizedBox(height: Sp.x1),
                Text(browserDownHint, style: context.text.labelSmall),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// 画面下的文件清单（v1.32）：↑ 传到网页上的工作区文件、↓ 网页下载存进工作区的。新来的一条上浮淡入，点开 = 打开工作区文件。
class _FileRows extends ConsumerWidget {
  const _FileRows({required this.files, required this.workspace});
  final List<BrowserFile> files;
  final String workspace;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(Sp.x2, Sp.x2, Sp.x2, 0),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final f in files)
          FadeSlideIn(
            key: ValueKey('${f.kind}:${f.path}'),
            child: Padding(
              padding: const EdgeInsets.only(bottom: Sp.x1),
              child: Pressable(
                semanticLabel: browserFileSemantics(f),
                onTap: () => openUrl(ref.read(apiProvider).fileUrl(workspaceFilePath(workspace, f.path))),
                child: ExcludeSemantics(
                  child: Container(
                  constraints: const BoxConstraints(minHeight: Layout.rowMin),
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x2),
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
                  child: Row(children: [
                    Icon(f.uploaded ? Icons.upload_file_rounded : Icons.download_done_rounded, size: 18, color: p.text2),
                    const SizedBox(width: Sp.x2),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                        Text(f.name, style: context.text.labelLarge, maxLines: 1, overflow: TextOverflow.ellipsis),
                        Text(browserFileLine(f), style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1),
                      ]),
                    ),
                    Icon(Icons.chevron_right_rounded, size: Layout.rowIcon, color: p.text3),
                  ]),
                ),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}
