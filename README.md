# 314159 · 小红书小工具打包

在这个仓库打开 Codex，告诉它游戏项目的路径。它会读游戏、接入适用的平台功能，交回 ZIP、发布表单和首发笔记草稿。只做本地适配与打包时无需登录小红书。

[看一份填好的后台表单示例](表单示例.md)

**直接发给 AI**

> 读这个仓库的 AGENTS.md，按 314159 小红书流程把「游戏路径」做成免费小工具。接关注、可用时赞赏，结尾推荐一款相关作品。请实际修改、校验并打包，交付 ZIP、后台填写单和首发文案。图标和封面由我按本款游戏定稿，有文件就检查，缺项先标待提供。只做本地交付。

**要做付费番外时加这一句**

> 主篇免费，另做独立付费番外《名称》，售价「金额」元，购买后能玩「具体的一幕／玩法」。请分别打包并生成两份填写单。已有目标 appId 为「编号」；还没上架就先隐藏跳转，等我给真实 appId 再接。

整款收费可直接说「整款付费，售价 × 元，购买后可以……」。发布后不能切换免费／付费。定价未给时保留待确认。更新工具链时在干净的仓库运行 `git pull --ff-only`，官方规范版本以当次上传页为准。

## 一起做这个工具

你在做哪种小工具，哪一步最费劲？欢迎提一个想法。发现小红书更新了规则，或某款手机上跑不通，也欢迎来报。直接写使用场景就可以，有相同问题也可以在已有 Issue 补充一次实测结果。

[提想法或补充平台规则](https://github.com/23333ironnnnn/314159-xhs-minitool/issues/new?template=01-idea.yml) · [反馈适配或打包问题](https://github.com/23333ironnnnn/314159-xhs-minitool/issues/new?template=02-problem.yml) · [看看大家在聊什么](https://github.com/23333ironnnnn/314159-xhs-minitool/issues)

## 手动运行

需要 Python 3.9+。打包已有离线产物不装 npm 依赖。先按 [适配流程](AGENTS.md) 完成游戏构建，由 AI 参照 [表单示例](release.example.json) 填入真实资料。每款游戏的图标、封面及视觉说明放在本地游戏项目中，交付目录也选在这个公共工具仓库之外。表单中的图片路径相对于配置文件，可指向已定稿素材。

```sh
python3 release.py /path/to/game/dist /path/to/new-release --form /path/to/release.json
```

输出目录内有 `game.zip`、`发布填写单.md`、校验摘要，以及配置中传入的图标与封面。输出目录须为新路径，避免混到上版。仅检查一个开发构建时可省略 `--form`，得到带「待填写」的资料草稿。程序会检验入口、常见静态引用、包结构与体积，并在打包前后调用官方审计。动态资源、宿主 API、模拟器和两端真机按填写单分列验收。

## 维护

- 适配、运营与付费流程在 [AGENTS.md](AGENTS.md)。表单字段与机械检查在 [release.py](release.py)。后台小工具名称和简介各限 14 个 UTF-16 码元。
- 两个官方包完整保存在 `.codex/skills/`；`.agents/skills` 为仓库内发现入口。仅运行管理命令时另需 Node.js、npm 与官方版本校验。每次更新官方包都从创服当前口令取链接，先安全解压，保留旧版本，再检查引用和 CLI。
- 本仓库初始打包规范为 1.11.1。原始归档 SHA-256 分别为开发规范 `b9e7ba8265963ed19301084e3f73d3a26ba21dcec0cea9e4dc127abc2b928ed7`、管理包 `ebc76d1a94258903a4b35726b7e25e94b452b824cd6d9cde0f2434e22900a4b3`。[开发包](https://fe-static.xhscdn.com/minitool/20261117152455/minitool-zip-builder-1.11.1.skill) · [管理包](https://fe-video-qc.xhscdn.com/fe-platform-file/104101b8326rqruuj5006b6titltg00000000038l066g4)
