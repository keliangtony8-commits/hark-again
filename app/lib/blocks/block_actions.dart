// 块里需要“回调上层”的动作（审批卡、订单卡的确认都走 onApproval；表单卡的提交/取消走 onForm），通过 InheritedWidget 往下传，
// 这样块组件不依赖具体是聊天页还是 Home 在渲染它。
import 'package:flutter/widgets.dart';

class BlockActions extends InheritedWidget {
  const BlockActions({super.key, required super.child, this.onApproval, this.onApprovalOption, this.onForm, this.onJobSettled});
  final void Function(String id, bool approved)? onApproval;

  /// 带批准范围地批准（主机命令卡的“这段对话里都允许 / 以后都允许…”，v1.49）。没给就只显示“批准 / 拒绝”。
  final void Function(String id, String option)? onApprovalOption;

  /// values = null 表示取消。返回 false = 没发出去（断线），卡片保留输入让用户再点。
  final bool Function(String id, Map<String, String>? values, bool remember)? onForm;

  /// 后台任务卡看着任务结束、服务器也接着说完了：聊天页重新拿一次这段对话，把助手的结论显示出来。
  final VoidCallback? onJobSettled;

  static BlockActions? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<BlockActions>();

  @override
  bool updateShouldNotify(BlockActions old) => old.onApproval != onApproval || old.onApprovalOption != onApprovalOption || old.onForm != onForm || old.onJobSettled != onJobSettled;
}
