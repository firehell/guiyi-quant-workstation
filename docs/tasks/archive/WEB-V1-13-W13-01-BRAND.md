# WEB-V1-13 W13-01 品牌资产验收

日期：2026-07-22

状态：`WEB_BRAND_IDENTITY_READY`

## 来源与派生

- 原始效果图：`apps/quant-web/src/assets/brand/original/user-professional-g-reference.png`
- Web 唯一 symbol：`apps/quant-web/src/assets/brand/brand-symbol.svg`
- 组件入口：`BrandMark.vue`、`BrandLogo.vue`
- favicon：`apps/quant-web/public/favicon.svg`

原始效果图保持原样。Web symbol 只提取深色圆角底、蓝色几何 G 与右侧终笔；未引入截图标题、说明文字、渐变、阴影或额外图形。horizontal 形态由 `BrandLogo.vue` 组合，避免复制品牌几何。

## 语义边界

- 品牌 accent 仅在 `tokens.css` 与 `theme.ts` 收口为 `#4e83ff` 系列。
- `--gy-up`、`--gy-down` 与状态色未改变语义。
- `MainLayout.vue` 已删除 CSS 柱形临时标记。
- 折叠侧栏保留可访问的 Logo 图像；展开侧栏显示中英文品牌名。

## 验收证据

- 品牌 E2E 先失败于缺少 `img[alt="归一量化"]`，实现后转绿。
- mock E2E：10 passed。
- Playwright 快照确认 Logo 具有可访问名称，1280×720 折叠侧栏可见。
- 视觉截图：`output/playwright/w13-01-brand-dashboard.png`（本地验收工件，不是 canonical 状态源）。

Gate：

```text
WEB_BRAND_IDENTITY_READY
WEB_BRAND_ASSET_SINGLE_SOURCE_READY
NO_DUPLICATE_BRAND_ASSETS
```
