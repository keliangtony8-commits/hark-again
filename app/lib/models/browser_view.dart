// 浏览器画面卡的纯规则（v1.29）：接管条文案、截图刷新节奏（截图轮询，不上 VNC：省 VPS 和流量）、读屏句子。
// 网页版 lib/browserView.ts 同一套；卡片本身在 blocks/browser_block.dart。
import '../theme/tokens.dart';
import 'block.dart';

const handoffTitle = '需要你来';
const handoffDoneLabel = '完成，交还';
const handoffCancelLabel = '做不了';

/// 右上角按钮：没在操作 → 接管；在操作 → 交还（不是“交还给我”：交还的对象是助手）。
String controlLabel(bool control) => control ? '交还' : '接管';

/// 接管结束后卡头下的一行小字；还在等 → 空（显示接管条）。
String handoffStateLine(BrowserHandoff h) => switch (h.state) {
      'done' => '你已交还，助手接着做',
      'cancelled' => '你没有接管，助手会换个办法',
      'expired' => '等太久没回应，已取消',
      _ => '',
    };

/// 截图刷新节奏：你在操作（或助手在等你）→ 快；页面在打开 → 中；只是看着 → 慢。
Duration screenInterval({required bool control, required bool live}) =>
    control ? Timing.screenFast : live ? Timing.screenOpening : Timing.screenIdle;

/// 只是看着超过 screenPauseAfter 就暂停刷新；在操作、在打开、在等你接管都不停。
bool screenShouldPause({required Duration idle, required bool control, required bool live, required bool pending}) =>
    !control && !live && !pending && idle >= Timing.screenPauseAfter;

String browserScreenSemantics({required bool control, required bool paused, String? site}) {
  final where = site == null ? '浏览器' : '$site 的浏览器';
  if (paused) return '$where画面已暂停，点一下继续';
  return control ? '$where实时画面，已接管，点哪里就点网页哪里' : '$where实时画面';
}

/// 卡上文件小条的第二行：传上去的 → “已传到网页”；下载的 → “已存到 downloads”（所在文件夹）。
String browserFileLine(BrowserFile f) {
  if (f.uploaded) return '已传到网页';
  final slash = f.path.lastIndexOf('/');
  return slash > 0 ? '已存到 ${f.path.substring(0, slash)}' : '已存到工作区';
}

String browserFileSemantics(BrowserFile f) => '${f.name}，${browserFileLine(f)}，点开查看';
