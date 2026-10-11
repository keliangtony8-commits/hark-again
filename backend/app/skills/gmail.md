# Gmail
读邮件、搜邮件、起草邮件。需要先在“连接的账户”里连上 Google。

1. 搜索：api_request GET https://gmail.googleapis.com/gmail/v1/users/me/messages?q=<Gmail 搜索语法>&maxResults=10
2. 读一封：GET .../users/me/messages/<id>?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date（要正文用 format=full，正文是 base64url）
3. 多封邮件结果用 show_table（发件人、主题、时间）。
4. 写邮件：只创建草稿 POST .../users/me/drafts，body 为 {"message":{"raw":<base64url 的 RFC822>}}；先把完整草稿给用户看，用户明确同意才创建。
5. 绝不直接发送；发送永远让用户自己点。
