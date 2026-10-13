// 改动卡（v1.68）的纯规则：标题、合计、能不能撤销、读屏、撤销结果的话。界面在 blocks/changes_block.dart；
// 网页版同款 lib/changes.ts；后端规则在 app/turn_changes.py。
import 'activity.dart';
import 'block.dart';
import 'message.dart';

int changesCount(ChangesBlock b) => b.files.length + b.more;

/// 改动是谁的：一轮回复（v1.68 消息里的改动卡）还是一个后台任务（v2.18 任务卡里嵌的那份）。只影响措辞。
enum ChangesScope { turn, job }

/// 任务卡要不要画改动区：结束了且列出了文件。
bool jobChangesShown(ChangesBlock? b) => b != null && b.files.isNotEmpty;

/// “改了 3 个文件” / “已撤销 3 个文件的改动”；任务卡里是 “任务改了 3 个文件”。
String changesTitle(ChangesBlock b, {ChangesScope scope = ChangesScope.turn}) => b.undone
    ? '已撤销 ${changesCount(b)} 个文件的改动'
    : '${scope == ChangesScope.job ? '任务' : ''}改了 ${changesCount(b)} 个文件';

/// 撤销前确认框的标题和正文。
(String, String) changesConfirm(ChangesBlock b, {ChangesScope scope = ChangesScope.turn}) => scope == ChangesScope.job
    ? ('撤销这个任务的文件改动？', '${changesCount(b)} 个文件会回到任务开始前的样子；它新建的文件会被删掉。')
    : ('撤销这一轮的文件改动？', '${changesCount(b)} 个文件会回到助手改之前的样子；这一轮新建的文件会被删掉。');

/// 合计 “+12 −3”（只算列出的）。
(int, int) changesTotals(ChangesBlock b) =>
    b.files.fold((0, 0), (t, f) => (t.$1 + f.added, t.$2 + f.removed));

bool changesUndoable(ChangesBlock b) => b.token.isNotEmpty && !b.undone;

/// 卡底的小字：太大的文件不能撤销；v2.14 其中几个是命令改的（撤销同样覆盖）；
/// v2.18 任务那份：同时段还有别的后台任务 / 几个文件归了这期间的对话回合。
String? changesNote(ChangesBlock b, {ChangesScope scope = ChangesScope.turn}) {
  final big = b.files.where((f) => f.big).length;
  final cmd = b.files.where((f) => f.command).length;
  if (b.undone) return scope == ChangesScope.job ? '文件已回到任务开始前的样子' : '文件已回到这一轮之前的样子';
  final parts = [
    if (b.token.isEmpty) '文件太大，没有留撤销记录' else if (big > 0) '$big 个大文件不能撤销',
    if (cmd > 0) '其中 $cmd 个是命令改的',
    if (b.overlap) '同时还有别的后台任务，可能也算进来了',
    if (b.shared > 0) '另有 ${b.shared} 个文件这期间对话里也改过，算在那一轮',
  ];
  return parts.isEmpty ? null : parts.join(' · ');
}

/// 每行右侧状态：“已不在”“大文件”、v2.16 只改了权限（+0 −0）时那句权限的话，或空（显示 +N −M）。
String? changeTag(FileChange f) =>
    f.deleted ? '已不在' : (f.big ? '大文件' : (f.mode.isNotEmpty && f.added == 0 && f.removed == 0 ? f.mode : null));

String changesSemantics(ChangesBlock b, {ChangesScope scope = ChangesScope.turn}) {
  final (a, r) = changesTotals(b);
  return '${changesTitle(b, scope: scope)}，增加 $a 行，删除 $r 行：${b.files.map((f) => f.path).join('、')}';
}

/// 撤销失败时给用户的话（服务器的 detail 已经是中文；断网另说）。
String undoErrorText(Object e) {
  final s = e.toString();
  return s.isEmpty ? '没撤销成功，稍后再试' : s;
}

/// `/diff`（v1.89）：最近一条带改动卡的消息 → (消息 id, 那张卡)；没有 → null。
(String, ChangesBlock)? latestChanges(List<Message> messages) {
  for (final m in messages.reversed) {
    for (final b in m.blocks.reversed) {
      if (b is ChangesBlock && b.files.isNotEmpty) return (m.id, b);
    }
  }
  return null;
}

/// 跳过去时的提示条：“改了 3 个文件 · +12 −3”（撤销过的照标题）。
String latestChangesToast(ChangesBlock b) {
  if (b.undone) return changesTitle(b);
  final (a, r) = changesTotals(b);
  return '${changesTitle(b)} · +$a −$r';
}

const noChangesToast = '这段对话里助手还没改过文件';
