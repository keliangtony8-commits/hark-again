// v2.20 命令借用已连接账户：任务卡 / “这台电脑”行 / 读屏都标“用 GitHub 账户”（后端 app/command_credentials.py）。
import 'package:assistant/models/block.dart';
import 'package:assistant/models/job.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Map<String, dynamic> wire({Object? creds}) => {
        'id': 'j1', 'title': '同步仓库', 'command': 'python sync.py', 'state': 'running', 'elapsed': 5,
        'keep_alive': true, 'credentials': ?creds,
      };

  test('解析：块和快照都认 credentials，坏形状当没借', () {
    expect(JobInfo.fromJson(wire(creds: ['GitHub'])).credentials, ['GitHub']);
    expect(JobInfo.fromJson(wire()).credentials, isEmpty);
    expect(JobInfo.fromJson(wire(creds: 'GitHub')).credentials, isEmpty);
    expect(JobInfo.fromJson(wire(creds: ['GitHub', 3])).credentials, ['GitHub']);
    final b = JobBlock.fromJson({...wire(creds: ['GitHub', 'Google']), 'type': 'job'});
    expect(b.credentials, ['GitHub', 'Google']);
    expect(JobInfo.fromBlock(b).credentials, ['GitHub', 'Google']);
    expect(JobInfo.fromBlock(b).withElapsed(const Duration(seconds: 9)).credentials, ['GitHub', 'Google']);
  });

  test('措辞：底部行、电脑页行、读屏', () {
    expect(jobCredentialsLabel(const []), isNull);
    expect(jobCredentialsLabel(const ['GitHub', 'Google']), '用 GitHub、Google 账户');
    final j = JobInfo.fromJson(wire(creds: ['GitHub']));
    expect(jobFootLabel(j), '常驻 · 运行中 · 用 GitHub 账户');
    expect(jobRowSubtitle(j), startsWith('常驻 · 用 GitHub 账户 · 运行 5 秒'));
    expect(jobSemantics(j), contains('，用 GitHub 账户，用时'));
    final plain = JobInfo.fromJson(wire());
    expect(jobFootLabel(plain), '常驻 · 运行中');
    expect(jobSemantics(plain), isNot(contains('账户')));
  });
}
