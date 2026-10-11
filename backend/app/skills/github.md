# GitHub
查看仓库、Issue、PR，必要时创建 Issue 或评论。需要先连上 GitHub。

1. 我的仓库：api_request GET https://api.github.com/user/repos?sort=updated&per_page=10
2. Issue：GET https://api.github.com/repos/<owner>/<repo>/issues?state=open
3. PR：GET https://api.github.com/repos/<owner>/<repo>/pulls
4. 列表用 show_table（标题、状态、更新时间、链接）。
5. 写操作（建 Issue、评论）先把内容给用户看，会弹审批卡。
6. 改代码在项目里做：run_command 里 git clone，改完提交和推送都需要用户批准。
