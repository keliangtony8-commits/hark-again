// 流光壁纸（v3.3，Toyuis 自写，思路参考 mesh_gradient (MIT) 的“底色 + 几团柔光缓慢流动”，未复制其代码）：
// 竖向底色渐变 + 三团高斯柔光沿各自的慢速椭圆轨道漂移 + 轻微抖动去色带。每像素只有 3 次 exp，整屏 < 0.5ms。
// uFade：> 0 时只画顶部一条（ShellPage 的上沿渐隐：clear 以上全不透明、到 solid 渐成透明），代替整页 ShaderMask 离屏层。
#include <flutter/runtime_effect.glsl>

uniform vec2 uSize;      // 画布大小（逻辑像素）
uniform vec2 uOrigin;    // 画布左上角在屏幕上的位置（逻辑像素），让顶条和整屏壁纸逐像素对齐
uniform vec2 uScreen;    // 屏幕大小（同单位）
uniform float uTime;     // 秒
uniform vec3 uTop;
uniform vec3 uBottom;
uniform vec3 uBlobA;
uniform vec3 uBlobB;
uniform vec3 uBlobC;
uniform vec3 uFade;      // x = 是否渐隐条（0/1），y = 全不透明到这一行，z = 到这一行完全透明（屏幕坐标）

out vec4 fragColor;

float blob(vec2 p, vec2 c, float r) {
  vec2 d = p - c;
  return exp(-dot(d, d) / (r * r));
}

void main() {
  vec2 px = FlutterFragCoord().xy + uOrigin;
  vec2 uv = px / uScreen;              // 0..1，按屏幕
  float aspect = uScreen.x / uScreen.y;
  vec2 p = vec2(uv.x * aspect, uv.y);  // 圆是圆

  float t = uTime;
  vec3 col = mix(uTop, uBottom, smoothstep(0.0, 1.0, pow(clamp(uv.y, 0.0, 1.0), 0.75))); // = Sky.ramp
  vec2 ca = vec2((0.25 + 0.18 * sin(t * 0.050)) * aspect, 0.28 + 0.10 * cos(t * 0.041));
  vec2 cb = vec2((0.78 + 0.16 * cos(t * 0.037)) * aspect, 0.52 + 0.14 * sin(t * 0.046));
  vec2 cc = vec2((0.45 + 0.22 * sin(t * 0.029 + 1.7)) * aspect, 0.86 + 0.08 * cos(t * 0.034));
  col = mix(col, uBlobA, 0.75 * blob(p, ca, 0.42));
  col = mix(col, uBlobB, 0.65 * blob(p, cb, 0.38));
  col = mix(col, uBlobC, 0.70 * blob(p, cc, 0.46));

  // 抖动：±0.5/255，消掉大面积渐变的色带
  float n = fract(sin(dot(px, vec2(12.9898, 78.233))) * 43758.5453);
  col += (n - 0.5) / 255.0;

  float a = 1.0;
  if (uFade.x > 0.5) {
    a = 1.0 - smoothstep(uFade.y, uFade.z, px.y);
  }
  fragColor = vec4(col * a, a); // 预乘 alpha
}
