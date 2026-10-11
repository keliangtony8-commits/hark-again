// 没图时占位用的“字标”：名字的第一个字（跳过空白和标点），大写。= App models/block.dart monogramOf。
export function monogramOf(name: string): string {
  for (const c of name) if (/[\p{L}\p{N}]/u.test(c)) return c.toUpperCase();
  return "·";
}
