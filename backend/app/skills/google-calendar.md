# Google 日历
查看日程、找空档、创建或修改日程。需要先连上 Google。

1. 查日程：api_request GET https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin=<RFC3339>&timeMax=<RFC3339>&singleEvents=true&orderBy=startTime
2. 时间一律带时区（默认 Asia/Shanghai，+08:00）。
3. 多条日程用 show_table（时间、标题、地点）。
4. 新建：POST .../calendars/primary/events，body 含 summary、start.dateTime、end.dateTime；会通知他人时先问用户。
5. 修改用 PATCH .../events/<id>；删除前确认。
