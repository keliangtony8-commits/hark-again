// “我的电脑”和“用量与花费”的假数据（v3.5.1，用户 10-18 00:24 真机截图同量级）：perf_frame_test 的滚动用例和截图共用。
// 我的电脑：2 个常驻服务、3 个端口、内存 4 个占用者 + 其它、8 个程序、磁盘拆分、12 个 pip 工具、2 个写盘任务、整台服务器；
// 浏览器登录 3 个网站；主机模式关。用量：本月 22M token / 1297 次、只有 15–18 日有数、8 个最花钱的对话（5 个已删）、5 个模型、未配单价。
const _mb = 1 << 20;

String _ago(Duration d) => DateTime.now().subtract(d).toUtc().toIso8601String();

Map<String, dynamic> computerFixture({double cpu = 26, int tick = 0}) => {
      'workspace': 'me',
      'name': '我的文件',
      'sandbox': {
        'state': 'running',
        'memory_used': (198.5 * _mb).round() + tick * 4096, // 真机上每次轮询内存都在小幅变
        'memory_limit': 512 * _mb,
        'cpu_percent': cpu,
        'oom_kills': 0,
        'processes': [
          {'pid': 1103487, 'cpu': 58.0, 'memory': (13.2 * _mb).round(), 'elapsed': 0, 'command': "python3 -c import json, os, sys; print(json.dumps(stat()))"},
          {'pid': 1103493, 'cpu': 50.0, 'memory': (3.1 * _mb).round(), 'elapsed': 0, 'command': 'bash -c ps -eo pid=,pgid=,pcpu=,rss=,etimes=,args='},
          {'pid': 2001, 'cpu': 0.0, 'memory': (18.3 * _mb).round(), 'elapsed': 290100 + tick, 'command': '/usr/bin/python3 monitor_app.py'},
          {'pid': 2002, 'cpu': 0.0, 'memory': (6.3 * _mb).round(), 'elapsed': 295500 + tick, 'command': '/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0'},
          {'pid': 2003, 'cpu': 0.0, 'memory': (2.1 * _mb).round(), 'elapsed': 290100 + tick, 'command': 'sh -c python3 monitor_app.py'},
          {'pid': 2004, 'cpu': 0.0, 'memory': (1.9 * _mb).round(), 'elapsed': 290000 + tick, 'command': 'node /srv/web/server.js --port 42139'},
          {'pid': 2005, 'cpu': 0.0, 'memory': (1.2 * _mb).round(), 'elapsed': 290000 + tick, 'command': 'tail -f /var/log/app.log'},
          {'pid': 2006, 'cpu': 0.0, 'memory': (0.8 * _mb).round(), 'elapsed': 300000 + tick, 'command': 'sleep infinity'},
        ],
      },
      'disk_used': (7.7 * _mb).round(),
      'disk_limit': 3 << 30,
      'disk_level': 'ok',
      'storage': {'files': (1.2 * _mb).round(), 'installed': (6.0 * _mb).round(), 'logs': (5 << 10), 'spill': 0, 'cache': (0.5 * _mb).round(), 'cleanable': 1 << 10},
      'tools': [
        for (final n in ['flask', 'requests', 'psutil', 'numpy', 'pandas', 'jinja2', 'werkzeug', 'click', 'itsdangerous', 'markupsafe', 'blinker', 'urllib3'])
          {'kind': 'pip', 'name': n, 'version': '1.0.0'},
      ],
      'ports': [
        {'port': 5000, 'command': 'python3 monitor_app.py'},
        {'port': 8080, 'command': 'python3 -m http.server 8080 --bind 0.0.0.0'},
        {'port': 42139, 'command': ''},
      ],
      'services': [
        {'id': 'svc1', 'title': '启动库存监控网页服务', 'command': 'python3 monitor_app.py', 'state': 'running', 'keep_alive': true, 'health': 'up',
         'ports': [5000], 'uptime': 290100 + tick, 'usage': {'cpu': 0.0, 'cpu_seconds': 12.0, 'memory': (13.7 * _mb).round(), 'processes': 3}},
        {'id': 'svc2', 'title': 'python3 -m http.server 8080 --bind 0.0.0.0', 'command': 'python3 -m http.server 8080', 'state': 'running', 'keep_alive': true,
         'health': 'up', 'ports': [8080], 'uptime': 295500 + tick, 'usage': {'cpu': 0.0, 'cpu_seconds': 3.0, 'memory': (6.3 * _mb).round(), 'processes': 3}},
      ],
      'running_jobs': [],
      'memory': {
        'used': (198.5 * _mb).round() + tick * 4096,
        'limit': 512 * _mb,
        'rows': [
          {'kind': 'service', 'id': 'svc1', 'title': '启动库存监控网页服务', 'memory': (13.7 * _mb).round(), 'processes': 3, 'share': 0.07},
          {'kind': 'process', 'pid': 1103487, 'title': 'python3 -c import json, os, sys', 'memory': (13.2 * _mb).round() + tick * 20480, 'share': 0.07},
          {'kind': 'service', 'id': 'svc2', 'title': 'python3 -m http.server 8080 --bind 0.0.0.0', 'memory': (6.3 * _mb).round(), 'processes': 3, 'share': 0.03},
          {'kind': 'process', 'pid': 1103493, 'title': 'bash -c ps -eo pid=,pgid=', 'memory': (3.1 * _mb).round(), 'share': 0.02},
        ],
        'other': (162.1 * _mb).round(),
      },
      'disk_jobs': [
        {'id': 'dj1', 'title': '安装监控页依赖', 'command': 'pip install flask psutil', 'state': 'done', 'elapsed': 40, 'finished_at': _ago(const Duration(days: 3)),
         'log_kept': true, 'disk': {'log': 649, 'written': (7.5 * _mb).round(), 'files': 300, 'overlap': 0, 'partial': false, 'top': [{'path': '.home/', 'size': (7.5 * _mb).round()}]}},
        {'id': 'dj2', 'title': '启动库存监控网页服务', 'command': 'python3 monitor_app.py', 'state': 'done', 'elapsed': 5, 'finished_at': _ago(const Duration(days: 3)),
         'log_kept': true, 'disk': {'log': 856, 'written': 0, 'files': 0, 'overlap': 0, 'partial': false, 'top': []}},
      ],
      'machine': {'cpus': 2, 'load1': 0.2, 'memory_total': (3.8 * 1024 * _mb).round(), 'memory_used': (1.4 * 1024 * _mb).round(),
                  'disk_total': (34.3 * 1024 * _mb).round(), 'disk_used': (23.5 * 1024 * _mb).round()},
    };

Map<String, dynamic> browserSessionsFixture() => {
      'sessions': [
        {'name': 'huaweicloud', 'label': 'huaweicloud.console', 'saved': true, 'last_used': _ago(const Duration(hours: 11))},
        {'name': 'greencloud', 'label': 'greencloudvps.com', 'saved': true, 'last_used': _ago(const Duration(days: 3))},
        {'name': 'itsllm', 'label': 'itsllm.com', 'saved': true, 'last_used': _ago(const Duration(days: 3))},
      ],
    };

Map<String, dynamic> hostFixture() => {'installed': false, 'enabled': false, 'reachable': false, 'rules': []};

Map<String, dynamic> usageFixture() {
  final now = DateTime.now();
  String day(int d) => '${now.year}-${now.month.toString().padLeft(2, '0')}-${d.toString().padLeft(2, '0')}';
  const busy = {15: 5600000, 16: 5400000, 17: 5300000, 18: 109000};
  return {
    'currency': 'CNY',
    'budget': null,
    'priced': <String>[],
    'today': {'calls': 6, 'tokens': 108000, 'cost': 0, 'models': [
      {'model': 'fast', 'calls': 6, 'prompt_tokens': 100000, 'completion_tokens': 9000, 'cost': 0},
    ]},
    'month': {
      'calls': 1297,
      'tokens': 22000000,
      'cost': 0,
      'models': [
        {'model': 'fast', 'calls': 1217, 'prompt_tokens': 22000000, 'completion_tokens': 199000, 'cached_tokens': 12760000, 'cost': 0},
        {'model': 'smart', 'calls': 9, 'prompt_tokens': 158000, 'completion_tokens': 1900, 'cached_tokens': 86900, 'cost': 0},
        {'model': 'lite', 'calls': 64, 'prompt_tokens': 9900, 'completion_tokens': 5000, 'cost': 0},
        {'model': 'stepaudio-2.5-tts', 'calls': 3, 'prompt_tokens': 853, 'completion_tokens': 0, 'cost': 0},
        {'model': 'stepaudio-2.5-asr', 'calls': 4, 'prompt_tokens': 447, 'completion_tokens': 52, 'cost': 0},
      ],
    },
    'daily': [
      for (var d = 1; d <= now.day; d++)
        {'date': day(d), 'tokens': busy[d] ?? 0, 'calls': busy[d] == null ? 0 : (busy[d]! / 18000).round(), 'cost': 0},
    ],
    'conversations': [
      {'id': 'c1', 'title': '部署库存监控网页', 'calls': 210, 'tokens': 3900000, 'cost': 0},
      {'id': 'c2', 'title': '整理 VPS 磁盘', 'calls': 160, 'tokens': 2800000, 'cost': 0},
      {'id': 'd1', 'title': null, 'calls': 31, 'tokens': 618000, 'cost': 0},
      {'id': 'c3', 'title': '考研英语作文批改', 'calls': 40, 'tokens': 420000, 'cost': 0},
      {'id': 'd2', 'title': null, 'calls': 12, 'tokens': 260000, 'cost': 0},
      {'id': 'd3', 'title': null, 'calls': 8, 'tokens': 180000, 'cost': 0},
      {'id': 'd4', 'title': null, 'calls': 8, 'tokens': 161000, 'cost': 0},
      {'id': 'd5', 'title': null, 'calls': 5, 'tokens': 90000, 'cost': 0},
    ],
    'last_month': {'calls': 0, 'tokens': 0, 'cost': 0, 'to_date': {'calls': 0, 'tokens': 0, 'cost': 0}},
  };
}

Map<String, dynamic> usageDayFixture() => {
      'currency': 'CNY',
      'priced': <String>[],
      'total': {'calls': 6, 'tokens': 109000, 'models': [
        {'model': 'fast', 'calls': 6, 'prompt_tokens': 100000, 'completion_tokens': 9000, 'cost': 0},
      ]},
      'conversations': [
        {'id': 'c1', 'title': '部署库存监控网页', 'calls': 6, 'tokens': 109000, 'cost': 0},
      ],
    };
