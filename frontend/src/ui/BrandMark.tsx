// 品牌图标（用户 2026-10-14 指定）：网页内唯一入口；图由 brand/make_icons.py 生成，与 App 图标同源。
export default function BrandMark({ size = 44 }: { size?: number }) {
  return <img className="brand-mark" src="/icons/mark.png" width={size} height={size} alt="" aria-hidden="true" />;
}
