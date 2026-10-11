// Pages：我为你生成并发布的网页。点一行打开操作菜单：打开、分享、复制链接、重命名、下线 / 重新发布；左滑删除。
// 下线 ≠ 删除：文件留着、公开链接暂时 404，重新发布后同一个链接恢复（发出去的链接不用重发）。
// 状态变化全走 pagesProvider.patch（PATCH /api/pages/{slug}），页面不自己维护副本。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/links.dart';
import '../../core/resource.dart';
import '../../core/share.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class PagesScreen extends ConsumerWidget {
  const PagesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SubPage(
      title: const Text('Pages'),
      body: AsyncBody<PageItem>(
        value: ref.watch(pagesProvider),
        onRetry: () => ref.invalidate(pagesProvider),
        empty: const EmptyHint(icon: Icons.web_rounded, title: '还没有发布过网页', text: '在聊天里说“把这个行程做成一个网页”，做好的页面会出现在这里。'),
        builder: (list) => PageBody(children: [
          ListGroup(children: [
            for (final (i, pg) in list.indexed)
              SwipeToDelete(
                id: pg.id,
                confirm: () => confirmDanger(context, title: '删除「${pg.title}」？', text: '分享出去的链接也会失效。只想暂时不让人看，可以用“下线”。'),
                onDelete: () => ref.read(pagesProvider.notifier).remove(pg.id),
                child: FadeSlideIn(delay: Motion.stagger(i), child: PageRow(pg)),
              ),
          ]),
        ]),
      ),
    );
  }
}

/// 一行：已下线的变淡并带“已下线”标签（标签换入换出走 SwapSwitcher）。
class PageRow extends ConsumerWidget {
  const PageRow(this.pg, {super.key});
  final PageItem pg;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Dimmed(
      dimmed: !pg.published,
      child: RowTile(
        icon: pg.published ? Icons.web_rounded : Icons.visibility_off_outlined,
        title: pg.title,
        subtitle: '${hostOf(pg.url)} · ${formatAgo(pg.updatedAt)}',
        trailing: SwapSwitcher(
          child: pg.published
              ? Icon(Icons.chevron_right_rounded, key: const ValueKey('live'), color: context.palette.text3)
              : const Pill('已下线', key: ValueKey('off')),
        ),
        onTap: () => _menu(context, ref),
      ),
    );
  }

  Future<void> _menu(BuildContext context, WidgetRef ref) {
    final box = context.findRenderObject() as RenderBox?;
    final origin = box == null ? null : box.localToGlobal(Offset.zero) & box.size;
    return showActionSheet<void>(context, title: pg.title, actions: [
      if (pg.published) ...[
        SheetAction(Icons.open_in_new_rounded, '在浏览器打开', onTap: () => openUrl(pg.url)),
        SheetAction(Icons.ios_share_rounded, '分享链接', onTap: () => shareLink(pg.url, subject: pg.title, origin: origin)),
        SheetAction(Icons.link_rounded, '复制链接', onTap: () {
          Clipboard.setData(ClipboardData(text: pg.url));
          showToast(context, '已复制');
        }),
      ] else
        SheetAction(Icons.public_rounded, '重新发布', onTap: () => _setPublished(context, ref, true)),
      SheetAction(Icons.drive_file_rename_outline_rounded, '重命名', onTap: () => _rename(context, ref)),
      if (pg.published) SheetAction(Icons.visibility_off_outlined, '下线', danger: true, onTap: () => _unpublish(context, ref)),
    ]);
  }

  Future<void> _unpublish(BuildContext context, WidgetRef ref) async {
    final ok = await confirmDanger(context, title: '下线「${pg.title}」？', text: '链接会暂时打不开，页面还留着；随时可以重新发布，链接不变。', action: '下线');
    if (ok && context.mounted) await _setPublished(context, ref, false);
  }

  Future<void> _setPublished(BuildContext context, WidgetRef ref, bool published) =>
      _patch(context, ref, {'published': published}, published ? '已重新发布，原链接恢复' : '已下线');

  Future<void> _rename(BuildContext context, WidgetRef ref) async {
    final r = await showFormSheet(context, title: '重命名', fields: [FieldSpec('title', '标题', initial: pg.title)]);
    final title = r?['title'];
    if (title == null || title == pg.title || !context.mounted) return;
    await _patch(context, ref, {'title': title}, '已重命名');
  }

  Future<void> _patch(BuildContext context, WidgetRef ref, Map<String, dynamic> body, String done) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(pagesProvider.notifier).patch(pg.id, body);
      messenger..hideCurrentSnackBar()..showSnackBar(SnackBar(content: Text(done)));
    } on ApiError catch (e) {
      messenger..hideCurrentSnackBar()..showSnackBar(SnackBar(content: Text(e.message)));
    }
  }
}
