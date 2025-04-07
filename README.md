# 保研信息查询插件 (astrbot_plugin_csbaoyan)

这个插件可以帮助你随时查询最新的保研信息，包括各大高校的夏令营、冬令营等保研通知。数据来源于 [CS-Baoyan](https://github.com/orgs/CS-BAOYAN/repositories) 社区。

## 功能特点

- 数据几乎实时更新：自动从 [CS-Baoyan](https://github.com/orgs/CS-BAOYAN/repositories) 获取最新保研信息
- 灵活筛选：可按标签筛选项目，支持多标签组合查询
- 即将截止提醒：查看即将截止的项目，避免错过重要日期
- 清晰展示：以文本形式展示查询结果，一目了然
- 支持搜索：可以通过项目名称进行模糊搜索
- 支持订阅：可以订阅保研信息更新通知（仅 aiocqhttp、Telegram 适配器可用）


## 使用方法

### 基本命令

> `/baoyan` 可以替换为 `/by`
> `list` 可以替换为 `ls`
> `upcoming` 可以替换为 `up`

- `/baoyan list [tag]` - 列出保研项目（可选标签筛选，多个标签用逗号分隔）
- `/baoyan sources` - 列出所有可用的数据源
- `/baoyan set_default <source>` - 设置默认数据源
- `/baoyan tags` - 列出当前数据源中的所有标签
- `/baoyan upcoming [tag]` - 列出30天内即将截止的项目（可选标签筛选，多个标签用逗号分隔）
- `/baoyan detail <name>` - 查看特定项目的详细信息
- `/baoyan update` - 手动更新保研信息数据
- `/baoyan sub` - 订阅保研信息更新通知(仅 aiocqhttp、Telegram 适配器可用)
- `/baoyan unsub` - 取消订阅保研信息更新通知

默认 10 分钟更新一次数据。

### 示例

```bash
# 查看所有可用数据源
/baoyan sources

# 列出当前数据源中的前10个项目
/baoyan list

# 查看拥有"985"标签前10个项目
/baoyan list 985

# 查看同时拥有"985,C9"标签的前10个项目
/baoyan list 985,C9

# 列出30天内即将截止的项目
/baoyan upcoming # 或者 /by up

# 列出30天内即将截止的985高校项目
/baoyan upcoming 985 # 或者 /by up 985

# 搜索
/baoyan search 北京科技大学

# 手动更新数据
/baoyan update
```

## 数据源

本插件从 CSBaoyan 社区获取最新的保研项目数据：`https://ddl.csbaoyan.top/config/schools.json`

数据结构如下：

```json
{
  "camp2025": [
    {
      "name": "清华大学",
      "institute": "智能产业研究院",
      "description": "冬令营（寒假期间进行的科研实习）",
      "deadline": "2025-01-10T00:00:00+08:00",
      "website": "https://air.tsinghua.edu.cn/info/1007/2129.htm",
      "tags": ["985", "211", "TOP2", "C9"]
    },
    // 更多项目...
  ],
  "camp2024": [
    // 2024年的项目
  ]
}
```

## 配置选项

在插件配置中，你可以设置：

- `update_interval`: 自动更新数据的时间间隔，单位为分钟（默认：10分钟）
- `max_display_items`: 查询结果最多显示的项目数量（默认：10）
