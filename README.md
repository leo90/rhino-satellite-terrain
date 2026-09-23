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
