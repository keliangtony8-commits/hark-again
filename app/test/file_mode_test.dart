// v2.16 改动卡的权限位：后端给 mode 那句话，客户端只原样显示（只改权限时代替 +0 −0）。
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/changes.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('只改权限：右侧显示那句权限的话', () {
    final f = FileChange.fromJson({'path': 'run.sh', 'added': 0, 'removed': 0, 'diff': '', 'command': true, 'mode': '加了可执行'})!;
    expect(f.mode, '加了可执行');
    expect(changeTag(f), '加了可执行');
    expect(f.semantics, contains('加了可执行'));
  });

  test('内容也改了：照常 +N −M，权限只进读屏', () {
    final f = FileChange.fromJson({'path': 'run.sh', 'added': 1, 'removed': 1, 'diff': '-a\n+b', 'mode': '权限 755→600'})!;
    expect(changeTag(f), isNull);
    expect(f.semantics, contains('权限 755→600'));
  });

  test('老服务器没有 mode / 删掉的文件', () {
    expect(FileChange.fromJson({'path': 'a', 'added': 1})!.mode, '');
    expect(changeTag(FileChange.fromJson({'path': 'a', 'deleted': true, 'mode': 'x'})!), '已不在');
  });
}
