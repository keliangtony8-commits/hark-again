// 流光壁纸（v3.3 起，Toyuis 自写，思路参考 mesh_gradient (MIT) 的“底色 + 几团柔光缓慢流动”，未复制其代码）。
// v3.5.1：五团柔光、各自漂移 + 旋转 + 伸缩、颜色在五个色相间轮转（用户 10-18：“要清楚地看到它在流动”“白天颜色不止一种”）。
// 只跟时间有关的量（每团的中心、旋转、伸缩、此刻的颜色）在 Dart 里每帧算一次（ui/sky.dart，= theme/tokens.dart SkyBlob.at / SkyPhase.hue），
// 着色器每像素只做：竖向底色 + 5 次高斯（每次一个 exp）+ 抖动，和 v3.3 的 3 次 exp 同一量级。
// v3.5.2：App 里平时不直接上屏，而是每个时钟步在 1/4 分辨率离屏画一张图（uFade.x = -1），再由 sky_blit.frag 放大贴图 + 抖动。
// uFade：> 0 时只画一条渐隐（ShellPage 的上沿渐隐：clear 以上全不透明、到 solid 渐成透明；v3.5 solid < clear 时是底部浮条下的渐隐），代替整页 ShaderMask 离屏层。
#include <flutter/runtime_effect.glsl>

uniform vec2 uSize;      // 画布大小（逻辑像素）
uniform vec2 uOrigin;    // 画布左上角在屏幕上的位置（逻辑像素），让顶条和整屏壁纸逐像素对齐
uniform vec2 uScreen;    // 屏幕大小（同单位）
uniform vec3 uFade;      // x = 是否渐隐条（0/1），y = 全不透明到这一行，z = 到这一行完全透明（屏幕坐标）
uniform vec3 uTop;
uniform vec3 uBottom;
// 每团柔光：O = 中心（屏高为单位，x 已乘宽高比），M = 2×2 矩阵（两条轴的缩放 × 旋转，按行），C = 此刻的颜色 rgb + 强度 a
uniform vec2 uO0;
uniform vec4 uM0;
uniform vec4 uC0;
uniform vec2 uO1;
uniform vec4 uM1;
uniform vec4 uC1;
uniform vec2 uO2;
uniform vec4 uM2;
uniform vec4 uC2;
uniform vec2 uO3;
uniform vec4 uM3;
uniform vec4 uC3;
uniform vec2 uO4;
uniform vec4 uM4;
uniform vec4 uC4;

out vec4 fragColor;

// ---- 流光核心 BEGIN（与网页 frontend/src/lib/skyGl.ts 里同名段落逐字相同，frontend scripts/check-contrast.mjs 查）----
// 一团柔光：移到中心后乘 2×2 矩阵 M（= 两条轴的缩放 × 旋转，Dart / TS 每帧算好），q = |M·d|²，高斯 exp(-q) × 强度
vec3 skyBlob(vec3 col, vec2 p, vec2 o, vec4 m, vec4 c) {
  vec2 d = p - o;
  vec2 e = vec2(dot(m.xy, d), dot(m.zw, d));
  return mix(col, c.rgb, exp(-dot(e, e)) * c.a);
}

vec3 skyColor(vec2 uv, float aspect) {
  vec2 p = vec2(uv.x * aspect, uv.y);
  vec3 col = mix(uTop, uBottom, smoothstep(0.0, 1.0, pow(clamp(uv.y, 0.0, 1.0), 0.75)));
  col = skyBlob(col, p, uO0, uM0, uC0);
  col = skyBlob(col, p, uO1, uM1, uC1);
  col = skyBlob(col, p, uO2, uM2, uC2);
  col = skyBlob(col, p, uO3, uM3, uC3);
  col = skyBlob(col, p, uO4, uM4, uC4);
  return col;
}

// 抖动：±0.5/255，消掉大面积柔和渐变的色带。用 interleaved gradient noise（Jimenez 2014，公开公式）：
// 只有乘加和 fract，比原来的 sin 哈希便宜，噪声分布也更均匀
vec3 skyDither(vec3 col, vec2 px) {
  float n = fract(52.9829189 * fract(dot(px, vec2(0.06711056, 0.00583715))));
  return col + (n - 0.5) / 255.0;
}
// ---- 流光核心 END ----

void main() {
  vec2 px = FlutterFragCoord().xy + uOrigin;
  vec2 uv = px / uScreen;              // 0..1，按屏幕
  vec3 col = skyColor(uv, uScreen.x / uScreen.y);
  // v3.5.2：uFade.x < 0 = 离屏低分辨率图（ui/sky.dart SkyFrames）：不抖动、不透明，抖动在 sky_blit.frag 按屏幕像素加
  if (uFade.x < -0.5) {
    fragColor = vec4(col, 1.0);
    return;
  }
  col = skyDither(col, px);

  float a = 1.0;
  if (uFade.x > 0.5) {
    // = Sky.fadeAlpha：z < y 时是底部渐隐（方向反过来）；不用 smoothstep(y, z)，因为 edge0 > edge1 在 GLSL 里没有定义
    float x = clamp((px.y - uFade.y) / (uFade.z - uFade.y), 0.0, 1.0);
    a = 1.0 - x * x * (3.0 - 2.0 * x);
  }
  fragColor = vec4(col * a, a); // 预乘 alpha
}
