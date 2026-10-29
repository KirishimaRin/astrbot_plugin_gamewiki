# MiSans 字体资源

本插件使用 MiSans 字体：正文使用 Regular，标题和分节使用 Medium。
字体内置版权声明为 `Copyright © 2020–2025 Beijing Xiaomi Mobile Software Co.,Ltd. All Rights Reserved.`，按随附的 [MiSans 字体知识产权许可协议](MiSans-LICENSE.pdf) 使用；字体资源不适用本项目代码的 MIT 许可。

这两个字体文件从小米官方字体包中直接取出，保持原始字节、字体内部版权声明与字重，不进行裁剪、转换或修改。它们作为游戏百科插件的渲染资源随软件提供。字体使用与许可说明亦见插件 README 和 doctor 诊断。

- 官方下载页：<https://hyperos.mi.com/font/zh/download/>
- 官方原始字体包：<https://hyperos.mi.com/font-download/MiSans.zip>
- 官方许可文件：<https://hyperos.mi.com/font-download/MiSans字体知识产权许可协议.pdf>

| 文件 | SHA-256 |
|---|---|
| MiSans-Regular.ttf | `9c120f0a849bc0aa5048daae2a3c0f6eecd828b5b33fce682a9622833f5feea6` |
| MiSans-Medium.ttf | `b03e98374e971594b0b7a9706d0704241f76e1b88556cdda79c5039ef8a638d1` |

服务器安装插件后即可离线使用内置字体，不需要系统字体安装、字体下载或 fc-cache 操作。数据目录 `fonts/` 中的 MiSans 文件可覆盖内置版本。
