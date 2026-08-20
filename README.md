# 小流萤 wife_today 插件图床

这是 **小流萤 QQ 机器人**（[firefly-QQBot-offical-Framework](https://gitee.com/geng-dan/firefly-QQBot-offical-Framework)）的 `wife_today` 插件所需的二次元图床。

> ⚠️ **图床与主项目分离的原因**
>
> wife 图床 2.4GB / 2656+ 张二次元图片，体积太大、版权敏感（ACGN 内容），不适合直接放进主项目仓库。所以单独建一个仓库，按需下载。
>
> 主项目已 `.gitignore` 排除 `assets/wife/`，所以即使本仓库不下载，wife_today 插件也不会报错（找不到图片时随机一张或回退默认图）。

## 📦 仓库内容

```
img1/  2000 张（1.89 GB）  主流 ACGN 角色壁纸
img2/  656 张  (700 MB)    备用 / 补充图
```

## 🚀 下载方法

### 方式 1：从 Release 下载（**推荐**）

打开 https://gitee.com/geng-dan/bed-scene-with-wife/releases

下载最新版本的所有 7z 分卷（共 25 个，约 2.4GB），然后：

**Windows (7-Zip)：**
1. 把 25 个 .7z.001~.025 放到同一目录
2. 右键 `wife-gallery-2026.08.20.7z.001` → 「7-Zip」→ 「提取到当前文件夹」
3. 7z 会自动合并所有卷解压
4. 把解压出的 `img1/` `img2/` 复制到 `小流萤bot/assets/wife/`

**Linux / macOS：**
```bash
mkdir wife && cd wife
# 下载全部 25 个卷到此目录（用 Gitee Release 页面里的下载链接）
7z x wife-gallery-2026.08.20.7z.001   # 自动识别后续卷
```

### 方式 2：git clone（会下载 2.4GB，**不推荐**）

```bash
cd /path/to/小流萤bot/assets
git clone https://gitee.com/geng-dan/bed-scene-with-wife.git wife
```

这种方式等于把 2.4GB 当 git 仓库下载，速度慢、流量大。**强烈建议用方式 1**。

## 📂 文件命名

文件名格式为 `作品名!角色名.扩展名`（中间是英文 `!` 分隔），例如：

- `异环!娜娜莉·柯林斯.png`
- `明日方舟终末地!弭弗.png`
- `原神!丝柯克.png`

`wife_today` 插件会按以下顺序抽取：

1. `img1/` 随机一张
2. `img2/` 随机一张（回退）

## 📜 版权声明

本图床仅作**个人学习 / 个人娱乐**用途，所引用作品名称、角色名称归原作者所有，图片版权归原作者所有。

如您是版权方且不希望某张图片出现在本仓库，请提交 Issue / PR，我会立即删除。

## 📄 许可证

本图床采用 **MIT 协议**发布。
