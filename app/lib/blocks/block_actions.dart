// 块里需要“回调上层”的动作（审批卡、订单卡的确认都走 onApproval；表单卡的提交/取消走 onForm），通过 InheritedWidget 往下传，
// 这样块组件不依赖具体是聊天页还是 Home 在渲染它。
import 'package:flutter/widgets.dart';

class BlockActions extends InheritedWidget {
  const BlockActions({super.key, required super.child, this.onApproval, this.onForm});
  final void Function(String id, bool approved)? onApproval;

  /// values = null 表示取消。返回 false = 没发出去（断线），卡片保留输入让用户再点。
  final bool Function(String id, Map<String, String>? values, bool remember)? onForm;

  static BlockActions? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<BlockActions>();

  @override
  bool updateShouldNotify(BlockActions old) => old.onApproval != onApproval || old.onForm != onForm;
}
