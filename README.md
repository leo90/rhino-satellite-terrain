# Rhino Satellite Terrain

从天地图卫星影像中框选区域，在 Rhino 中生成带卫星贴图的真实 DEM 地形，并可叠加 OpenStreetMap 道路、水系与建筑体块。

## 功能

- 本机交互式地图框选，范围以 WGS84 坐标保存。
- 通过本机回环地址代理天地图 `img_w`/`cia_w` WMTS 瓦片，支持服务器端类型的 `TIANDITU_KEY`。密钥只留在本机 `.env`，不会嵌入或发送给浏览器。
- 使用 AWS Terrain Tiles（Terrarium）生成可编辑 Rhino 网格。
- 可选导入 OSM 道路、水域、建筑体块与建筑轮廓，并保留来源与要素 ID。
- 输出 Rhino `.3dm`、卫星贴图、DEM 数据和质量报告。

## 环境要求

- Windows、Rhino（用于打开/导入生成的 `.3dm`）
- Python 3.12 或更新版本
- 天地图开发者应用密钥 `TIANDITU_KEY`，且该应用已开通需要的瓦片服务
- 可访问天地图 WMTS、AWS Terrain Tiles 与 OSM Overpass 服务的网络

## 申请天地图服务器端应用密钥（TK）

本 skill 在本机 Python 服务端请求天地图 WMTS 瓦片，因此应创建“服务器端”应用；不要把这个 TK 填入网页代码、公开仓库或截图。天地图控制台界面可能调整，以下按“应用管理 / 我的应用”流程说明。官方入口：[天地图](https://www.tianditu.gov.cn/)、[地图服务与 API 文档](https://lbs.tianditu.gov.cn/server/MapService.html)、[开发者控制台 / Key 管理](https://console.tianditu.gov.cn/api/key)。

1. 打开[天地图官网](https://www.tianditu.gov.cn/)，注册或登录账号。也可以直接打开[开发者控制台](https://console.tianditu.gov.cn/api/key)；首次使用时按提示完成个人开发者认证/实名认证。没有企业资质时，选择个人开发者身份即可。
2. 进入“控制台” → “应用管理” → “我的应用”，点击“创建应用”或“创建新应用”。如果系统先要求申请成为开发者，先提交个人开发者申请并按页面提示完成认证。
3. 填写应用信息。应用名称可用 `rhino-terrain`；行业类别按实际用途如实选择（例如建筑/住建相关类别）；应用类型选择 **服务器端**。这个类型与本工具的本机后端取瓦片方式相符，浏览器页面本身不会拿到 TK。
4. 在服务类别中选择“基础服务”，然后只开启本工具需要的 **“瓦片服务”**。不需要的服务保持关闭，减少密钥可调用的范围。若创建页面把服务权限放在另一处，创建后进入应用的“设置/服务权限”补开瓦片服务。
5. 检查“IP白名单”。服务器端校验的是发出天地图请求的机器的**公网出口 IP**，不是浏览器地址 `127.0.0.1`，也不是电脑的局域网地址（如 `192.168.x.x`）。如果你的公网出口 IP 固定，可按控制台格式填入以限制调用；如果是家庭宽带、IP 会变化，白名单可能导致换网后请求失败。控制台若仍显示“留空表示不限制”，留空即不启用 IP 限制；此时更要妥善保管 TK、只勾选必需服务并关注配额。
6. 阅读并接受页面上的服务条款/声明，提交创建。若应用状态显示待审核，等状态允许调用后再测试。
7. 回到“我的应用”，打开刚创建的应用详情，复制该应用对应的 **服务器端 TK / 应用密钥**。请勿复制成其他应用的 TK，也不要把它发到聊天、截图、Issue 或公开仓库中。
8. 在仓库根目录复制 `.env.example` 为 `.env`，仅在本机编辑这一行：

   ```dotenv
   TIANDITU_KEY=粘贴服务器端TK
   ```

   等号两侧不要加空格；不要加引号。`.env` 已由 `.gitignore` 忽略。可以用 `git check-ignore -v .env` 确认 Git 正在忽略它；提交时只保留 `.env.example` 中的空值模板。
9. 用本 skill 的地图选取器进行实际验证。如果瓦片加载失败，依次检查 TK 是否完整、应用是否为服务器端、是否启用了“瓦片服务”、应用审核状态/服务配额，以及 IP 白名单是否包含当前公网出口地址。不要把含 `tk=` 的完整请求 URL复制或公开。

天地图官方文档说明，调用相关服务需要申请 Key，并在控制台配置服务权限；如控制台字段名称或认证要求与本文不同，以当前控制台页面和对应服务文档为准。个人开发者的具体额度、可调用范围及下载/缓存/再分发权限以账号页面和适用服务条款为准；本说明不扩展这些授权范围。

## 安装与配置

在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

在 `.env` 中填写本机密钥：

```dotenv
TIANDITU_KEY=在这里填入你的天地图tk
```

`.env` 已被 `.gitignore` 忽略。不要把真实密钥写进 README、脚本、截图、选择文件或提交记录；`.env.example` 只保留空值。

## 选择场地

```powershell
.venv\Scripts\python.exe scripts\map_picker.py --env-file .\.env --out .\terrain-selection.json --port 8765
```

脚本会打印本机页面地址。打开后平移/缩放到目标位置，点“开始框选”，拖出矩形，再点“确认此范围”。页面确认天地图瓦片加载后才允许开始框选。

出于服务器端密钥安全，选取器只绑定 loopback（默认 `127.0.0.1`）；不要改造成公网代理，也不要把带密钥的请求地址复制或发布。页面通过同源 `/tiles/...` 路径取图，密钥由本机服务端注入。

## 生成 Rhino 地形

```powershell
.venv\Scripts\python.exe scripts\prepare_rhino_terrain.py `
  --env-file .\.env `
  --selection .\terrain-selection.json `
  --out .\terrain.3dm
```

生成默认参数：DEM zoom 14、地形网格最长边最多 512 个采样点、天地图影像最高使用 WMTS level 18、贴图边长上限 4096 px、卫星瓦片上限 1000、贴图目标分辨率不粗于 0.5 m/px。OSM 默认启用；不需要时可添加 `--no-osm`。

### 影像精度门槛

报告中的 `texture_ground_resolution_m_per_pixel` 是所选区域映射到贴图后的实际地面像素尺寸。默认必须 ≤0.5 m/px；若最高 zoom 的源影像本身达不到，脚本会停止，不会默默降低标准或上采样伪造细节。先确认是否由贴图尺寸或瓦片预算造成：只有这些限制确实生效时，提高 `--max-texture` / `--max-sat-tiles` 才有帮助。若是影像源的原生分辨率限制，需要先取得用户明确同意，再按其接受值设置 `--max-ground-resolution`，并在报告中保留实际分辨率与阈值。

## 结果与精度

生成器会在 `.3dm` 旁输出：

- `*_satellite.jpg`：天地图卫星贴图
- `*_elevation.npz`：采样高程数据
- `*.report.json`：范围、DEM/影像分辨率、网格统计、OSM 要素数、来源与限制

地形采用本地米制坐标，原点为选区西南角。DEM、卫星影像与 OSM 的来源精度各不相同；Rhino 网格更密不代表地形测量精度更高。OSM 道路为中心线；建筑高度只使用 OSM 提供的 `height` 或明确注明估算假设的 `building:levels`，缺高度的建筑只生成轮廓。该成果适用于区域场地研究与概念设计，不是测绘成果。

## 数据署名与发布注意事项

- 天地图：按适用服务条款保留“国家地理信息公共服务平台 天地图”署名。本 skill 不推定用户拥有超出其服务条款的瓦片或衍生数据再分发权；公开发布模型、贴图或缓存前，应单独核对许可范围。
- OpenStreetMap：数据按 ODbL 1.0 提供，分发 OSM 衍生成果时遵守署名与许可义务。
- 高程：AWS Terrain Tiles / Terrarium。核对其数据与服务条款后再分发生成物。
- 仓库软件许可尚未指定。公开仓库前由仓库所有者选择并添加适当的软件许可证；不要把数据服务许可误当成仓库代码许可证。

## GitHub 发布前检查

```powershell
git check-ignore -v .env
git status --short --ignored
git ls-files
```

确认 `.env` 显示为 ignored，且未出现在 staged/tracked 文件中；检查差异中没有任何密钥值。只提交 `.env.example` 的空模板，不提交 `.env`、生成的选择范围、贴图、DEM 缓存、模型或报告。

## 仓库结构

- `SKILL.md` — Codex skill 工作流与质量门槛
- `scripts/map_picker.py` — 回环绑定的本机地图与瓦片代理
- `assets/map_picker.html` — 卫星地图框选页面
- `scripts/prepare_rhino_terrain.py` — DEM/影像/OSM 处理及 `.3dm` 生成
- `references/data-and-accuracy.md` — 数据来源、坐标和精度说明
- `.env.example` — 不含密钥值的环境变量模板
