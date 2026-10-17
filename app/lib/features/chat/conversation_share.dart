// 分享对话：把对话做成一张只读网页快照（服务端渲染，Pages 的一种），拿到链接的人都能看。
// 数据只在 conversationShareProvider(对话 id) 里：GET 状态 / POST 生成或更新快照 / DELETE 停止分享；
// 页面本身也出现在“我的 → Pages”，所以每次变动顺手让 pagesProvider 失效。
// 入口两个，都只调 showConversationShare：历史面板长按菜单“分享为网页”、顶栏标题弹出的本对话用量页右上角。
// 三种状态共用一个 Sheet，SwapSwitcher 换内容：没分享 → 一个主按钮；分享中 → 链接 + 复制/分享 +（有新内容时）更新快照 + 停止分享；
// 停止过 → 主按钮“恢复分享”，原链接复活。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../core/swr.dart';
import '../../core/share.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class ConversationShareNotifier extends SwrNotifier<ConversationShare> {
  ConversationShareNotifier(this.id);
  final String id;

  @override
  String get path => '/api/conversations/$id/share';

  @override
  ConversationShare parse(Object? j) => ConversationShare.fromJson(jsonMap(j));

  /// 生成 / 更新快照并公开（停止过的也恢复，原链接不变）。
  Future<void> share() => _run(() => ref.read(apiProvider).post(path));

  /// 停止分享 = 下线：链接打不开，但保留，再分享原链接恢复。
  Future<void> unshare() => _run(() => ref.read(apiProvider).delete(path));

  Future<void> _run(Future<dynamic> Function() call) async {
    emit(await call()); // 出错直接抛给调用方提示，旧状态不动
    ref.invalidate(pagesProvider);
  }
}

final conversationShareProvider =
    AsyncNotifierProvider.autoDispose.family<ConversationShareNotifier, ConversationShare, String>(ConversationShareNotifier.new);

Future<void> showConversationShare(BuildContext context, String id) =>
    showAppSheet<void>(context, title: '分享对话', builder: (_) => ConversationShareSheet(id: id));

class ConversationShareSheet extends ConsumerStatefulWidget {
  const ConversationShareSheet({super.key, required this.id});
  final String id;

  @override
  ConsumerState<ConversationShareSheet> createState() => _ConversationShareSheetState();
}

class _ConversationShareSheetState extends ConsumerState<ConversationShareSheet> {
  bool _busy = false;

  ConversationShareNotifier get _ctl => ref.read(conversationShareProvider(widget.id).notifier);

  Future<void> _do(Future<void> Function() action, String done) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
      if (mounted) showToast(context, done);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _stop() async {
    final ok = await confirmDanger(context,
        title: '停止分享？', text: '链接会打不开，快照还留着；之后再分享，原链接恢复。', action: '停止分享');
    if (ok && mounted) await _do(_ctl.unshare, '已停止分享');
  }

  void _copy(String url) {
    Clipboard.setData(ClipboardData(text: url));
    showToast(context, '链接已复制');
  }

  Future<void> _systemShare(PageItem page) async {
    final box = context.findRenderObject() as RenderBox?;
    final origin = box == null ? null : box.localToGlobal(Offset.zero) & box.size; // iPad 弹出框锚点
    try {
      await shareLink(page.url, subject: page.title, origin: origin);
    } catch (_) {
      if (mounted) showToast(context, '这台设备打不开分享面板');
    }
  }

  @override
  Widget build(BuildContext context) {
    final value = ref.watch(conversationShareProvider(widget.id));
    final p = context.palette;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x5),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('生成一张只读网页快照，拿到链接的人都能看。审批卡和浏览器画面不会出现，附件只显示文件名。',
              style: context.text.bodySmall?.copyWith(color: p.text2)),
          const SizedBox(height: Sp.x4),
          SwapSwitcher(
            child: value.swr(
              loading: () => const Shimmer(key: ValueKey('loading'), height: 104),
              error: (e) => Column(key: const ValueKey('error'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text(e is ApiError ? e.message : '加载失败', style: context.text.bodySmall),
                const SizedBox(height: Sp.x3),
                PillButton(label: '重试', onTap: () => ref.invalidate(conversationShareProvider(widget.id))),
              ]),
              data: (s) => s.shared && s.page != null ? _shared(s, s.page!) : _notShared(s),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _notShared(ConversationShare s) => Column(key: const ValueKey('off'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (s.page != null) ...[
          Text('之前停止过分享，恢复后还是原来的链接。', style: context.text.bodySmall),
          const SizedBox(height: Sp.x3),
        ],
        PillButton(
          label: s.page == null ? '生成分享链接' : '恢复分享',
          icon: Icons.public_rounded,
          primary: true,
          onTap: _busy ? null : () => _do(_ctl.share, s.page == null ? '已生成链接' : '已恢复，原链接可以打开了'),
        ),
      ]);

  Widget _shared(ConversationShare s, PageItem page) {
    final p = context.palette;
    return Column(key: const ValueKey('on'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Pressable(
        semanticLabel: '复制链接',
        onTap: () => _copy(page.url),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
          decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
          child: Row(children: [
            Icon(Icons.link_rounded, size: Fs.lg, color: p.text2),
            const SizedBox(width: Sp.x3),
            Expanded(child: Text(page.url, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodyMedium)),
          ]),
        ),
      ),
      const SizedBox(height: Sp.x2),
      Text('快照更新于 ${formatAgo(page.updatedAt)}', style: context.text.bodySmall?.copyWith(color: p.text2)),
      const SizedBox(height: Sp.x4),
      Row(children: [
        Expanded(child: PillButton(label: '复制链接', icon: Icons.copy_rounded, onTap: () => _copy(page.url))),
        const SizedBox(width: Sp.x3),
        Expanded(child: PillButton(label: '分享', icon: Icons.ios_share_rounded, primary: true, onTap: () => _systemShare(page))),
      ]),
      RiseSwitcher(
        child: s.stale
            ? Padding(
                key: const ValueKey('stale'),
                padding: const EdgeInsets.only(top: Sp.x3),
                child: PillButton(
                  label: '对话有新内容 · 更新快照',
                  icon: Icons.refresh_rounded,
                  onTap: _busy ? null : () => _do(_ctl.share, '快照已更新，链接不变'),
                ),
              )
            : null,
      ),
      const SizedBox(height: Sp.x2),
      Center(
        child: TextButton(
          onPressed: _busy ? null : _stop,
          style: TextButton.styleFrom(foregroundColor: p.danger),
          child: const Text('停止分享'),
        ),
      ),
    ]);
  }
}
