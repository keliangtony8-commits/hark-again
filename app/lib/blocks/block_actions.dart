// 块里需要“回调上层”的动作（目前只有审批），通过 InheritedWidget 往下传，
// 这样块组件不依赖具体是聊天页还是 Home 在渲染它。
import 'package:flutter/widgets.dart';

class BlockActions extends InheritedWidget {
  const BlockActions({super.key, required super.child, this.onApproval});
  final void Function(String id, bool approved)? onApproval;

  static BlockActions? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<BlockActions>();

  @override
  bool updateShouldNotify(BlockActions old) => old.onApproval != onApproval;
}
