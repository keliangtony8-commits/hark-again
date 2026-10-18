// v3.5.2 流光壁纸的“贴图”着色器：sky.frag 每个时钟步（33ms）在 1/4 分辨率离屏画一张图（ui/sky.dart SkyFrames），
// 整屏壁纸和渐隐条都用这里把它双线性放大贴上：每像素 1 次采样 + 原来那份抖动 + 渐隐 alpha（不再每帧每像素 5 次 exp）。
// 柔光是半径上百像素的高斯、底色是平滑竖向渐变，1/4 分辨率双线性放大后和原图只差量化级；抖动在这里按屏幕像素加（= sky.frag skyDither），不出色带。
#include <flutter/runtime_effect.glsl>

uniform vec2 uSize;      // 画布大小（逻辑像素）
uniform vec2 uOrigin;    // 画布左上角在屏幕上的位置（逻辑像素）
uniform vec2 uScreen;    // 屏幕大小（同单位）= 离屏图覆盖的范围
uniform vec3 uFade;      // = sky.frag uFade
uniform sampler2D uSky;  // 离屏图（整屏，1/4 分辨率，未抖动）

out vec4 fragColor;

// = sky.frag skyDither（同一个公式，按屏幕坐标）
vec3 skyDither(vec3 col, vec2 px) {
  float n = fract(52.9829189 * fract(dot(px, vec2(0.06711056, 0.00583715))));
  return col + (n - 0.5) / 255.0;
}

void main() {
  vec2 px = FlutterFragCoord().xy + uOrigin;
  vec2 uv = px / uScreen;
#ifdef IMPELLER_TARGET_OPENGLES
  uv.y = 1.0 - uv.y; // toImageSync 的图在 GLES 下上下颠倒（Flutter 着色器文档）
#endif
  vec3 col = skyDither(texture(uSky, uv).rgb, px);

  float a = 1.0;
  if (uFade.x > 0.5) {
    float x = clamp((px.y - uFade.y) / (uFade.z - uFade.y), 0.0, 1.0);
    a = 1.0 - x * x * (3.0 - 2.0 * x);
  }
  fragColor = vec4(col * a, a); // 预乘 alpha
}
