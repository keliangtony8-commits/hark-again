/// 一轮回复怎么结束的（服务器消息 status；v1.52 interrupted，v1.56 wrapped / looped）。
/// 不是 done 的回复：操作行尾标一句说明（[label]），最后一条另给“继续”（[continueText]，发出去就是一句普通的“继续”，
/// 服务器在下一轮历史里给模型附上对应说明：turn_journal.history_note）。
enum ReplyEnd {
  /// 正常说完。
  done,

  /// 用户中途点了停止，内容是半截的。
  stopped,

  /// 服务器进程在这一轮中途没了（崩溃 / 重启），回答没说完（turn_journal 恢复出来的）。
  interrupted,

  /// 步数 / 用量预算用完，模型交代了进度收尾（loop.Limits）。内容完整，事没做完。
  wrapped,

  /// 原地打转被叫停（loop_guard 第二次判定）。
  looped;

  static ReplyEnd parse(Object? status) => switch (status) {
        'stopped' => stopped,
        'interrupted' => interrupted,
        'wrapped' => wrapped,
        'looped' => looped,
        _ => done,
      };

  /// 内容本身是半截的（停止 / 被打断）：重新生成能补全。
  bool get cutShort => this == stopped || this == interrupted;

  /// 事没做完：最后一条回复给“继续”。
  bool get continuable => this != done;

  /// 值得用警示色的结束方式（不是用户自己停的）。
  bool get warn => this == interrupted || this == looped;

  /// 操作行尾的说明；done → null。导出 Markdown 也用这句。
  String? get label => switch (this) {
        done => null,
        stopped => '已停止',
        interrupted => '服务器重启，回答被打断',
        wrapped => '步数用完，先停在这里',
        looped => '原地打转，先停下了',
      };

  /// “继续”按钮的读屏说明。
  String get continueHint => switch (this) {
        looped => '让助手换个做法接着做',
        _ => '让助手从停下的地方接着做',
      };
}

/// “继续”发出去的原话（和用户自己打字一样，服务器不需要新接口）。
const continueText = '继续';
