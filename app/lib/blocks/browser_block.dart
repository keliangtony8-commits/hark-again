// 云浏览器实时画面卡 = 预览 + 接管入口（v2.82 §H：卡片上不能直接点/打字，接管在全屏页 blocks/browser_takeover.dart）。
// v2.89 §M：画面是一条 WS 推流（blocks/browser_live.dart BrowserLive，卡片拥有、接管页复用同一条），画面变了才推，
// 卡片在就连、拆了就断、App 后台断开；断了退避重连（先留着最后一帧，盖一句“正在重连…”），浏览器已关闭 → “重新打开”。
// 每个连接带卡上的会话名（v1.26 按网站分会话）；卡头写网站名。block.live = 页面还在打开：“没开”当作还没好，接着连。
// v1.29 接管交还：block.handoff pending = 助手在等你（验证码、滑块、扫码）→ 卡头下出“需要你来”条（HandoffBar，和接管页同一个），
// 并且自动推出接管页（每个 handoff 只推一次；只读场景不推）。完成 → onForm(id, {})，做不了 → onForm(id, null)；结束后一行小字说明结果。
// v1.32 画面下列出这条回复里传到网页上的 / 网页下载存进工作区的文件（block.files），点开用工作区文件接口。
// v2.28 block.down = 浏览器服务本身不能用：不连画面、不能接管，画面位置换成 _DownPanel（一句原因 + 怎么办）。
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
import 'browser_live.dart';
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
  bool _away = false; // 接管页开着
  double _px = 0; // 卡上画面的物理像素宽（接管页关了再报一次）
  String? _replied; // 已答复过的接管 id（等服务器把卡改成 done/cancelled 之前不再显示按钮）
  late final _live = ValueNotifier<BrowserBlock>(widget.block); // 给接管页：卡片更新它跟着变
  BrowserLive? _stream;

  BrowserHandoff? get _handoff => widget.block.handoff;
  bool get _waiting => _handoff?.pending == true && _replied != _handoff!.id;
  String? get _down => widget.block.down;

  @override
  void initState() {
    super.initState();
    _syncStream();
    _maybeAutoOpen();
  }

  @override
  void didUpdateWidget(BrowserBlockView old) {
    super.didUpdateWidget(old);
    _live.value = widget.block;
    _syncStream();
    final h = _handoff;
    if (h != null && h.pending && old.block.handoff?.id != h.id) _maybeAutoOpen();
  }

  @override
  void dispose() {
    _dropStream();
    _live.dispose();
    super.dispose();
  }

  /// 服务坏了（block.down）不连；好了再连。会话名变了（不会，但防御）重建。
  void _syncStream() {
    if (_down != null) return _dropStream();
    final s = _stream;
    if (s != null) {
      s.opening = widget.block.live;
      return;
    }
    final api = ref.read(apiProvider);
    final session = widget.block.session;
    _stream = BrowserLive(
      uri: (reopen) => liveUri(api, session, reopen: reopen),
      connect: ref.read(liveConnectProvider),
      openingAtStart: widget.block.live,
    )
      ..addListener(_onStream)
      ..hold();
  }

  void _dropStream() {
    final s = _stream;
    if (s == null) return;
    _stream = null;
    s
      ..removeListener(_onStream)
      ..release()
      ..drop();
  }

  /// 只在连接状态变了时重画卡头（红点）；帧由 LiveScreen 自己听，不重画整张卡。
  LiveState? _shown;
  void _onStream() {
    final st = _stream?.state;
    if (mounted && st != _shown) setState(() => _shown = st);
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
    final stream = _stream;
    if (_away || _down != null || stream == null) return;
    setState(() => _away = true);
    final canAnswer = BlockActions.of(context)?.onForm != null;
    await openBrowserTakeover(context, block: _live, live: stream, onAnswer: canAnswer ? _answer : null);
    if (!mounted) return;
    setState(() => _away = false);
    if (_px > 0) stream.view(_px); // 接管页报过它自己的宽度：换回卡片的
  }

  /// 完成 / 做不了（卡上的条和接管页共用）；没连上返回 false，按钮留着。
  bool _answer(bool done) {
    final h = _handoff;
    final onForm = BlockActions.of(context)?.onForm;
    if (h == null || onForm == null) return false;
    if (!onForm(h.id, done ? const {} : null, false)) return false;
    setState(() => _replied = h.id);
    return true;
  }

  void _answerOnCard(bool done) {
    if (!_answer(done)) showToast(context, '尚未连接，连接后请重试');
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
            FadeSwitcher(child: _stream?.state == LiveState.live && _down == null ? PulseDot(key: const ValueKey('on'), color: p.danger, size: 7) : const SizedBox(key: ValueKey('off'))),
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
                    onTap: _open,
                    excludeFromSemantics: true,
                    child: Semantics(
                      label: browserScreenSemantics(takeover: false, site: widget.block.site),
                      image: true,
                      button: true,
                      child: AspectRatio(
                        aspectRatio: browserAspect,
                        child: LayoutBuilder(builder: (context, c) {
                          _px = c.maxWidth * MediaQuery.devicePixelRatioOf(context);
                          if (!_away) _stream?.view(_px);
                          return _stream == null ? const SizedBox.shrink() : LiveScreen(live: _stream!, site: widget.block.site);
                        }),
                      ),
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

}

/// 实时画面（卡片和接管页共用）：最新一帧 + 状态（重连中先留着最后一帧，盖一层淡淡的说明；关了给“重新打开”）。
class LiveScreen extends StatelessWidget {
  const LiveScreen({super.key, required this.live, this.site, this.radius = 0});
  final BrowserLive live;
  final String? site;
  final double radius;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: live,
        builder: (context, _) {
          final f = live.frame;
          final line = liveStatusLine(live.state, hasFrame: f != null, opening: live.isOpening, site: site);
          return ClipRRect(
            borderRadius: BorderRadius.circular(radius),
            child: Stack(fit: StackFit.expand, children: [
              if (f != null)
                Image.memory(f, fit: BoxFit.cover, gaplessPlayback: true, excludeFromSemantics: true)
              else
                ColoredBox(color: context.tileFill),
              FadeSwitcher(
                child: line == null
                    ? const SizedBox.shrink(key: ValueKey('clear'))
                    : Container(
                        key: ValueKey('${live.state}'),
                        color: f == null ? Colors.transparent : context.palette.scrim,
                        alignment: Alignment.center,
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(line,
                              style: context.text.bodySmall?.copyWith(color: f == null ? context.palette.text2 : context.palette.onInk)),
                          if (liveCanReopen(live.state)) ...[
                            const SizedBox(height: Sp.x2),
                            PillButton(label: liveReopenLabel, dense: true, onTap: live.reopen),
                          ],
                        ]),
                      ),
              ),
            ]),
          );
        },
      );
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
