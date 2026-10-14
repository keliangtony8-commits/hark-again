// 偏好设置（v2.67，对标 Hark 设置 → System preferences）：服务器 /api/preferences 的数据。
// 现在只有“回复语言”：auto = 跟随我说的语言（默认）/ zh-Hans / zh-Hant / en。规则在后端 app/reply_language.py，
// 选项和显示名由服务器给（这里不写死），所以以后加语言 App 不用改。

class LanguageChoice {
  const LanguageChoice(this.code, this.label);
  final String code, label;
}

class Preferences {
  const Preferences({required this.replyLanguage, required this.choices});
  final String replyLanguage;
  final List<LanguageChoice> choices;

  static const auto = 'auto';

  factory Preferences.fromJson(Map<String, dynamic> j) => Preferences(
        replyLanguage: '${j['reply_language'] ?? auto}',
        choices: [
          for (final c in (j['reply_languages'] as List? ?? const []))
            if (c is Map) LanguageChoice('${c['code']}', '${c['label']}'),
        ],
      );

  Preferences copyWith({String? replyLanguage}) => Preferences(replyLanguage: replyLanguage ?? this.replyLanguage, choices: choices);

  /// “我的”页那一行的说明：当前选项的名字；没加载到 → 默认那句。
  String get replyLanguageLabel {
    for (final c in choices) {
      if (c.code == replyLanguage) return c.label;
    }
    return '跟随我的语言';
  }

  /// 菜单里每项下面的一行说明。
  static String hintFor(String code) => code == auto ? '我用什么语言说，就用什么语言回' : '不管我用什么语言说，都用它回；语音识别也跟着换';
}
