// 云浏览器实时画面：可见时每 1.2 秒刷新截图；点“接管”后点画面 = 点网页，底部输入框 = 键盘。
// 每个请求都带卡上的会话名（v1.26 按网站分会话）；卡头写网站名。block.live = 页面还在打开：没画面时显示“正在打开”并继续刷，不当作浏览器没开。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/motion.dart';
import '../ui/glass.dart';
import 'block_frame.dart';

class BrowserBlockView extends ConsumerStatefulWidget {
  const BrowserBlockView(this.block, {super.key});
  final BrowserBlock block;

  @override
  ConsumerState<BrowserBlockView> createState() => _BrowserBlockViewState();
}

class _BrowserBlockViewState extends ConsumerState<BrowserBlockView> {
  static const _interval = Duration(milliseconds: 1200);
  static const _aspect = 1280 / 800;
  Timer? _timer;
  int _tick = 0;
  bool _control = false, _broken = false;
  final _keys = TextEditingController();

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(_interval, (_) {
      if (mounted && !_broken && TickerMode.valuesOf(context).enabled) setState(() => _tick++);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _keys.dispose();
    super.dispose();
  }

  Api get _api => ref.read(apiProvider);
  String get _session => widget.block.session;

  /// 还在打开时拿不到画面是正常的：不进“没打开”状态。
  bool get _opening => widget.block.live;

  void _tap(TapUpDetails d, BoxConstraints c) {
    if (!_control) return;
    _api.post('/api/browser/mouse',
        {'x': d.localPosition.dx / c.maxWidth, 'y': d.localPosition.dy / (c.maxWidth / _aspect), 'session': _session});
  }

  Future<void> _sendKeys() async {
    final text = _keys.text;
    _keys.clear();
    await _api.post('/api/browser/keyboard',
        text.isEmpty ? {'key': 'Enter', 'session': _session} : {'text': text, 'key': 'Enter', 'session': _session});
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return BlockFrame(
      tone: _control ? FrameTone.live : FrameTone.calm,
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
            if (!_broken) PulseDot(color: p.danger, size: 7),
            const Spacer(),
            TextButton.icon(
              onPressed: () => setState(() => _control = !_control),
              icon: Icon(_control ? Icons.pan_tool_rounded : Icons.pan_tool_outlined, size: 16),
              label: Text(_control ? '交还给我' : '接管'),
            ),
          ]),
        ),
        LayoutBuilder(
          builder: (_, c) => GestureDetector(
            onTapUp: (d) => _tap(d, c),
            excludeFromSemantics: true,
            child: AspectRatio(
              aspectRatio: _aspect,
              child: _broken
                  ? InkWell(
                      onTap: () => setState(() => _broken = false),
                      child: Container(
                        color: context.tileFill,
                        alignment: Alignment.center,
                        child: Text('浏览器没打开或已休眠，点此重试', style: context.text.bodySmall),
                      ),
                    )
                  : Image.network(
                      '${_api.fileUrl('/api/browser/screen')}&session=${Uri.encodeQueryComponent(_session)}&t=$_tick',
                      semanticLabel: _control ? '浏览器实时画面，已接管，点哪里就点网页哪里' : '浏览器实时画面',
                      fit: BoxFit.cover,
                      gaplessPlayback: true, // 刷新时不闪白
                      errorBuilder: (_, _, _) {
                        if (_opening) {
                          return Container(
                            color: context.tileFill,
                            alignment: Alignment.center,
                            child: Text('正在打开${widget.block.site == null ? '网页' : ' ${widget.block.site}'}…',
                                style: context.text.bodySmall),
                          );
                        }
                        WidgetsBinding.instance.addPostFrameCallback((_) => mounted ? setState(() => _broken = true) : null);
                        return Container(color: context.tileFill);
                      },
                    ),
            ),
          ),
        ),
        AnimatedSize(
          duration: Motion.base,
          curve: Motion.ease,
          child: _control
              ? Padding(
                  padding: const EdgeInsets.all(Sp.x2),
                  child: Row(children: [
                    Expanded(
                      child: TextField(
                        controller: _keys,
                        decoration: const InputDecoration(hintText: '先点画面里的输入框，再在这里打字', isDense: true),
                        onSubmitted: (_) => _sendKeys(),
                      ),
                    ),
                    IconButton.filled(onPressed: _sendKeys, tooltip: '发送按键', icon: const Icon(Icons.keyboard_return_rounded)),
                  ]),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}
