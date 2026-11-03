# 素材来源与许可证（ASSET_SOURCES）

本项目前端只使用可合法分发的开源图标与系统字体，运行时不访问任何 CDN/外网。

## 图标：Lucide

- 来源：https://github.com/lucide-icons/lucide （官方 GitHub 仓库）
- 版本：release **1.61.0**（asset lucide-icons-1.61.0.zip）
- 许可证：ISC（部分图标源自 Feather，MIT），完整文本见
  apps/sixmic-desktop/assets/licenses/LUCIDE_LICENSE.txt（取自官方仓库 tag 1.61.0 的 LICENSE）
- 本地化：只复制实际使用的 SVG（apps/sixmic-desktop/assets/icons/*.svg，清单见
  _used_icons.json，共 120 个）；保持 24×24 视盒、约 2px 描边；运行时按主题色在用户数据目录
  生成着色副本（ui/viewmodels/app_view_model.py: iconSource），SVG 原文与许可证保留在安装包内。
- 名称映射（官方 1.61.0 中的实际名称）：waves→audio-lines、building-2→building、
  alert-triangle→triangle-alert、filter→funnel、more-horizontal→ellipsis、
  area-chart→chart-area、plug-zap-2→plug-zap、unlock→lock-open 等（以 assets/icons 实际文件为准）。

## 应用 Logo（原创）

- apps/sixmic-desktop/assets/branding/logo.svg：六条声学采样线构成的简约标志（原创，未使用
  定位箭头，避免暗示自动 DOA）。随应用分发。
- sixmic3d.ico：由 logo.svg 渲染 16/24/32/48/64/128/256 多尺寸生成，用于 Windows
  任务栏/安装包；logo-256.png 供文档/页面使用。

## 字体

- 界面使用系统字体：Segoe UI / Segoe UI Variable（拉丁）与 Microsoft YaHei UI（中文）；
  数字使用 Cascadia Mono / 等宽回退。**未打包再分发任何系统或 Apple 字体**，符合许可要求。
- 若未来需要可分发字体，只能从 Inter / Noto Sans SC / JetBrains Mono 官方仓库引入必要子集并
  附带 OFL 文本；当前未引入。

## 主题与视觉

- 视觉 token 见 apps/sixmic-desktop/themes/tokens.py（按任务书第 4 节固定色值/圆角/字号）。
- 未使用任何商业软件截图、厂商 Logo、Web 图片或模板素材；绘图区网格、坐标轴、图表均为本项目
  程序化绘制。

## 获取与校验（可复现）

```powershell
curl -L -o lucide-icons-1.61.0.zip https://github.com/lucide-icons/lucide/releases/download/1.61.0/lucide-icons-1.61.0.zip
curl -L -o LUCIDE_LICENSE.txt https://raw.githubusercontent.com/lucide-icons/lucide/1.61.0/LICENSE
```

## 背景纹理（原创）

- apps/sixmic-desktop/assets/patterns/grid_tech.svg、retro_grid.svg、hex_tech.svg：
  本项目原创静态几何 SVG，用于欢迎/连接卡片与监测工作区头部；低对比度、无动画。
- 风格参考（未复制素材）：Magic UI（MIT）Animated Grid Pattern / Retro Grid；
  Pattern Monster（使用前需逐素材核验许可证）；React Bits（MIT + Commons Clause，
  因附加限制未集成）。详见 docs/frontend/DESIGN.md 与 FRONTEND_INTERFACE_CONTRACT.md 第 8 节。
