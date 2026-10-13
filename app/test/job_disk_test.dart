import 'package:assistant/models/block.dart';
import 'package:assistant/models/job.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const mb = 1 << 20;
  final raw = {
    'log': 300 * 1024,
    'written': 2 * mb,
    'files': 12,
    'top': [
      {'path': 'images/', 'size': 2 * mb - 10},
      {'path': '.home/', 'size': 10},
      'junk',
      {'path': '', 'size': 3},
    ],
    'overlap': 0,
    'partial': false,
  };

  test('tryParse validates', () {
    final d = JobDisk.tryParse(raw)!;
    expect(d.files, 12);
    expect(d.top.map((t) => t.path), ['images/', '.home/']);
    for (final bad in [null, 'x', <String, Object>{}, {...raw, 'log': -1}, {...raw, 'files': 'x'}]) {
      expect(JobDisk.tryParse(bad), isNull, reason: '$bad');
    }
    expect(JobDisk.tryParse({...raw}..remove('overlap'))!.overlap, 0);
  });

  test('labels', () {
    final d = JobDisk.tryParse(raw)!;
    expect(jobDiskLabel(d), '写入 2.0 MB · 12 个文件 · 最多 images/ · 日志 300 KB');
    expect(jobDiskDetail(d), '运行期间新写或改过 12 个文件，共 2.0 MB：images/ 2.0 MB、装的软件 10 B；日志 300 KB');
    final shared = JobDisk.tryParse({...raw, 'overlap': 2, 'partial': true})!;
    expect(jobDiskLabel(shared), '写入 2.0 MB+ · 12+ 个文件 · 最多 images/ · 日志 300 KB · 含同时段任务');
    expect(jobDiskDetail(shared), endsWith('（文件太多只数了一部分；同时段还有 2 个任务在跑，可能含它们写的）'));
    final none = JobDisk.tryParse({'log': 2 * mb, 'written': 0, 'files': 0, 'overlap': 1})!;
    expect(jobDiskLabel(none), '没写新文件 · 日志 2.0 MB');
    expect(jobDiskDetail(none), startsWith('运行期间没有新写文件；日志 2.0 MB'));
    expect(jobDiskSemantics(none), '没写新文件，日志 2.0 MB');
  });

  test('shown only when it matters', () {
    expect(jobDiskShown(null), isFalse);
    expect(jobDiskShown(JobDisk.tryParse({'log': 100, 'written': 0, 'files': 0})), isFalse);
    expect(jobDiskShown(JobDisk.tryParse({'log': mb, 'written': 0, 'files': 0})), isTrue);
    expect(jobDiskShown(JobDisk.tryParse({'log': 100, 'written': 5, 'files': 1})), isTrue);
  });

  test('flows from block and api', () {
    final b = JobBlock.fromJson({'id': 'j1', 'title': 't', 'command': 'c', 'state': 'done', 'disk': raw});
    final j = JobInfo.fromBlock(b);
    expect(j.disk!.written, 2 * mb);
    expect(j.withElapsed(const Duration(seconds: 3)).disk, same(j.disk));
    expect(jobSemantics(j), contains('写入 2.0 MB，12 个文件'));
    final api = JobInfo.fromJson({'id': 'j1', 'state': 'running', 'disk': null});
    expect(api.disk, isNull);
    expect(jobSemantics(api), isNot(contains('写入')));
  });
}
