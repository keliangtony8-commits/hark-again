// 浏览器画面卡 + 接管页的纯规则（v1.29 / v2.82 / v2.89）：接管条文案、实时画面连接状态机（WS 推流，断了退避重连）、
// 读屏句子、接管页的坐标换算（缩放平移后点到网页哪里）。
// 网页版 lib/browserView.ts 同一套；卡片在 blocks/browser_block.dart，接管页在 blocks/browser_takeover.dart。
import 'dart:ui';

import '../theme/tokens.dart';
import 'block.dart';

/// 浏览器服务的视口（browser/service.py VIEW）：画面就是这个比例。
const browserView = Size(1280, 800);
const browserAspect = 1280 / 800;

/// 接管页最多放大几倍（再大画面就糊成色块了）。
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

/// 实时画面连接（v2.89 §M，一条 WS：下行 JPEG 帧、上行接管输入；= 网页 lib/browserView.ts LiveState）。
/// connecting 刚连 / live 有画面在推 / reconnecting 断了在退避重连 / closed 浏览器已关闭（等用户点“重新打开”）/ down 浏览器服务不可用。
enum LiveState { connecting, live, reconnecting, closed, down }

/// 服务器的关闭码（= backend routes/browser.py、browser/live.py CLOSE_*）。
const liveCloseUnauthorized = 4401, liveCloseNotOpen = 4404, liveCloseDown = 4503;

/// 连接关了之后进哪个状态。还在打开（block.live）时“没开”是正常的 → 接着重连；token 失效交给聊天连接去登出。
LiveState liveStateAfterClose(int? code, {required bool opening}) => switch (code) {
      liveCloseNotOpen => opening ? LiveState.reconnecting : LiveState.closed,
      liveCloseDown => LiveState.down,
      liveCloseUnauthorized => LiveState.closed,
      _ => LiveState.reconnecting,
    };

/// 第 [attempt] 次重连前等多久（从 0 起）：1、2、4、8、15、15… 秒。
Duration liveRetryDelay(int attempt) {
  final d = Timing.liveRetryMin * (1 << attempt.clamp(0, 8));
  return d > Timing.liveRetryMax ? Timing.liveRetryMax : d;
}

/// 画面上的一句状态；live 且有画面 → null（不盖东西）。[hasFrame] = 已经有过一帧（重连时先留着最后一帧）。
String? liveStatusLine(LiveState s, {required bool hasFrame, required bool opening, String? site}) => switch (s) {
      LiveState.live => hasFrame ? null : '正在载入画面…',
      LiveState.connecting => hasFrame ? null : opening ? '正在打开${site == null ? '网页' : ' $site'}…' : '正在连接画面…',
      LiveState.reconnecting => opening && !hasFrame ? '正在打开${site == null ? '网页' : ' $site'}…' : '正在重连…',
      LiveState.closed => liveClosedTitle,
      LiveState.down => browserDownTitle,
    };

const liveClosedTitle = '浏览器已关闭';
const liveReopenLabel = '重新打开';

/// closed / down 时画面上给一个“重新打开”（用存好的登录回到最后网址）。
bool liveCanReopen(LiveState s) => s == LiveState.closed || s == LiveState.down;

/// 读屏：takeover = 在接管页里（点哪里就点网页哪里）；卡片上 = 预览，点开接管。
String browserScreenSemantics({required bool takeover, String? site}) {
  final where = site == null ? '浏览器' : '$site 的浏览器';
  return takeover ? '$where实时画面，已接管，点哪里就点网页哪里' : '$where实时画面，点开接管';
}

/// 点一下按住了多久（毫秒，手指 / 鼠标真实的按下 → 抬起）：随 click 发给服务端，它按这个时长按住再抬起（browser/live.py）。
/// 没量到（缺一头）→ null，不带 hold，服务端用默认值。= 网页 lib/browserView.ts takeoverHold。
int? takeoverHoldMs(Duration? down, Duration? up) {
  if (down == null || up == null) return null;
  final ms = (up - down).inMicroseconds / 1000;
  return ms < 0 ? 0 : ms.round();
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
