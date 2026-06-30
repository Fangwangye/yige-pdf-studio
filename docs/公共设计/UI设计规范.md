# UI 设计规范

实现于 `static/styles.css`，以 CSS 变量为单一事实源。

## 配色（`:root`）

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--ink` | `#151716` | 主文字 |
| `--muted` | `#5d6661` | 次要文字 |
| `--line` | `#d7ddd8` | 边框/分隔线 |
| `--paper` | `#eef2ee` | 页面底色 |
| `--panel` / `--panel-strong` | `#fbfcf8` / `#fff` | 卡片/输入背景 |
| `--accent` / `--accent-dark` | `#0d7a68` / `#084d42` | 主青绿（按钮、激活态、焦点） |
| `--warm` | `#b86d2c` | 进行中/待办状态 |
| `--danger` | `#a63b2a` | 错误/删除 |

侧边栏用深青绿渐变（`#0f3b34→#0a2c27`）形成主次对比。

## 间距与圆角

- 圆角：卡片 `--radius: 12px`，按钮/输入 `8px`。
- 卡片内边距 `18px`，视图滚动区 `22px 24px`。
- 栅格间距统一 `12–16px`。

## 组件

### 按钮 `.btn`
- `.btn-primary`（青绿实心，主操作）、`.btn-ghost`（描边，次操作）、`.btn-danger-ghost`（hover 变红，删除）。
- `.btn-sm` 小号；`.is-disabled`/`:disabled` 统一灰态。

### 表单 `.field`
- 标签 `span` 12px 加粗 muted，控件统一 40px 高、8px 圆角，焦点用青绿描边 + 3px 光晕。

### 卡片 `.card`
- `.card-head`（可 `.row` 两端对齐）+ 内容。`.card-desc` 为说明文字。

### 状态色点
- 任务/质检用 `::before` 圆点或徽标：成功=青绿、进行中/排队=暖橙、失败=红、待定=灰。

## 响应式断点

- `≤1100px`：栅格收为单/双列，翻译按钮占满行。
- `≤860px`：隐藏侧边栏，预览改为上下堆叠。

## 约定

- 新增颜色必须先进 `:root` 变量，禁止散落硬编码色值。
- 新增视图沿用 `.view[data-panel]` + nav `data-view` 的约定，并在 `app.js` 的 `viewMeta` 补标题/副标题。
- 改样式后给 `index.html` 的 `?v=` 版本号 bump 以破缓存。
