// 浏览器画面卡 + 接管页的纯规则（v1.29 / v2.82）：接管条文案、截图刷新节奏（截图轮询，不上 VNC：省 VPS 和流量）、
// 读屏句子、接管页的坐标换算（缩放平移后点到网页哪里）。
// 网页版 lib/browserView.ts 同一套；卡片在 blocks/browser_block.dart，接管页在 blocks/browser_takeover.dart。
import 'dart:ui';

import '../theme/tokens.dart';
import 'block.dart';

/// 浏览器服务的视口（browser/service.py VIEW）：截图就是这么大。
const browserView = Size(1280, 800);
const browserAspect = 1280 / 800;

/// 接管页最多放大几倍（再大截图就糊成色块了）。
const takeoverZoomMax = 4.0;

/// 接管页第一次进来时画面下的一句手势说明；用户做过一次手势就不再显示。
const takeoverHint = '双指放大，单指滚动，长按拖动';
const takeoverKeysHint = '打字发到网页，空着发送 = 回车';

const handoffTitle = '需要你来';
const handoffDoneLabel = '完成，交还';
const handoffCancelLabel = '做不了';

/// v2.28 浏览器服务本身不能用（卡上 down）：标题 + 怎么办（原因在 down 里）。网页版 lib/browserView.ts 同文案。
const browserDownTitle = '云浏览器现在用不了';
const browserDownHint = '是服务器上的浏览器服务出了问题，不是网页的问题。修好后让助手再打开一次。';

/// 卡头右边的按钮：打开全屏接管页（v2.82 卡片上不再能直接操作，只是预览 + 入口）。
const takeoverLabel = '接管';

/// 接管结束后卡头下的一行小字；还在等 → 空（显示接管条）。
String handoffStateLine(BrowserHandoff h) => switch (h.state) {
      'done' => '你已交还，助手接着做',
      'cancelled' => '你没有接管，助手会换个办法',
      'expired' => '等太久没回应，已取消',
      _ => '',
    };

/// 截图刷新节奏：接管页开着（或助手在等你）→ 快；页面在打开 → 中；只是看着 → 慢。
Duration screenInterval({required bool control, required bool live}) =>
    control ? Timing.screenFast : live ? Timing.screenOpening : Timing.screenIdle;

/// 只是看着超过 screenPauseAfter 就暂停刷新；在操作、在打开、在等你接管都不停。
bool screenShouldPause({required Duration idle, required bool control, required bool live, required bool pending}) =>
    !control && !live && !pending && idle >= Timing.screenPauseAfter;

/// 读屏：takeover = 在接管页里（点哪里就点网页哪里）；卡片上 = 预览，点开接管。
String browserScreenSemantics({required bool takeover, required bool paused, String? site}) {
  final where = site == null ? '浏览器' : '$site 的浏览器';
  if (paused) return '$where画面已暂停，轻点继续';
  return takeover ? '$where实时画面，已接管，点哪里就点网页哪里' : '$where实时画面，点开接管';
}

/// 截图在 [box] 里按 contain 摆放的位置（上下或左右留边）。
Rect takeoverFit(Size box) {
  final w = box.width / box.height > browserAspect ? box.height * browserAspect : box.width;
  final h = w / browserAspect;
  return Rect.fromLTWH((box.width - w) / 2, (box.height - h) / 2, w, h);
}

/// 接管页屏幕上的一点 → 网页上的 0–1 坐标。画面先 contain 进 [box]，再按左上角为原点放大 [scale]、平移 [pan]。
/// 点在截图外（留边处）→ null，不发点击。
Offset? takeoverPoint(Offset local, Size box, {double scale = 1, Offset pan = Offset.zero}) {
  final scene = (local - pan) / scale;
  final img = takeoverFit(box);
  if (!img.contains(scene)) return null;
  return Offset((scene.dx - img.left) / img.width, (scene.dy - img.top) / img.height);
}

/// 平移别把画面拖出屏：放大后边缘最多贴住屏边；没放大就不能平移。
Offset takeoverClampPan(Offset pan, Size box, double scale) => Offset(
      pan.dx.clamp(box.width - box.width * scale, 0).toDouble(),
      pan.dy.clamp(box.height - box.height * scale, 0).toDouble(),
    );

/// 手指在屏上划过的距离 → 网页要滚的像素（手指往上划 = 网页往下滚，所以取反）。放大后同样一指滚得少，跟手。
double takeoverScrollPixels(double fingerDelta, Size box, double scale) =>
    -fingerDelta / (takeoverFit(box).height * scale) * browserView.height;

/// 卡上文件小条的第二行：传上去的 → “已传到网页”；下载的 → “已存到 downloads”（所在文件夹）。
String browserFileLine(BrowserFile f) {
  if (f.uploaded) return '已传到网页';
  final slash = f.path.lastIndexOf('/');
  return slash > 0 ? '已存到 ${f.path.substring(0, slash)}' : '已存到工作区';
}

String browserFileSemantics(BrowserFile f) => '${f.name}，${browserFileLine(f)}，点开查看';
