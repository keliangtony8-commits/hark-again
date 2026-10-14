"""品牌图标唯一来源：brand/source.png（用户 2026-10-14 指定）→ 生成 Android/iOS/Web/App 内所有图标。
改图标只换 source.png 后运行：python3 brand/make_icons.py（在 assistant/ 下）。"""
import os
from PIL import Image, ImageDraw, ImageFilter
src = Image.open('brand/source.png').convert('RGB')
rows = [src.getpixel((240, y)) for y in range(240, 781)]  # 底板纵向渐变
N = 1024
master = Image.new('RGB', (N, N))
d = ImageDraw.Draw(master)
for y in range(N):
    d.line([(0, y), (N, y)], fill=rows[int(y / (N - 1) * (len(rows) - 1))])
crop = src.crop((232, 228, 792, 788))
S = int(560 * 1.30)
crop = crop.resize((S, S), Image.LANCZOS)
m = Image.new('L', (S, S), 0)
ImageDraw.Draw(m).ellipse((S * .06, S * .06, S * .94, S * .94), fill=255)
m = m.filter(ImageFilter.GaussianBlur(S * .06))
o = (N - S) // 2
master.paste(crop, (o, o + 4), m)

def rounded(size, r=.225):
    im = master.resize((size, size), Image.LANCZOS).convert('RGBA')
    k = 4
    mk = Image.new('L', (size * k,) * 2, 0)
    ImageDraw.Draw(mk).rounded_rectangle((0, 0, size * k - 1, size * k - 1), radius=int(size * k * r), fill=255)
    im.putalpha(mk.resize((size, size), Image.LANCZOS))
    return im

def sq(size):
    return master.resize((size, size), Image.LANCZOS)

res = 'app/android/app/src/main/res/'
for dpi, sz in dict(mdpi=48, hdpi=72, xhdpi=96, xxhdpi=144, xxxhdpi=192).items():
    rounded(sz).save(f'{res}mipmap-{dpi}/ic_launcher.png')
    big = int(sz * 108 / 48)
    sq(big).save(f'{res}mipmap-{dpi}/ic_launcher_background.png')
    Image.new('RGBA', (big, big), (0, 0, 0, 0)).save(f'{res}mipmap-{dpi}/ic_launcher_foreground.png')
ios = 'app/ios/Runner/Assets.xcassets/AppIcon.appiconset/'
for f in os.listdir(ios):
    if f.endswith('.png'):
        sq(Image.open(ios + f).size[0]).save(ios + f)
rounded(256).save('app/assets/brand/mark.png')
pub = 'frontend/public/'
rounded(64).save(pub + 'favicon.png')
sq(180).save(pub + 'icons/apple-touch-icon.png')
for s in (192, 512):
    sq(s).save(pub + f'icons/icon-{s}.png')
rounded(128).save(pub + 'icons/mark.png')
rounded(512).save('/tmp/brand_preview.png')
