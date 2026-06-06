# 更新日志

所有重要的更改都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-06-06

### 💥 重大变更

- **渲染引擎替换**：移除 Playwright + Chromium 依赖，改用 [html2pic](https://github.com/francozanardi/html2pic)（基于 Skia + Taffy + HarfBuzz）
  - 磁盘占用从 ~300MB 降至 ~50MB
  - 无需安装浏览器或任何系统级依赖
  - 渲染速度基本持平（~1 秒/次）
  - 内存占用大幅降低

### 新增

- 🪶 **轻量渲染引擎**：html2pic 纯 pip 安装，即装即用
- 🔵 **抗锯齿圆形头像**：使用 4x 超采样 + LANCZOS 缩放，头像边缘平滑无锯齿
- 🎨 **渐变色头像占位符**：无头像用户显示渐变色圆形头像 + 姓氏首字

### 移除

- ❌ Playwright 浏览器依赖（`playwright>=1.40.0`）
- ❌ 浏览器实例管理（页面池、路由拦截、浏览器启动/关闭）
- ❌ JS 气泡宽度动态计算脚本

### 技术细节

渲染流程变更：

1. 旧：Playwright 打开页面 → 加载 HTML → JS 计算宽度 → 截图
2. 新：html2pic 构建 HTML+CSS → Skia 渲染 → Pillow 后处理（圆形头像裁剪）

html2pic CSS 适配：

| 原始 CSS | 适配后 | 原因 |
|---|---|---|
| `background: #fff` | `background-color: #fff` | html2pic 不支持 `background` 简写 |
| `border-radius: 50%` | Pillow 后处理圆形裁剪 | html2pic 在 flex 布局中 border-radius 不裁剪背景 |
| `border-left: 3px solid` | 移除 | html2pic 不支持 |
| `width: fit-content` | 移除，用 min/max-width | html2pic 不支持 |
| `↩` 字符 | 移除 | html2pic 渲染不支持的 Unicode 字符会崩溃 |
| `white-space: pre-wrap` | Python 中 `\n` → `<br>` | html2pic 不支持 |

---

## [1.0.0] - 2026-04-02

### 新增

- ✨ 核心功能：将 QQ 群聊消息渲染为精美的引用图片
- 🎨 QQ 聊天气泡样式 1:1 复刻，完美还原群聊界面
- 📸 支持连续引用多条消息（1-20 条）
- 📅 智能日期分隔，跨日期消息自动显示日期线
- 💬 支持消息内回复预览，还原真实对话场景
- 🔍 智能语录检索功能
  - 基于关键词搜索
  - 按用户 ID 筛选
  - 按群号筛选
  - 全局搜索（跨群）
- 🤖 LLM 工具集成，支持 AI 助手调用搜索和随机展示
- 🎯 相似语录检测，基于 pHash 算法自动识别重复
- 📝 可选 OCR 文字识别，让图片中的文字可搜索
- ⚡ 自定义触发词，支持无斜杠触发
- 🗑️ 语录删除功能，支持权限控制
- 📊 语录统计信息查看

### 改进

- ⚡ **FTS5 全文搜索**：使用 SQLite FTS5 索引，大幅提升搜索性能
- 🔒 **权限控制**：`/qdel` 命令支持配置管理员权限要求
- 🛡️ **错误处理**：完善错误日志记录，便于问题排查
- 🎭 **浏览器管理**：优化 Playwright 浏览器实例管理，提升并发性能
- 💾 **去重机制**：保存前自动检测相似语录，避免重复存储

### 配置选项

#### 触发词配置
- `q_trigger`: 生成语录触发词
- `qsearch_trigger`: 搜索语录触发词
- `qrandom_trigger`: 随机语录触发词

#### 渲染选项
- `show_title`: 显示群头衔（默认 true）
- `show_time`: 显示消息时间（默认 false）
- `show_date`: 显示日期分隔（默认 false）

#### OCR 选项
- `enable_ocr`: 启用图片 OCR 识别（默认 false）

#### 权限选项
- `qdel_require_admin`: 删除语录需要管理员权限（默认 true）

### 技术特性

- 基于 **Playwright** 进行浏览器渲染
- 使用 **SQLite + FTS5** 存储和索引数据
- 支持 **pHash** 感知哈希算法进行图片去重
- 完整的 **异步支持**，性能优异
- 兼容 **AstrBot 4.0+**

### 命令列表

| 命令 | 说明 |
|------|------|
| `/q [数量]` | 生成语录图片 |
| `/qsearch <关键词>` | 搜索语录 |
| `/qrandom` | 随机语录 |
| `/qstats` | 查看统计 |
| `/qdel` | 删除语录 |

### 渲染选项

```bash
/q --title 0    # 不显示群头衔
/q --time 1     # 显示消息时间
/q --date 1     # 显示日期分隔
/q 3 --title 1 --time 0  # 组合使用
```

---

## 版本规划

### 计划中

- [ ] 语录导出功能
- [ ] 更多渲染样式主题
- [ ] 语录收藏夹功能
- [ ] 批量管理工具

---

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

本项目采用 AGPL-3.0 许可证 - 详见 [LICENSE](LICENSE) 文件
