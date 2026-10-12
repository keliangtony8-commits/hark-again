// 改动卡（v1.68）的纯规则：标题、合计、能不能撤销、读屏、撤销结果的话。界面在 blocks/changes_block.dart；
// 网页版同款 lib/changes.ts；后端规则在 app/turn_changes.py。
import 'activity.dart';
import 'block.dart';

int changesCount(ChangesBlock b) => b.files.length + b.more;

/// “改了 3 个文件” / “已撤销 3 个文件的改动”。
String changesTitle(ChangesBlock b) => b.undone ? '已撤销 ${changesCount(b)} 个文件的改动' : '改了 ${changesCount(b)} 个文件';

/// 合计 “+12 −3”（只算列出的）。
(int, int) changesTotals(ChangesBlock b) =>
    b.files.fold((0, 0), (t, f) => (t.$1 + f.added, t.$2 + f.removed));

bool changesUndoable(ChangesBlock b) => b.token.isNotEmpty && !b.undone;

/// 卡底的小字：太大的文件不能撤销；命令改的文件不在这里。
String? changesNote(ChangesBlock b) {
  final big = b.files.where((f) => f.big).length;
  if (b.undone) return '文件已回到这一轮之前的样子';
  if (b.token.isEmpty) return '文件太大，没有留撤销记录';
  if (big > 0) return '$big 个大文件不能撤销';
  return null;
}

/// 每行右侧状态：“新建”“已删除”“大文件”或空（显示 +N −M）。
String? changeTag(FileChange f) => f.deleted ? '已不在' : (f.big ? '大文件' : null);

String changesSemantics(ChangesBlock b) {
  final (a, r) = changesTotals(b);
  return '${changesTitle(b)}，增加 $a 行，删除 $r 行：${b.files.map((f) => f.path).join('、')}';
}

/// 撤销失败时给用户的话（服务器的 detail 已经是中文；断网另说）。
String undoErrorText(Object e) {
  final s = e.toString();
  return s.isEmpty ? '没撤销成功，稍后再试' : s;
}
